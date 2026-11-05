"""NTB monorepo memakai baris TMS NTB dari DWH production (bukan tabel ``tms_ntb``)."""
from unittest.mock import MagicMock

from qc_core.db import crud


def test_tanpa_db_langsung_tanya_dwh(monkeypatch):
    seen = []
    monkeypatch.setattr(crud.data_dwh, "fetch_ntb_checked",
                        lambda rid: (seen.append(rid) or ({"result_id": rid, "submit_time": "2026-11-01"}, True)))
    assert crud.get_tms_ntb_by_result_id(None, " 020757P8dx ") == {"result_id": "020757P8dx", "submit_time": "2026-11-01"}
    assert seen == ["020757P8dx"]


def test_snapshot_reference_data_ntb_didahulukan(monkeypatch):
    monkeypatch.setattr(crud.data_dwh, "fetch_ntb_checked", lambda rid: (_ for _ in ()).throw(AssertionError("DWH tidak boleh dipanggil")))
    db = MagicMock()
    db.query.return_value.join.return_value.filter.return_value.order_by.return_value.first.return_value = ({"agent_id": "fikri801"},)
    assert crud.get_tms_ntb_by_result_id(db, "040845DQJG") == {"agent_id": "fikri801"}


def test_snapshot_null_jatuh_ke_dwh_dan_kosong(monkeypatch):
    monkeypatch.setattr(crud.data_dwh, "fetch_ntb_checked", lambda rid: (None, True))
    db = MagicMock()
    db.query.return_value.join.return_value.filter.return_value.order_by.return_value.first.return_value = (None,)
    assert crud.get_tms_ntb_by_result_id(db, "X1") is None
    assert crud.get_tms_ntb_by_result_id(db, "") is None
