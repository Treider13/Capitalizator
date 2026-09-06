"""Integration regressions for the confirmed audit fixes.

Uses actual Runtime, Executor and pinned pybit with a controlled HTTP transport.
Assertions require corrected behaviour and preserve valid/ambiguous controls.
"""

import json
import threading
import time

import pytest
import requests
from tests.fusion import test_confirmed_audit_fixes as a
from tests.fusion.daily_fixtures import seed_daily
from tests.fusion.test_cross_market import frame

from capitalizator.fusion.structure import parse_history


@pytest.fixture
def store(tmp_path):
    s = a.Store(tmp_path / "fusion.sqlite3")
    yield s
    s.close()


def adapter(monkeypatch, code):
    api = a.Bybit("demo", ("audit-placeholder", "audit-placeholder"), a.CFG)
    calls = []

    def send(request, **kwargs):
        calls.append(request)
        response = requests.Response()
        response.status_code = 200
        response.url = request.url
        response._content = json.dumps(
            {"retCode": code, "retMsg": "controlled response", "result": {}}
        ).encode()
        return response

    monkeypatch.setattr(api.http.client, "send", send)
    monkeypatch.setattr("pybit._http_manager.time.sleep", lambda _: None)
    return api, calls


@pytest.mark.parametrize(
    "code,exception", [(10006, a.VenueError), (10002, a.VenueError), (10001, a.VenueError)]
)
def test_sdk_actual_error_mapping(monkeypatch, code, exception):
    api, calls = adapter(monkeypatch, code)
    with pytest.raises(exception) as err:
        api.close_position(a.position(), "audit-close")
    assert type(err.value) is exception
    assert len(calls) == 1
    if exception is a.VenueError:
        assert err.value.code == code
    else:
        assert "FailedRequestError" in str(err.value)


@pytest.mark.parametrize("code", [10001, 10006])
def test_close_rejection_retries_only_when_definitive_and_allowed(store, monkeypatch, code):
    api, calls = adapter(monkeypatch, code)
    venue = a.Venue()
    venue.positions = [a.position()]
    venue.close_position = api.close_position
    executor = a.Executor(store, venue, a.CFG)
    store.command("operator-close", "demo", "BTCUSDT", "flatten", 102, {})
    with pytest.raises(RuntimeError):
        executor.tick(102, False)
    assert len(calls) == 1

    # Endpoint recovered; any new request would now succeed.
    def recovered(request, **kwargs):
        calls.append(request)
        response = requests.Response()
        response.status_code = 200
        response.url = request.url
        response._content = b'{"retCode": 0, "retMsg": "OK", "result": {"orderId": "recovered"}}'
        return response

    monkeypatch.setattr(api.http.client, "send", recovered)
    for at in (108, 114, 120, 126):
        executor.tick(at, False)
    command = store.rows("SELECT * FROM commands WHERE id='operator-close'")[0]
    assert command["state"] == ("pending" if code == 10006 else "failed")
    assert json.loads(command["body"])["close_attempted"] is (code == 10006)
    assert len(calls) == (2 if code == 10006 else 1)
    if code == 10001:
        store.command("operator-retry", "demo", "BTCUSDT", "flatten", 127, {"reason": "operator"})
        executor.tick(127, False)
        assert len(calls) == 2
    # An empty lookup after the accepted retry must not send again.
    executor.tick(133, False)
    assert len(calls) == 2


def ready_runtime(tmp_path, monkeypatch, now=103):
    runtime = a.Runtime(tmp_path, a.CFG)
    runtime.shared.broker_ready = True
    runtime.shared.news_required = False
    runtime.shared.paused = False
    market = runtime.engines["BTCUSDT"].market
    book = {**frame(at=now), "_received_monotonic": time.monotonic()}
    market.ingest("book", book, now)
    market.ingest("ticker", {"data": {}}, now)
    market.ingest("spot_book", book, now)
    seed_daily(market, at=now)
    runtime.spot_generations["BTCUSDT"] = 1
    runtime.shared.snapshots["BTCUSDT"] = market.snapshot()
    monkeypatch.setattr("capitalizator.fusion.runtime.time.time", lambda: now)
    return runtime


