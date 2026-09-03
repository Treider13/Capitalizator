"""LLM as an *extractor* behind a JSON schema. No keys of the exchange, no advice.

The model reads one post/headline and returns claims in a fixed shape:

  {"claims": [{"asset": "BTCUSDT", "side": "long|short|none", "target": "70000"|null,
               "horizon": "4h"|"1d"|"1w"|null, "confidence": 0..1}],
   "motive": {"promo": bool, "ref_link": bool}, "event_class": "...|none"}

Anything else in the reply is dropped; a reply that does not parse is a *null*
extraction (the post stays unparsed — canon: text without fields is not a call).
`trade_advice` cannot exist in the output: the schema has no such field and the
verifier never reads the model's words as facts — the desk resolves claims against
its own tape (`authors.resolve`).

Providers: anthropic (Messages API) and openai (Chat Completions), both over
urllib; the key comes from Settings (`llm.api_key`) and lives only in this process.
Spend is metered from the providers' usage fields against `llm.monthly_budget_usd`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.request import Request, urlopen

from capitalizator.ops.knowledge import Knowledge

Poster = Callable[[str, bytes, dict[str, str]], bytes]

SCHEMA_HINT = (
    "Extract trading claims from the text. Reply with ONLY a JSON object of the form "
    '{"claims":[{"asset":"<SYMBOL>USDT","side":"long|short|none","target":"<number or null>",'
    '"horizon":"<e.g. 4h,1d,1w or null>","confidence":<0..1>}],'
    '"motive":{"promo":<bool>,"ref_link":<bool>},'
    '"event_class":"<CPI|FOMC|SEC|listing|hack|outage|none>"}. '
    "Do not add fields. Do not give advice. If there is no claim, return an empty claims list."
)
ASSET_RE = re.compile(r"^[A-Z0-9]{2,15}USDT$")
HORIZON_RE = re.compile(r"^\d+(m|h|d|w)$")
EVENT_CLASSES = {"CPI", "FOMC", "SEC", "listing", "hack", "outage", "none"}

# USD per 1M tokens (input, output) — approximate list prices, used only for the budget meter.
PRICES = {
    "anthropic": (3.0, 15.0),
    "openai": (2.0, 8.0),
}


@dataclass(frozen=True)
class Claim:
    asset: str
    side: str
    target: str | None
    horizon: str | None
    confidence: float


@dataclass(frozen=True)
class Extraction:
    claims: tuple[Claim, ...]
    promo: bool
    ref_link: bool
    event_class: str
    tokens_in: int
    tokens_out: int
    cost_usd: float

    def payload(self) -> dict[str, Any]:
        return {
            "claims": [c.__dict__ for c in self.claims],
            "promo": self.promo,
            "ref_link": self.ref_link,
            "event_class": self.event_class,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": round(self.cost_usd, 6),
        }


def default_post(url: str, body: bytes, headers: dict[str, str]) -> bytes:
    req = Request(url, data=body, headers=headers, method="POST")
    with urlopen(req, timeout=60) as resp:  # noqa: S310 - fixed https provider hosts
        return resp.read()


class BudgetExceeded(RuntimeError):
    pass


class LLMClient:
    def __init__(
        self,
        *,
        provider: str,
        model: str,
        api_key: str,
        monthly_budget_usd: float,
        knowledge: Knowledge | None = None,
        post: Poster = default_post,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if provider not in {"anthropic", "openai"}:
            raise ValueError("provider must be anthropic|openai")
        if not api_key or not model:
            raise ValueError("llm api_key and model are required")
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.budget = float(monthly_budget_usd)
        self.knowledge = knowledge
        self._post = post
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    # --- budget meter -------------------------------------------------------------------
    def _month_key(self) -> str:
        return self._clock().strftime("%Y-%m")

    def spent(self) -> float:
        if self.knowledge is None or not self.knowledge.available():
            return 0.0
        raw = self.knowledge.meta(f"llm_spend:{self._month_key()}")
        try:
            return float(raw) if raw else 0.0
        except ValueError:
            return 0.0

    def _add_spend(self, usd: float) -> None:
        if self.knowledge is None or not self.knowledge.available():
            return
        self.knowledge.set_meta(f"llm_spend:{self._month_key()}", f"{self.spent() + usd:.6f}")

    # --- provider calls -------------------------------------------------------------------
    def _call(self, text: str) -> tuple[str, int, int]:
        prompt = f"{SCHEMA_HINT}\n\nTEXT:\n{text[:6000]}"
        if self.provider == "anthropic":
            body = json.dumps(
                {
                    "model": self.model,
                    "max_tokens": 600,
                    "temperature": 0,
                    "messages": [{"role": "user", "content": prompt}],
                }
            ).encode()
            raw = self._post(
                "https://api.anthropic.com/v1/messages",
                body,
                {
                    "content-type": "application/json",
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                },
            )
            data = json.loads(raw.decode())
            content = "".join(
                block.get("text", "")
                for block in data.get("content") or []
                if isinstance(block, dict)
            )
            usage = data.get("usage") or {}
            t_in = int(usage.get("input_tokens") or 0)
            t_out = int(usage.get("output_tokens") or 0)
            return content, t_in, t_out
        body = json.dumps(
            {
                "model": self.model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode()
        raw = self._post(
            "https://api.openai.com/v1/chat/completions",
            body,
            {"content-type": "application/json", "authorization": f"Bearer {self.api_key}"},
        )
        data = json.loads(raw.decode())
        choices = data.get("choices") or [{}]
        content = ((choices[0].get("message") or {}).get("content")) or ""
        usage = data.get("usage") or {}
        t_in = int(usage.get("prompt_tokens") or 0)
        t_out = int(usage.get("completion_tokens") or 0)
        return content, t_in, t_out

    def extract(self, text: str) -> Extraction | None:
        """None = unparsed (no claim recorded). Raises BudgetExceeded before a call."""
        if self.spent() >= self.budget:
            raise BudgetExceeded(f"llm budget {self.budget} USD reached for {self._month_key()}")
        content, t_in, t_out = self._call(text)
        p_in, p_out = PRICES.get(self.provider, (0.0, 0.0))
        cost = (t_in * p_in + t_out * p_out) / 1_000_000
        self._add_spend(cost)
        parsed = parse_extraction(content)
        if parsed is None:
            return None
        claims, promo, ref, event_class = parsed
        return Extraction(
            claims=tuple(claims),
            promo=promo,
            ref_link=ref,
            event_class=event_class,
            tokens_in=t_in,
            tokens_out=t_out,
            cost_usd=cost,
        )


def parse_extraction(content: str) -> tuple[list[Claim], bool, bool, str] | None:
    """Strict: unknown fields dropped, bad values → the claim is dropped, no JSON → None."""
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    claims: list[Claim] = []
    for raw in data.get("claims") or []:
        if not isinstance(raw, dict):
            continue
        asset = str(raw.get("asset") or "").upper().replace("/", "").replace("-", "")
        if asset and not asset.endswith("USDT"):
            asset = f"{asset}USDT"
        side = str(raw.get("side") or "none").lower()
        if not ASSET_RE.match(asset) or side not in {"long", "short", "none"}:
            continue
        horizon = raw.get("horizon")
        horizon_s = str(horizon).lower() if horizon not in (None, "", "null") else None
        if horizon_s is not None and not HORIZON_RE.match(horizon_s):
            horizon_s = None
        target = raw.get("target")
        try:
            target_s = None if target in (None, "", "null") else str(float(str(target)))
        except ValueError:
            target_s = None
        try:
            conf = max(0.0, min(1.0, float(raw.get("confidence") or 0.0)))
        except (TypeError, ValueError):
            conf = 0.0
        claims.append(
            Claim(asset=asset, side=side, target=target_s, horizon=horizon_s, confidence=conf)
        )
    motive = data.get("motive") if isinstance(data.get("motive"), dict) else {}
    event_class = str(data.get("event_class") or "none")
    if event_class not in EVENT_CLASSES:
        event_class = "none"
    return claims, bool(motive.get("promo")), bool(motive.get("ref_link")), event_class
