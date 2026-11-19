"""Unit tests for crud.cashline_agent_index — the cid -> agent_id/submit_time map.

Regression guard for the bug where these lookups read the local ``tms_cashline``
table. That table stopped being filled when reference data moved to the DWH API,
so every lookup returned nothing: the Statistics hierarchy collapsed into a single
"(Tidak diketahui)" node and Team Leaders saw zero tickets.

The fast path must stay SQL-only (the snapshot already stored in
``result_data.result_json``); the DWH API is a fallback for rows evaluated before
App A started caching ``agent_id``/``submit_time``.
"""
import pytest

from qc_core.db import crud


# --------------------------------------------------------------------------
# Fake SQLAlchemy query chain — returns canned (cid, agent_id, submit_time) rows
# --------------------------------------------------------------------------

class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def join(self, *a, **k):
        return self

    def distinct(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def all(self):
        return self._rows


class _FakeDb:
    def __init__(self, rows):
        self._rows = rows

    def query(self, *a, **k):
        return _FakeQuery(self._rows)


@pytest.fixture(autouse=True)
def _clear_memo():
    """The DWH fallback memo is module-level; isolate it between tests."""
    crud._CASHLINE_ID_MEMO.clear()
    yield
    crud._CASHLINE_ID_MEMO.clear()


@pytest.fixture
def no_dwh(monkeypatch):
    """Fail the test if the fallback fires — the fast path must not touch DWH."""
    def _boom(cids):
        raise AssertionError(f"DWH fallback should not run, got {cids}")

    monkeypatch.setattr(crud, "_cashline_ids_from_dwh", _boom)


# --------------------------------------------------------------------------
# Fast path — everything resolved straight from the stored snapshot
# --------------------------------------------------------------------------

def test_reads_agent_and_submit_time_from_stored_snapshot(no_dwh):
    db = _FakeDb([
        ("010923HWcN", "chreste801", "2026-07-27 16:02:21"),
        ("271136Z1mY", "sartika801", "2026-07-27 11:52:32"),
    ])
    assert crud.cashline_agent_index(db) == {
        "010923HWcN": {"agent_id": "chreste801", "submit_time": "2026-07-27 16:02:21"},
        "271136Z1mY": {"agent_id": "sartika801", "submit_time": "2026-07-27 11:52:32"},
    }


def test_trims_and_normalises_blank_values(no_dwh):
    db = _FakeDb([("  010923HWcN  ", "  chreste801  ", "   ")])
    assert crud.cashline_agent_index(db) == {
        "010923HWcN": {"agent_id": "chreste801", "submit_time": None},
    }


def test_skips_rows_without_a_customer_id(no_dwh):
    db = _FakeDb([("", "chreste801", "2026-07-27 16:02:21"), (None, "x801", "2026-01-01 00:00:00")])
    assert crud.cashline_agent_index(db) == {}


# --------------------------------------------------------------------------
# Fallback — only for rows whose snapshot predates the agent_id/submit_time fix
# --------------------------------------------------------------------------

def test_fallback_runs_only_for_rows_missing_agent_id(monkeypatch):
    asked = []

    def _fake(cids):
        asked.append(sorted(cids))
        return {c: {"agent_id": "recovered801", "submit_time": "2026-06-01 09:00:00"} for c in cids}

    monkeypatch.setattr(crud, "_cashline_ids_from_dwh", _fake)
    db = _FakeDb([
        ("hasAgent", "chreste801", "2026-07-27 16:02:21"),
        ("noAgent", None, None),
    ])
    index = crud.cashline_agent_index(db)

    assert asked == [["noAgent"]], "only the row missing agent_id should hit DWH"
    assert index["hasAgent"]["agent_id"] == "chreste801"
    assert index["noAgent"]["agent_id"] == "recovered801"


def test_dwh_only_fills_gaps_never_erases_snapshot_submit_time(monkeypatch):
    """26 Okt 2026: snapshot tanpa agent_id tapi ber-submit_time. DWH yang kosong
    (atau submit_time-nya lain) tidak boleh menimpa submit_time snapshot — filter
    tanggal Results (SQL) membaca snapshot, jadi Statistics & export harus sama."""
    monkeypatch.setattr(crud, "_cashline_ids_from_dwh", lambda cids: {
        "blank": {"agent_id": None, "submit_time": None},
        "other": {"agent_id": "dwh801", "submit_time": "2026-06-01 09:00:00"},
    })
    db = _FakeDb([
        ("blank", None, "2026-10-20 12:32:26"),
        ("other", None, "2026-10-21 08:00:00"),
    ])
    index = crud.cashline_agent_index(db)
    assert index["blank"] == {"agent_id": None, "submit_time": "2026-10-20 12:32:26"}
    assert index["other"] == {"agent_id": "dwh801", "submit_time": "2026-10-21 08:00:00"}


def test_dwh_failure_leaves_entry_unknown_instead_of_raising(monkeypatch):
    monkeypatch.setattr(crud.data_dwh, "fetch_bundle_checked", lambda cid: (_ for _ in ()).throw(RuntimeError("DWH down")))
    db = _FakeDb([("noAgent", None, None)])
    assert crud.cashline_agent_index(db) == {"noAgent": {"agent_id": None, "submit_time": None}}


def test_empty_dwh_result_is_not_memoised(monkeypatch):
    """A blank, UNCONFIRMED answer (DWH error/timeout) may just mean the row has not
    landed yet — caching it would pin the ticket to "(Tidak diketahui)" until the
    process restarts. (Confirmed-absent answers get the short negative memo below.)"""
    monkeypatch.setattr(crud.data_dwh, "fetch_bundle_checked", lambda cid: ({"cashline": None}, False))
    crud._cashline_ids_from_dwh(["noAgent"])
    assert "noAgent" not in crud._CASHLINE_ID_MEMO

    monkeypatch.setattr(
        crud.data_dwh, "fetch_bundle_checked",
        lambda cid: ({"cashline": {"agent_id": "late801", "submit_time": "2026-06-01 09:00:00"}}, True),
    )
    assert crud._cashline_ids_from_dwh(["noAgent"])["noAgent"]["agent_id"] == "late801"
    assert crud._CASHLINE_ID_MEMO["noAgent"]["agent_id"] == "late801", "positive result must be memoised"


# --------------------------------------------------------------------------
# Memo NEGATIF berumur pendek (19 Nov 2026): refresh Statistics jalan tiap beberapa
# menit dan worker stats tidak membaca Redis, jadi ~700 id yang memang tidak ada di
# DWH (404 di kedua endpoint) di-probe ulang tiap refresh (~64 dtk). Hanya jawaban
# "PASTI tidak ada" yang ditahan, dan hanya selama _CASHLINE_ID_NEG_TTL_SEC.
# --------------------------------------------------------------------------

_ABSENT = {"cashline": None, "customer": None}


def _count_checked(monkeypatch, bundle, pasti):
    calls = []

    def _fake(cid):
        calls.append(cid)
        return dict(bundle), pasti

    monkeypatch.setattr(crud.data_dwh, "fetch_bundle_checked", _fake)
    return calls


def test_confirmed_absent_ids_are_not_probed_again_within_ttl(monkeypatch):
    calls = _count_checked(monkeypatch, _ABSENT, True)
    cids = [f"gone{i}" for i in range(5)]

    first = crud._cashline_ids_from_dwh(cids)
    second = crud._cashline_ids_from_dwh(cids)

    assert len(calls) == 5, "second pass must be served from the negative memo"
    unknown = {"agent_id": None, "submit_time": None}
    assert first == second == {c: unknown for c in cids}


def test_unconfirmed_dwh_failure_is_probed_again(monkeypatch):
    """pasti=False = DWH down/timeout: NOT proof the row is absent, so no negative memo."""
    calls = _count_checked(monkeypatch, _ABSENT, False)
    crud._cashline_ids_from_dwh(["flaky"])
    crud._cashline_ids_from_dwh(["flaky"])
    assert calls == ["flaky", "flaky"]


def test_negative_memo_expires_and_a_late_row_is_then_picked_up(monkeypatch):
    calls = _count_checked(monkeypatch, _ABSENT, True)
    crud._cashline_ids_from_dwh(["late"])
    monkeypatch.setattr(crud, "_CASHLINE_ID_NEG_TTL_SEC", 0.0)  # entry now expired

    found = {"cashline": {"agent_id": "late801", "submit_time": "2026-11-19 09:00:00"}}
    monkeypatch.setattr(crud.data_dwh, "fetch_bundle_checked", lambda cid: (found, True))

    assert crud._cashline_ids_from_dwh(["late"])["late"]["agent_id"] == "late801"
    assert len(calls) == 1
    assert crud._CASHLINE_ID_MEMO["late"]["agent_id"] == "late801"


# --------------------------------------------------------------------------
# customer_ids_for_agent_ids — the login-scoping lookup built on the index
# --------------------------------------------------------------------------

def test_customer_ids_for_agent_ids_matches_case_insensitively(no_dwh):
    db = _FakeDb([
        ("cidA", "Chreste801", "2026-07-27 16:02:21"),
        ("cidB", "sartika801", "2026-07-27 11:52:32"),
    ])
    assert crud.customer_ids_for_agent_ids(db, ["CHRESTE801"]) == ["cidA"]
    assert sorted(crud.customer_ids_for_agent_ids(db, ["chreste801", "sartika801"])) == ["cidA", "cidB"]


def test_customer_ids_for_agent_ids_empty_input_skips_all_work():
    assert crud.customer_ids_for_agent_ids(_FakeDb([]), []) == []
    assert crud.customer_ids_for_agent_ids(_FakeDb([]), None) == []


def test_existing_row_with_blank_agent_is_not_negatively_memoised(monkeypatch):
    """Only 'no cashline row at all' is negative-cached; a row whose agent_id is
    still blank may be filled in later and must stay retryable."""
    calls = _count_checked(monkeypatch, {"cashline": {"agent_id": "", "submit_time": ""}, "customer": None}, True)
    crud._cashline_ids_from_dwh(["blank"])
    crud._cashline_ids_from_dwh(["blank"])
    assert calls == ["blank", "blank"]