def test_F06_actual_runtime_authorization_revoked_during_leverage(tmp_path, monkeypatch):
    runtime = ready_runtime(tmp_path, monkeypatch)
    try:
        a.seed_order(runtime.store)
        api, calls = adapter(monkeypatch, 0)
        venue = a.Venue()
        venue.place = api.place
        if hasattr(api, "prepare_entry"):
            venue.prepare_entry = api.prepare_entry
        executor = a.Executor(
            runtime.store,
            venue,
            a.CFG,
            entry_lock=runtime.shared.entry_lock,
            authorize=runtime._authorize_send,
        )
        runtime.executor = executor
        executor.last_reconcile = 103
        order = runtime.store.rows("SELECT * FROM orders")[0]
        assert runtime._authorize_send(order)
        original = api.http.client.send

        def revoke(request, **kwargs):
            response = original(request, **kwargs)
            if request.url.endswith("/position/set-leverage"):
                runtime.shared.halt("public_socket_disconnected")
                assert not runtime._authorize_send(order)
            return response

        monkeypatch.setattr(api.http.client, "send", revoke)
        executor.tick(103, True)
        assert [r.url.rsplit("/", 1)[-1] for r in calls] == ["set-leverage"]
        assert not runtime._authorize_send(order)
    finally:
        runtime.close()


def test_partial_cancel_blocks_second_dispatch_with_real_authorization(tmp_path, monkeypatch):
    runtime = ready_runtime(tmp_path, monkeypatch)
    try:
        payload = a.seed_order(runtime.store)
        venue = a.Venue()
        executor = a.Executor(
            runtime.store,
            venue,
            a.CFG,
            entry_lock=runtime.shared.entry_lock,
            authorize=runtime._authorize_send,
        )
        runtime.executor = executor
        executor.last_reconcile = 101
        executor.set_state(payload["orderLinkId"], "partial", 102)
        executor.private(
            {
                "topic": "order",
                "data": [
                    {
                        "category": "linear",
                        "orderLinkId": payload["orderLinkId"],
                        "orderStatus": "Cancelled",
                        "cumExecQty": "1",
                        "updatedTime": "103000",
                    }
                ],
            },
            103,
        )
        second, reason = a.reserve(
            runtime.store,
            "demo",
            a.register(runtime.store, "second"),
            a.INST,
            a.CFG,
            103,
            100,
            10000,
            0.02,
            0,
        )
        assert second is None, reason
        executor.tick(103, True)
        assert venue.sent == []
        # Control: receiving the missing position prevents a third reserve.
        executor.private({"topic": "position", "data": [a.position(updatedTime="103000")]}, 103)
        third, _ = a.reserve(
            runtime.store,
            "demo",
            a.register(runtime.store, "third"),
            a.INST,
            a.CFG,
            103,
            100,
            10000,
            0.02,
            0,
        )
        assert third is None
    finally:
        runtime.close()


def test_close_is_not_blocked_by_history_outage_or_duplicated_on_recovery(store):
    venue = a.Venue()
    venue.positions = [a.position()]
    executor = a.Executor(store, venue, a.CFG)
    store.command("close", "demo", "BTCUSDT", "flatten", 102, {})

    def down(*args):
        raise RuntimeError("execution endpoint only is down")

    venue.executions = down
    for at in (102, 108, 114):
        with pytest.raises(RuntimeError):
            executor.tick(at, False)
    assert venue.closes == ["acx-close"]
    venue.executions = lambda *args: []
    executor.tick(120, False)
    assert venue.closes == ["acx-close"]


@pytest.mark.parametrize("mode", ["demo", "live"])
@pytest.mark.parametrize("category,closed", [("linear", 1), ("spot", 0)])
def test_F01_category_collision_with_linear_control(store, mode, category, closed):
    payload = a.seed_order(store)
    with store.transaction() as db:
        db.execute("UPDATE orders SET mode=?", (mode,))
    venue = a.Venue()
    venue.mode = mode
    executor = a.Executor(store, venue, a.CFG)
    fill = {
        "category": "linear",
        "execId": "open",
        "orderLinkId": payload["orderLinkId"],
        "symbol": "BTCUSDT",
        "execTime": "102000",
        "execQty": "1",
        "execPrice": "100",
        "execFee": "0",
        "side": "Buy",
        "execType": "Trade",
        "closedSize": "0",
    }
    executor.private({"topic": "execution", "data": [fill]}, 102)
    assert a.venue_performance(store, mode, policy=a.CFG.version)["closed_episodes"] == 0
    sale = {
        **fill,
        "category": category,
        "execId": "sell",
        "orderLinkId": "manual",
        "execTime": "103000",
        "execPrice": "120",
        "side": "Sell",
    }
    executor.private({"topic": "execution", "data": [sale]}, 103)
    report = a.venue_performance(store, mode, policy=a.CFG.version)
    assert report["closed_episodes"] == closed
    assert report["realized_net"] == (20 if category == "linear" else 0)
    assert report["incomplete_inventory"] is False


