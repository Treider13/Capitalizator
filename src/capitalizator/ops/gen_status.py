"""Generate ops/STATUS-GENERATED.md from facts, not prose.

Facts collected: pytest summary (run here), ruff, module reachability from the
runtime entry points (AST import walk), recorder subscriptions, the list of
processes and their commands, and — when a userdir is given — the live knowledge:
touches, paper trades, ОКО organ maturity, intel items, blocked entries.

Usage: python -m capitalizator.ops.gen_status [--userdir DIR] [--out ops/STATUS-GENERATED.md]
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

# Long-running processes + operator CLIs (gates, backup, checks). Anything not
# reachable from these is library code nobody runs — listed, so it is a decision.
ENTRY_POINTS = (
    "capitalizator.desk.__main__",
    "capitalizator.signer.__main__",
    "capitalizator.recorder.app",
    "capitalizator.ops.console",
    "capitalizator.ops.night",
    "capitalizator.intel.run",
    "capitalizator.ops.compact_tape",
    "capitalizator.ops.gates",
    "capitalizator.ops.backup",
    "capitalizator.ops.gen_status",
    "capitalizator.ops.check_author_parsed",
    "capitalizator.ops.check_author_raw",
    "capitalizator.ops.check_parquet_count",
    "capitalizator.ops.check_skips",
    "capitalizator.ops.day_episodes",
    "capitalizator.ops.skip_log",
    "capitalizator.recorder.scan_keys",
    "capitalizator.ops.healthz",
)


def _src_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _modules() -> dict[str, Path]:
    root = _src_root()
    out: dict[str, Path] = {}
    for path in (root / "capitalizator").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(root).with_suffix("")
        name = ".".join(rel.parts)
        if name.endswith(".__init__"):
            name = name[: -len(".__init__")]
        out[name] = path
    return out


def _imports(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return set()
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
            out.update(f"{node.module}.{a.name}" for a in node.names)
    return {m for m in out if m.startswith("capitalizator")}


def reachability() -> tuple[list[str], list[str]]:
    mods = _modules()
    seen: set[str] = set()
    stack = [m for m in ENTRY_POINTS if m in mods]
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        for imp in _imports(mods[name]):
            cand = imp
            while cand and cand not in mods:
                cand = cand.rpartition(".")[0]
            if cand and cand not in seen:
                stack.append(cand)
            pkg = cand.rpartition(".")[0] if cand else ""
            if pkg and pkg in mods and pkg not in seen:
                stack.append(pkg)
    unreachable = sorted(m for m in mods if m not in seen and not m.endswith("__main__"))
    return sorted(seen), unreachable


def run_tests() -> str:
    proc = subprocess.run(
        [
            sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q",
            "-o", "addopts=--import-mode=importlib",
        ],
        capture_output=True,
        text=True,
        cwd=_src_root().parent,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    return lines[-1] if lines else f"pytest exit {proc.returncode}"


def run_ruff() -> str:
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "src", "tests"], capture_output=True, text=True,
        cwd=_src_root().parent,
    )
    return "чисто" if proc.returncode == 0 else f"ошибки: {proc.stdout.strip().splitlines()[-1]}"


def live_facts(userdir: Path | None) -> dict[str, object]:
    if userdir is None:
        return {}
    from capitalizator.ops.knowledge import open_knowledge
    from capitalizator.ops.vault import load_vault

    vault = load_vault(userdir)
    kn = open_knowledge(vault, create=False)
    try:
        if not kn.available():
            return {"knowledge": "нет"}
        journal = kn.journal_rows()
        paper = kn.paper_trades(limit=100_000)
        oko = kn.meta_prefix("oko:passport:")
        mature = 0
        for raw in oko.values():
            try:
                d = json.loads(raw)
                depth = d.get("depth") or {}
                n = int(depth.get("n") or len(depth.get("values") or []))
                if n >= 30:
                    mature += 1
            except (json.JSONDecodeError, ValueError, TypeError):
                continue
        return {
            "касаний в журнале": len(journal),
            "с исходом": sum(1 for r in journal if r.get("outcome") in {"bounce", "break", "die"}),
            "бумажных сделок (закрытых)": sum(1 for p in paper if p.get("closed_at")),
            "паспортов ОКО": len(oko),
            "паспортов ОКО зрелых (n≥30)": mature,
            "intel-элементов": len(kn.intel_items(limit=100_000)),
            "входы заблокированы": kn.meta("entries_blocked"),
            "режим": kn.meta("user_mode"),
            "hello": kn.meta("testnet_hello"),
            "recorder_status": (kn.meta("recorder_status") or "")[:200],
        }
    finally:
        kn.close()


def render(*, userdir: Path | None) -> str:
    reach, unreach = reachability()
    facts = live_facts(userdir)
    now = datetime.now(tz=UTC).isoformat(timespec="seconds")
    lines = [
        "# STATUS (сгенерировано)",
        "",
        f"Дата: {now}. Этот файл пишет `python -m capitalizator.ops.gen_status`; руками не редактировать.",
        "",
        f"- Тесты: **{run_tests()}**",
        f"- Ruff: **{run_ruff()}**",
        f"- Модулей достижимо из точек входа: **{len(reach)}**; недостижимо: **{len(unreach)}**",
        "",
        "## Процессы (infra/deploy/compose.yml)",
        "",
        "| Процесс | Команда | Что делает |",
        "|---|---|---|",
        "| recorder | `capitalizator.recorder.app --live-ws` | сырой WS Bybit: сделки, дельты книги, "
        "тикеры (OI/фандинг), ликвидации → jsonl (живой) + parquet (архив); instruments-info раз в час |",
        "| desk | `capitalizator.desk --serve` | зоны → касание → CAV/ZLG (выжившая ликвидность)/PRS → "
        "ОКО → жюри (факт книги обязателен) → бумага → интент |",
        "| signer | `capitalizator.signer --serve` | единственный с ключом: pybit, липкий блок входов, "
        "сторож по эпизодам, сверка REST без усыновления, unknown→resolve |",
        "| intel | `capitalizator.intel --serve` | RSS/Reddit/X/Hyperliquid/Bybit public/F&G → knowledge; "
        "LLM-экстрактор по схеме; резолюция авторов на своей ленте |",
        "| console | `capitalizator.ops.console --serve` | 127.0.0.1:8082: стол, настройки (ключи/источники), словарь кодов |",
        "| night | shell-цикл | ночной контур 00:30 UTC, компакция ленты каждый час |",
        "",
        "## Недостижимые из рантайма модули",
        "",
    ]
    lines += [f"- `{m}`" for m in unreach] or ["- нет"]
    if facts:
        lines += ["", "## Живые факты (userdir)", ""]
        lines += [f"- {k}: `{v}`" for k, v in facts.items()]
    lines += [
        "",
        "## Что по замыслу выдаёт «нет данных», пока не набрана статистика",
        "",
        "- веса жюри и голоса меток — n_min (20) на класс; паспорт ОКО — mature_n (30) на символ;",
        "- прогноз/память ОКО — n_min окон в классе; калибровка классов — mature_n бумажных сделок;",
        "- веса авторов — ≥5 разрешённых вызовов; месячный сентимент — ≥20 дневных отпечатков.",
        "Это не заглушки: функции работают и показывают, сколько набрано из скольких.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate STATUS from facts.")
    parser.add_argument("--userdir", default=None)
    parser.add_argument("--out", default="ops/STATUS-GENERATED.md")
    args = parser.parse_args(argv)
    text = render(userdir=Path(args.userdir) if args.userdir else None)
    out = Path(args.out)
    out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
