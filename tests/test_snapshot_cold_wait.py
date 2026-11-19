"""Snapshot Statistics dingin tidak boleh membuat request menggantung (19 Nov 2026).

``/stats/ai_status_timeseries`` memberi tiap kombinasi (granularity/tanggal/campaign)
``scope_key`` sendiri. Kombinasi yang belum pernah dihitung dikerjakan SINKRON di
dalam request, dan butuh 24-40 dtk — melewati timeout axios 30 dtk di dashboard.

Dengan ``cold_wait_sec`` hitungan dingin dijalankan di latar belakang; request
menunggu paling lama itu, lalu mengembalikan hasilnya bila sudah jadi, atau
``SnapshotPending`` (router menjawab HTTP 202) bila belum — tidak pernah menggantung.
Tanpa ``cold_wait_sec`` perilakunya persis seperti sebelumnya.
"""
import pytest

from qc_core.db import crud


class _Row:
    def __init__(self, payload):
        self.payload = payload


class _Query:
    def __init__(self, row):
        self._row = row

    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def first(self):
        return self._row


class _Db:
    """Sesi palsu: ``query(...).filter().order_by().first()`` -> baris snapshot / None."""

    def __init__(self, row=None):
        self._row = row
        self.closed = False

    def query(self, *a, **k):
        return _Query(self._row)

    def close(self):
        self.closed = True


SIG = "v33|abc"


@pytest.fixture(autouse=True)
def _stub(monkeypatch):
    monkeypatch.setattr(crud, "_stats_signature", lambda db: SIG)


@pytest.fixture
def calls(monkeypatch):
    log = {"started": [], "computed": 0, "stored": 0}
    monkeypatch.setattr(
        crud, "_start_snapshot_refresh",
        lambda sf, scope, fn, sig: log["started"].append((scope, sig)),
    )

    def _compute(db, fn):
        log["computed"] += 1
        return {"ok": True}

    monkeypatch.setattr(crud, "_compute_stats_payload", _compute)
    monkeypatch.setattr(
        crud, "_store_stats_snapshot",
        lambda db, scope, payload: (log.__setitem__("stored", log["stored"] + 1), payload)[1],
    )
    return log


# --------------------------------------------------------------------------
# _await_snapshot
# --------------------------------------------------------------------------

def test_await_returns_the_snapshot_as_soon_as_it_appears(monkeypatch):
    rows = iter([None, None, _Row({"_signature": SIG, "n": 1})])
    sessions = []

    def _factory():
        db = _Db(next(rows))
        sessions.append(db)
        return db

    monkeypatch.setattr(crud.time, "sleep", lambda s: None)
    out = crud._await_snapshot(_factory, "ts:x", SIG, wait_sec=30, poll_sec=0.5)

    assert out == {"_signature": SIG, "n": 1}
    assert len(sessions) == 3 and all(s.closed for s in sessions), "tiap polling menutup sesinya"


def test_await_gives_up_after_the_deadline_and_returns_none(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(crud.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(crud.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))

    out = crud._await_snapshot(lambda: _Db(None), "ts:x", SIG, wait_sec=2, poll_sec=0.5)

    assert out is None
    assert clock["t"] >= 2


def test_await_ignores_a_snapshot_with_a_different_signature(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(crud.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(crud.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))
    stale = _Row({"_signature": "v33|OLD"})

    assert crud._await_snapshot(lambda: _Db(stale), "ts:x", SIG, wait_sec=1, poll_sec=0.5) is None


# --------------------------------------------------------------------------
# get_or_build_stats_snapshot
# --------------------------------------------------------------------------

def test_cold_key_without_cold_wait_still_computes_synchronously(calls):
    out = crud.get_or_build_stats_snapshot(
        _Db(None), scope_key="ts:x", compute_fn=lambda s: {}, session_factory=lambda: _Db())
    assert out["ok"] is True
    assert calls["computed"] == 1 and calls["started"] == []


def test_cold_key_with_cold_wait_computes_in_background_and_returns_when_ready(monkeypatch, calls):
    monkeypatch.setattr(crud, "_await_snapshot", lambda sf, scope, sig, wait_sec, poll_sec=0.5: {"ready": 1})
    out = crud.get_or_build_stats_snapshot(
        _Db(None), scope_key="ts:x", compute_fn=lambda s: {},
        session_factory=lambda: _Db(), cold_wait_sec=20)
    assert out == {"ready": 1}
    assert calls["started"] == [("ts:x", SIG)]
    assert calls["computed"] == 0, "request tidak boleh menghitung sendiri"


def test_cold_key_not_ready_in_time_raises_pending_instead_of_hanging(monkeypatch, calls):
    monkeypatch.setattr(crud, "_await_snapshot", lambda *a, **k: None)
    with pytest.raises(crud.SnapshotPending):
        crud.get_or_build_stats_snapshot(
            _Db(None), scope_key="ts:x", compute_fn=lambda s: {},
            session_factory=lambda: _Db(), cold_wait_sec=20)
    assert calls["started"] == [("ts:x", SIG)]
    assert calls["computed"] == 0


def test_fresh_snapshot_is_returned_without_any_background_work(calls):
    fresh = _Row({"_signature": SIG, "cached": True})
    out = crud.get_or_build_stats_snapshot(
        _Db(fresh), scope_key="ts:x", compute_fn=lambda s: {},
        session_factory=lambda: _Db(), cold_wait_sec=20)
    assert out["cached"] is True
    assert calls["started"] == [] and calls["computed"] == 0


def test_force_ignores_cold_wait_and_computes_inline(calls):
    out = crud.get_or_build_stats_snapshot(
        _Db(None), force=True, scope_key="ts:x", compute_fn=lambda s: {},
        session_factory=lambda: _Db(), cold_wait_sec=20)
    assert out["ok"] is True
    assert calls["computed"] == 1 and calls["started"] == []