def test_F09_explicit_flat_row_fences_old_position_but_omission_does_not(store):
    venue = a.Venue()
    executor = a.Executor(store, venue, a.CFG)
    old = a.position(updatedTime="100000")
    executor.private({"topic": "position", "data": [old]}, 101)
    venue.positions = [{**old, "size": "0", "updatedTime": "110000"}]
    executor.reconcile(110)
    executor.private({"topic": "position", "data": [{**old, "updatedTime": "105000"}]}, 111)
    assert executor.positions == []


def test_F07_visible_position_rejects_credentials_control(tmp_path):
    runtime = a.Runtime(tmp_path, a.CFG)
    try:
        runtime.shared.paused = True
        runtime.store.account("demo", time.time(), 10000, [a.position()], [], "1970-01-01")
        with pytest.raises(ValueError, match="flat"):
            runtime.control("credentials", {"mode": "demo", "key": "fake", "secret": "fake"})
        assert not (tmp_path / "secrets/demo.json").exists()
    finally:
        runtime.close()


@pytest.mark.parametrize("prefix,admitted", [("manual-foreign", False), ("acr-foreign", False)])
def test_F08_prefix_alone_changes_unknown_order_admission(store, prefix, admitted):
    store.account(
        "demo",
        101,
        10000,
        [],
        [
            {
                "symbol": "BTCUSDT",
                "orderLinkId": prefix,
                "side": "Buy",
                "qty": "100",
                "price": "100",
                "reduceOnly": False,
            }
        ],
        "1970-01-01",
    )
    result, _ = a.reserve(store, "demo", a.register(store), a.INST, a.CFG, 101, 100, 10000, 0.02, 0)
    assert (result is not None) is admitted


def test_F10_boundary_filter_control():
    partial = [["60000", "100", "102", "99", "101", "50"]]
    assert parse_history("BTCUSDT", "1m", partial, 119.9) == []
    assert len(parse_history("BTCUSDT", "1m", partial, 120.1)) == 1


def test_history_worker_preserves_source_time_across_candle_boundary(tmp_path, monkeypatch):
    import capitalizator.fusion.runtime as runtime_module

    runtime = a.Runtime(tmp_path, a.replace(a.CFG, symbols=("BTCUSDT",)))
    sampled, release = threading.Event(), threading.Event()
    receipt = [119.9]
    failures = []
    monkeypatch.setattr(runtime_module, "TFS", ("1m",))
    monkeypatch.setattr(runtime_module.time, "time", lambda: receipt[0])
    partial = [["60000", "100", "102", "99", "101", "50"]]

    def response(*args, **kwargs):
        sampled.set()
        assert release.wait(5)
        return json.dumps({"retCode": 0, "time": 119900, "result": {"list": partial}}).encode()

    monkeypatch.setattr("capitalizator.fusion.external.read_url", response)
    original_put = runtime.mailboxes[0].put

    def put(key, item):
        result = original_put(key, item)
        runtime.supervisor.stop.set()
        return result

    monkeypatch.setattr(runtime.mailboxes[0], "put", put)

    def worker():
        try:
            runtime._history()
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    try:
        assert sampled.wait(5)
        engine = runtime.engines["BTCUSDT"]
        engine.process(
            "history", {"tf": "1m", "rows": [["60000", "100", "110", "90", "105", "1000"]]}, 120.05
        )
        assert engine.market.structure.cache["1m"]["candles"][-1]["high"] == 110
        receipt[0] = 120.1
        release.set()
        thread.join(5)
        assert not thread.is_alive() and not failures
        symbol, kind, payload, at, epoch = runtime.mailboxes[0].get()[0]
        assert at == 120.1
        engine.process(kind, payload, at)
        bar = engine.market.structure.cache["1m"]["candles"][-1]
        assert bar["high"] == 110 and bar["volume"] == 1000
        assert payload["known_at"] == 119.9
    finally:
        release.set()
        runtime.supervisor.stop.set()
        thread.join(5)
        runtime.close()


