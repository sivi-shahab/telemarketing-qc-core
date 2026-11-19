"""Memo per-perhitungan untuk index berat Statistics (19 November 2026).

``/stats/ai_status_timeseries`` untuk kombinasi filter yang belum pernah dihitung butuh
24-40 dtk (> timeout axios 30 dtk). Profil menunjukkan 15 dari 32 query SQL-nya
DUPLIKAT PERSIS (``cashline_agent_index`` 6x, ``reference_snapshot_index`` 2x,
``cashline_change_flags_index`` 2x; ~14 dtk), masing-masing memindai seluruh
``result_data.result_json``.

Memo-nya OPT-IN (``crud.request_memo(db)``): di luar blok itu perilaku tidak berubah,
sehingga worker/evaluasi yang memakai satu sesi lintas commit tidak pernah membaca
data basi.
"""
import pytest

from qc_core.db import crud
from qc_core.compliance import documents, reference_data, stats_aggregate


class _FakeQuery:
    def __init__(self, db):
        self._db = db

    def join(self, *a, **k):
        return self

    def distinct(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def all(self):
        self._db.executed += 1
        return self._db.rows


class _FakeDb:
    """Sesi palsu: ``.info`` seperti ``Session.info``; menghitung query yang jalan."""

    def __init__(self, rows):
        self.rows = rows
        self.executed = 0
        self.info = {}

    def query(self, *a, **k):
        return _FakeQuery(self)


@pytest.fixture(autouse=True)
def _no_dwh(monkeypatch):
    # Baris contoh sudah punya agent_id, tapi jangan pernah menyentuh DWH di tes ini.
    monkeypatch.setattr(crud, "_cashline_ids_from_dwh", lambda cids: {})


ROWS = [("c1", "agent1", "2026-11-19 09:00:00"), ("c2", "agent2", "2026-11-19 10:00:00")]


def test_without_request_memo_every_call_hits_the_database():
    db = _FakeDb(ROWS)
    crud.cashline_agent_index(db)
    crud.cashline_agent_index(db)
    assert db.executed == 2, "di luar request_memo perilaku lama harus utuh"


def test_inside_request_memo_the_same_index_is_queried_once():
    db = _FakeDb(ROWS)
    with crud.request_memo(db):
        first = crud.cashline_agent_index(db)
        second = crud.cashline_agent_index(db)
        third = crud.cashline_agent_index(db)
    assert db.executed == 1
    assert first == second == third
    assert first["c1"] == {"agent_id": "agent1", "submit_time": "2026-11-19 09:00:00"}


def test_memo_does_not_outlive_the_block():
    db = _FakeDb(ROWS)
    with crud.request_memo(db):
        crud.cashline_agent_index(db)
    assert "_request_memo" not in db.info
    crud.cashline_agent_index(db)
    assert db.executed == 2, "setelah blok selesai, data harus dibaca segar lagi"


def test_caller_mutating_a_result_cannot_corrupt_the_memo():
    db = _FakeDb(ROWS)
    with crud.request_memo(db):
        a = crud.cashline_agent_index(db)
        a["c1"]["agent_id"] = "HACKED"
        a["new"] = {"agent_id": "x", "submit_time": None}
        b = crud.cashline_agent_index(db)
    assert b["c1"]["agent_id"] == "agent1"
    assert "new" not in b


def test_nested_blocks_share_the_outer_memo_and_do_not_clear_it_early():
    db = _FakeDb(ROWS)
    with crud.request_memo(db):
        crud.cashline_agent_index(db)
        with crud.request_memo(db):
            crud.cashline_agent_index(db)
        crud.cashline_agent_index(db)
    assert db.executed == 1


def test_different_cid_filters_are_memoised_separately():
    db = _FakeDb([("c1", {}), ("c2", {})])
    with crud.request_memo(db):
        a1 = crud.cashline_change_flags_index(db, ["c1"])
        a2 = crud.cashline_change_flags_index(db, ["c1"])
        b = crud.cashline_change_flags_index(db, ["c1", "c2"])
    assert db.executed == 2, "['c1'] sekali + ['c1','c2'] sekali"
    assert a1 == a2
    assert set(b) >= set(a1)


def test_session_without_info_attribute_still_works():
    db = _FakeDb(ROWS)
    db.info = None
    with crud.request_memo(db):
        crud.cashline_agent_index(db)
        crud.cashline_agent_index(db)
    assert db.executed == 2, "tanpa Session.info tidak ada memo, dan tidak error"


# --------------------------------------------------------------------------
# _missing_docs_map: normalisasi verifikasi (~1,3 ms/baris) cukup SEKALI per baris
# --------------------------------------------------------------------------

class _Row:
    def __init__(self, rid, cid):
        self.id = rid
        self.source_files = [f"{cid}_t.txt"]
        self.uploaded_at = None


def test_missing_docs_map_normalises_each_result_once(monkeypatch):
    monkeypatch.setattr(crud, "document_types_by_result", lambda db, ids: {})
    monkeypatch.setattr(crud, "document_ocr_by_result", lambda db, ids: {})
    monkeypatch.setattr(crud, "cashline_change_flags_index", lambda db, cids: {
        "c1": {"kantor": False, "rumah": False, "npwp": False, "nik": False},
        "c2": {"kantor": False, "rumah": False, "npwp": False, "nik": False},
    })
    monkeypatch.setattr(documents, "card_holder_bands_apply", lambda uploaded_at: True)
    monkeypatch.setattr(reference_data, "get_credit_limit", lambda cid, db: None)

    calls = []
    real = stats_aggregate._normalized_json

    def _counting(rj):
        calls.append(rj)
        return real(rj)

    monkeypatch.setattr(stats_aggregate, "_normalized_json", _counting)

    rows = [_Row("r1", "c1"), _Row("r2", "c2")]
    ev = {"r1": {"evaluation": {}}, "r2": {"evaluation": {}}}
    out = stats_aggregate._missing_docs_map(_FakeDb([]), rows, ev)

    assert out == {"r1": False, "r2": False}
    assert len(calls) == len(rows), f"dinormalkan {len(calls)}x untuk {len(rows)} baris"