def test_live_and_replay_recover_from_the_same_invalid_frame(tmp_path):
    cfg = a.replace(a.CFG, symbols=("BTCUSDT",), workers=1)
    runtime = a.Runtime(tmp_path, cfg)
    now = time.time()
    bad = {
        "topic": "orderbook.50.BTCUSDT",
        "type": "snapshot",
        "ts": now * 1000,
        "data": {"u": 1, "b": [["100", "-1"]], "a": [["101", "2"]]},
    }
    good = {**bad, "data": {"u": 2, "b": [["100", "2"]], "a": [["100.01", "1"]]}}
    runtime.callback(bad, 0)
    runtime.callback(good, 0)
    original_beat = runtime.supervisor.beat

    def beat(name):
        original_beat(name)
        if runtime.engines["BTCUSDT"].market.valid:
            runtime.supervisor.stop.set()

    runtime.supervisor.beat = beat
    thread = threading.Thread(target=lambda: runtime._market_worker(0))
    thread.start()
    try:
        thread.join(5)
        assert not thread.is_alive()
        assert runtime.engines["BTCUSDT"].market.valid
        assert "invalid_market_frame" in runtime.shared.halts
        journal = runtime.store.rows("SELECT * FROM events ORDER BY id")
        assert len(journal) >= 4
        a.compare(runtime.store, tmp_path, tmp_path / "replay", cfg, {"BTCUSDT": a.INST})
    finally:
        runtime.supervisor.stop.set()
        thread.join(5)
        runtime.close()


def test_old_frame_cannot_acknowledge_real_maintenance_generation(tmp_path):
    cfg = a.replace(a.CFG, symbols=("BTCUSDT",), workers=1)
    runtime = a.Runtime(tmp_path, cfg)
    entered, release, opened, completed = (threading.Event() for _ in range(4))
    runtime.public_ws = a.SimpleNamespace(
        is_connected=lambda: False, started_at=0, exit=lambda: None
    )
    runtime._open_public = lambda: opened.set()
    original = runtime.engines["BTCUSDT"].process

    def process(kind, frame, at):
        original(kind, frame, at)
        if kind == "book":
            entered.set()
            assert release.wait(5)

    runtime.engines["BTCUSDT"].process = process
    original_beat = runtime.supervisor.beat

    def beat(name):
        original_beat(name)
        if name == "market-0":
            completed.set()

    runtime.supervisor.beat = beat
    now = time.time()
    runtime.callback(frame(at=now), 0)
    actor = threading.Thread(target=lambda: runtime._market_worker(0))
    maintenance = threading.Thread(target=runtime._maintenance)
    actor.start()
    try:
        assert entered.wait(5)
        maintenance.start()
        assert opened.wait(5)
        assert runtime.epoch == 1 and runtime.recovering == {"BTCUSDT"}
        assert "recovering_feed" in runtime.shared.halts
        release.set()
        assert completed.wait(5)
        assert runtime.recovering == {"BTCUSDT"}
        assert "recovering_feed" in runtime.shared.halts
        # No frame from epoch 1 was ever enqueued.
        assert runtime.mailboxes[0].status()["pending"] == 0
    finally:
        release.set()
        runtime.supervisor.stop.set()
        actor.join(5)
        if maintenance.ident is not None:
            maintenance.join(5)
        runtime.close()


def test_partial_fill_reservation_survives_cancel_and_executor_restart(store):
    payload = a.seed_order(store)
    venue = a.Venue()
    executor = a.Executor(store, venue, a.CFG)
    ident = payload["orderLinkId"]
    executor.private(
        {
            "topic": "order",
            "data": [{"orderLinkId": ident, "orderStatus": "PartiallyFilled", "cumExecQty": "1"}],
        },
        102,
    )
    executor._cancel(store.rows("SELECT * FROM orders")[0], 103)
    assert store.rows("SELECT state FROM orders")[0]["state"] == "cancelling"
    executor = a.Executor(store, venue, a.CFG)
    # Even without a cumulative quantity in a later notification, the prior
    # execution evidence survives the cancellation state and process restart.
    executor.private(
        {"topic": "order", "data": [{"orderLinkId": ident, "orderStatus": "Cancelled"}]}, 104
    )
    assert store.rows("SELECT state FROM orders")[0]["state"] == "filled"
    second, _ = a.reserve(
        store, "demo", a.register(store, "second"), a.INST, a.CFG, 104, 100, 10000, 0.02, 0
    )
    assert second is None
    venue.orders[ident] = {"orderStatus": "Cancelled", "cumExecQty": "1"}
    executor.reconcile(105)
    assert store.rows("SELECT state FROM orders")[0]["state"] == "filled"
    executor.reconcile(110)
    assert store.rows("SELECT state FROM orders")[0]["state"] == "closed"


def test_position_fence_requires_rest_and_accepts_real_new_fill(store):
    venue = a.Venue()
    executor = a.Executor(store, venue, a.CFG)
    executor.reconcile(101)
    new = a.position(updatedTime="102000")
    executor.private({"topic": "position", "data": [new]}, 102)
    assert executor.positions == []
    assert executor.last_reconcile == 0
    assert store.rows("SELECT at FROM account")[0]["at"] == 0
    venue.positions = [new]
    executor.reconcile(102)
    assert executor.positions == [new]
    assert store.rows("SELECT at FROM account")[0]["at"] == 102
    executor.private(
        {"topic": "position", "data": [{**new, "size": "2", "updatedTime": "103000"}]}, 103
    )
    assert executor.positions[0]["size"] == "2"


def test_ambiguous_close_stays_single_attempt_across_restart(store):
    venue = a.Venue()
    venue.positions = [a.position()]
    attempts = []

    def timeout(pos, ident):
        attempts.append(ident)
        raise TimeoutError("ambiguous")

    venue.close_position = timeout
    executor = a.Executor(store, venue, a.CFG)
    store.command("close", "demo", "BTCUSDT", "flatten", 102, {})
    with pytest.raises(TimeoutError):
        executor.tick(102, False)
    executor = a.Executor(store, venue, a.CFG)
    store.command("operator-retry", "demo", "BTCUSDT", "flatten", 108, {"reason": "operator"})
    executor.tick(108, False)
    assert attempts == ["acx-close"]


@pytest.mark.parametrize("pending", [False, True])
def test_credential_change_rejects_fresh_venue_orders_and_pending_commands(tmp_path, pending):
    runtime = a.Runtime(tmp_path, a.CFG)
    try:
        runtime.shared.paused = True
        orders = [] if pending else [{"orderLinkId": "manual", "symbol": "BTCUSDT"}]
        runtime.store.account("demo", time.time(), 10000, [], orders, "1970-01-01")
        if pending:
            runtime.store.command("close", "demo", "BTCUSDT", "flatten", time.time(), {})
        with pytest.raises(ValueError, match="flat"):
            runtime.control("credentials", {"mode": "demo", "key": "fake", "secret": "fake"})
        assert not (tmp_path / "secrets/demo.json").exists()
    finally:
        runtime.close()


def test_old_spot_rows_and_old_performance_cache_do_not_pollute_linear_report(store):
    payload = a.seed_order(store)
    fill = {
        "category": "linear",
        "execId": "open",
        "orderLinkId": payload["orderLinkId"],
        "symbol": "BTCUSDT",
        "execTime": "102000",
        "execQty": "1",
        "execPrice": "100",
        "execFee": "0",
        "side": "Buy",
        "execType": "Trade",
    }
    store.execution("demo", fill)
    spot = {**fill, "category": "spot", "execId": "old-spot", "execPrice": "120", "side": "Sell"}
    with store.transaction() as db:
        db.execute(
            "INSERT INTO executions VALUES(?,?,?,?,?,?)",
            ("demo", "old-spot", "manual", "BTCUSDT", 103, a.encode(spot)),
        )
    store.put_meta(
        "performance:demo:policy:" + a.CFG.version,
        {
            "revision": store.meta("execution_revision:demo"),
            "report": {"realized_net": 20, "closed_episodes": 1},
        },
    )
    report = a.venue_performance(store, "demo", policy=a.CFG.version)
    assert report["closed_episodes"] == 0 and report["realized_net"] == 0
    assert report["ignored_executions"] == 1


def test_spot_order_cannot_change_linear_order_with_same_link_id(store):
    payload = a.seed_order(store)
    executor = a.Executor(store, a.Venue(), a.CFG)
    executor.private(
        {
            "topic": "order",
            "data": [
                {
                    "category": "spot",
                    "orderLinkId": payload["orderLinkId"],
                    "orderStatus": "Cancelled",
                }
            ],
        },
        102,
    )
    assert store.rows("SELECT state FROM orders")[0]["state"] == "pending"


def test_replay_spot_recovery_preserves_linear_book(store, tmp_path):
    cfg = a.replace(a.CFG, symbols=("BTCUSDT",))
    store.event(101, "BTCUSDT", "book", frame())
    bad = frame()
    bad["data"]["b"][0][1] = "-1"
    store.event(101, "BTCUSDT", "spot_book", bad)
    store.event(101, "BTCUSDT", "spot_status", {"generation": 1, "status": "invalid_frame"})
    store.event(102, "BTCUSDT", "spot_book", frame(at=102))
    output = tmp_path / "replay"
    a.compare(store, tmp_path, output, cfg, {"BTCUSDT": a.INST})
    replay_store = a.Store(output / "D.sqlite3")
    try:
        assert replay_store.rows("SELECT * FROM events WHERE kind='spot_status'")
        assert not replay_store.rows(
            "SELECT * FROM events WHERE kind='gap' AND json_extract(body,'$.reason')='ValueError'"
        )
    finally:
        replay_store.close()


def test_mixed_legacy_demo_qualification_is_revoked_once(tmp_path):
    path = tmp_path / "fusion.sqlite3"
    store = a.Store(path)
    with store.transaction() as db:
        db.execute("DELETE FROM meta WHERE key='linear_ledger_v2'")
        db.execute(
            "INSERT INTO executions VALUES(?,?,?,?,?,?)",
            ("demo", "old", "manual", "BTCUSDT", 100, a.encode({"category": "spot"})),
        )
    store.put_meta("live_qualified_policy", a.CFG.version)
    store.put_meta("mode", "live")
    store.put_meta("policy_epoch", {"version": a.CFG.version, "since": 99})
    store.close()
    runtime = a.Runtime(tmp_path, a.CFG)
    try:
        assert not runtime.live_qualified
        assert runtime.shared.paused
        # A subsequent valid qualification must survive another restart.
        runtime.store.put_meta("live_qualified_policy", a.CFG.version)
    finally:
        runtime.close()
    runtime = a.Runtime(tmp_path, a.CFG)
    try:
        assert runtime.live_qualified
    finally:
        runtime.close()


def test_failed_close_blocks_entries_until_explicit_retry_or_observed_flat(store):
    venue = a.Venue()
    venue.positions = [a.position()]

    def reject(pos, ident):
        raise a.VenueError(10001)

    venue.close_position = reject
    executor = a.Executor(store, venue, a.CFG)
    store.command("close", "demo", "BTCUSDT", "flatten", 102, {})
    with pytest.raises(a.VenueError):
        executor.tick(102, False)
    assert store.rows("SELECT state FROM commands")[0]["state"] == "failed"
    # An automated trigger does not restart a permanently rejected request.
    store.command("news", "demo", "BTCUSDT", "flatten", 108, {"reason": "news"})
    assert len(store.rows("SELECT * FROM commands")) == 1
    venue.positions = []  # Position closed independently on the venue.
    executor.reconcile(110)
    assert store.rows("SELECT state FROM commands")[0]["state"] == "done"


def test_history_outage_still_cancels_open_entry(store):
    payload = a.seed_order(store)
    venue = a.Venue()
    executor = a.Executor(store, venue, a.CFG)
    executor.tick(102, True)
    ident = payload["orderLinkId"]
    assert store.rows("SELECT state FROM orders")[0]["state"] == "accepted"
    venue.orders[ident] = {"orderStatus": "New", "orderLinkId": ident}
    cancelled = []
    venue.cancel = lambda symbol, link: cancelled.append(link)

    def unavailable(*args):
        raise TimeoutError("history unavailable")

    venue.executions = unavailable
    with pytest.raises(RuntimeError, match="execution history"):
        executor.tick(110, True)
    assert cancelled == [ident]
    assert store.rows("SELECT state FROM orders")[0]["state"] == "cancelling"
    assert len(venue.sent) == 1


def test_replay_news_respects_invalid_market_halt(store, tmp_path, monkeypatch):
    from capitalizator.fusion.executor import Executor

    cfg = a.replace(a.CFG, symbols=("BTCUSDT",))
    bad = frame()
    bad["data"]["b"][0][1] = "-1"
    store.event(101, "BTCUSDT", "book", bad)
    store.event(102, "*", "news", [])
    observed = []
    original = Executor.tick

    def tick(self, at, allow_entries):
        observed.append((at, allow_entries))
        return original(self, at, allow_entries)

    monkeypatch.setattr(Executor, "tick", tick)
    a.compare(store, tmp_path, tmp_path / "replay", cfg, {"BTCUSDT": a.INST})
    news_ticks = [allowed for at, allowed in observed if at == 102]
    assert news_ticks and not any(news_ticks)


@pytest.mark.parametrize("cancel_error", [TimeoutError, ValueError])
def test_cancel_failure_does_not_prevent_closing_filled_exposure(store, cancel_error):
    payload = a.seed_order(store)
    venue = a.Venue()
    venue.positions = [a.position()]
    venue.orders[payload["orderLinkId"]] = {"orderStatus": "PartiallyFilled", "cumExecQty": "1"}
    executor = a.Executor(store, venue, a.CFG)
    executor.set_state(payload["orderLinkId"], "partial", 102)

    def fail_cancel(*args):
        raise cancel_error("cancel endpoint unavailable")

    venue.cancel = fail_cancel
    store.command("operator-close", "demo", "BTCUSDT", "flatten", 103, {"reason": "operator"})
    with pytest.raises(cancel_error):
        executor.tick(103, False)
    assert venue.closes == ["acx-operator-close"]
    assert store.rows("SELECT state FROM commands WHERE id='operator-close'")[0]["state"] == "pending"
    # Restart and another cancellation failure must not duplicate an ambiguous close.
    executor = a.Executor(store, venue, a.CFG)
    with pytest.raises(cancel_error):
        executor.tick(110, False)
    assert venue.closes == ["acx-operator-close"]


@pytest.mark.parametrize("generation", ["missing", "bad", None, "inf"])
@pytest.mark.parametrize("kind", ["spot_book", "spot_status"])
@pytest.mark.parametrize("initial", [False, True])
def test_replay_recovers_invalid_spot_generation(store, tmp_path, generation, kind, initial):
    cfg = a.replace(a.CFG, symbols=("BTCUSDT",))
    store.event(100, "BTCUSDT", "book", frame(at=100))
    if initial:
        store.event(100, "BTCUSDT", "spot_book", frame(at=100, generation=7))
    bad = frame(at=101)
    if generation == "missing":
        del bad["generation"]
    else:
        bad["generation"] = generation
    store.event(101, "BTCUSDT", kind, bad)
    store.event(102, "BTCUSDT", "spot_book", frame(at=102, generation=8))
    output = tmp_path / "replay"
    a.compare(store, tmp_path, output, cfg, {"BTCUSDT": a.INST})
    for variant in ("A", "B", "C", "D"):
        result = a.Store(output / f"{variant}.sqlite3")
        try:
            faults = result.rows(
                "SELECT body FROM events WHERE kind='spot_status' "
                "AND json_extract(body,'$.status')='invalid_frame'"
            )
            assert len(faults) == 1
            assert json.loads(faults[0]["body"])["generation"] == (7 if initial else -1)
            assert result.rows("SELECT id FROM events WHERE kind='spot_book' AND received=102")
            assert not result.rows("SELECT id FROM events WHERE kind='gap' AND received>=101")
        finally:
            result.close()


@pytest.mark.parametrize("failed_side", ["venue", "engine"])
def test_spot_recovery_keeps_new_valid_generation_and_both_books_consistent(store, failed_side):
    from capitalizator.fusion.engine import Engine, Shared
    from capitalizator.fusion.replay import ReplayVenue, _recover_spot

    cfg = a.replace(a.CFG, symbols=("BTCUSDT",))
    venue = ReplayVenue({"BTCUSDT": a.INST}, cfg)
    engine = Engine("BTCUSDT", store, Shared(), cfg)
    markets = (venue.markets["BTCUSDT"], engine.market)
    for market in markets:
        market.ingest("book", frame(), 101)
        market.ingest("spot_book", frame(generation=7), 101)
    bad = frame(generation=8, qty=-1)
    failed = markets[0 if failed_side == "venue" else 1]
    with pytest.raises(ValueError):
        failed.ingest("spot_book", bad, 102)
    _recover_spot(venue, engine, "BTCUSDT", 102)
    for market in markets:
        assert market.valid
        assert market.spot.generation == 8
        assert market.spot.status == "invalid_frame"
        assert not market.spot.bids and not market.spot.asks
        market.ingest("spot_book", frame(at=103, generation=8), 103)
        assert market.spot.status == "streaming"
