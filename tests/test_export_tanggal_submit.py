"""Tanggal Submit di export Results (26 Oktober 2026).

Filter tanggal Results, Statistics, dan seluruh export memakai SATU tanggal:
Tanggal Submit (``submit_time`` TMS), lalu generated_at, lalu WIB uploaded_at —
aturan ``crud._series_date_expr``. Export Agregat dulu tidak mengenal filter tanggal
sama sekali dan tidak punya kolom tanggal; export Tiket menulis submit_time padahal
filternya ``load_date`` App C.

Memakai ``unittest.mock`` (bukan fixture ``monkeypatch``) dengan alasan yang sama
seperti ``test_phase_export``.
"""
from datetime import date, datetime
from types import SimpleNamespace
from unittest import mock

try:
    from qc_core.compliance import stats_aggregate as sa
except ImportError:  # image worker tidak memuat paket ``api`` — modul ini dilewati di sana
    import pytest
    pytest.skip("stats_aggregate butuh paket api (hanya ada di image API)",
                allow_module_level=True)


def _r(rid, generated_at=None, uploaded_at=None):
    return SimpleNamespace(id=rid, generated_at=generated_at, uploaded_at=uploaded_at,
                           campaign="CashLine NTB", source_files=[f"{rid}_20261020092448.pdf"])


# --- isi sel Tanggal Submit ------------------------------------------------

def test_tanggal_submit_memakai_submit_time_apa_adanya():
    r = _r("A", generated_at=datetime(2026, 10, 1, 8, 0))
    assert sa._tanggal_submit_cell(r, "2026-10-20 12:32:26") == "2026-10-20 12:32:26"


def test_tanpa_submit_time_jatuh_ke_generated_at():
    r = _r("A", generated_at=datetime(2026, 10, 20, 9, 24, 48))
    assert sa._tanggal_submit_cell(r, None) == "2026-10-20 09:24:48"


def test_tanpa_generated_at_jatuh_ke_uploaded_at_wib():
    """uploaded_at naive UTC: 20.00 UTC = 03.00 WIB hari berikutnya — sama dengan filter."""
    r = _r("A", uploaded_at=datetime(2026, 10, 20, 20, 0, 0))
    assert sa._tanggal_submit_cell(r, "") == "2026-10-21 03:00:00"


def test_tanpa_tanggal_apa_pun_kosong():
    assert sa._tanggal_submit_cell(_r("A"), None) is None


# --- jendela tanggal = aturan TicketDates ---------------------------------

def test_jendela_tanggal_menyaring_per_tanggal_tiket():
    rows = [_r("A"), _r("B"), _r("C")]
    tdates = {"A": sa.TicketDates((), date(2026, 10, 19)),
              "B": sa.TicketDates((), date(2026, 10, 20)),
              "C": sa.TicketDates((), None)}
    with mock.patch.object(sa, "_ticket_dates_map", lambda db, rs: tdates):
        kept = sa._in_date_window(None, rows, date(2026, 10, 20), date(2026, 10, 22))
    assert [r.id for r in kept] == ["B"]


def test_tanpa_jendela_tidak_menyaring_dan_tidak_membaca_tanggal():
    rows = [_r("A")]
    with mock.patch.object(sa, "_ticket_dates_map", side_effect=AssertionError):
        assert sa._in_date_window(None, rows, None, None) == rows


def test_tanggal_tiket_mengabaikan_load_date():
    """26 Okt 2026: ``loads`` selalu kosong -> tanggal tiket = Tanggal Submit."""
    r = _r("A", generated_at=datetime(2026, 10, 1, 8, 0))
    with mock.patch.object(sa, "_submit_date_map", lambda db, rs: {"A": date(2026, 10, 20)}):
        td = sa._ticket_dates_map(None, [r])["A"]
    assert td.loads == () and td.single() == date(2026, 10, 20)


# --- kolom Tanggal Submit di export Agregat --------------------------------

def _tiket(ev, tanggal="2026-10-20 12:32:26", cid="T1"):
    return (SimpleNamespace(campaign="CashLine NTB"), cid, ev, "FAIL", tanggal)


def test_export_fase_membawa_tanggal_submit():
    item = {"item_code": "SC_CL_2", "category": "Greeting", "status": "BELUM_SESUAI",
            "evidence": {}}
    with mock.patch.object(sa, "_iter_export_tickets",
                           lambda *a, **k: iter([_tiket({"scorecard_result": [item]})])):
        d = sa.compute_phase_export(None, "Greeting")
    assert d["columns"][:2] == [("ticket_id", "Ticket ID"), ("tanggal_submit", "Tanggal Submit")]
    assert d["rows"][0]["tanggal_submit"] == "2026-10-20 12:32:26"


def test_export_verifikasi_membawa_tanggal_submit():
    cat = next(iter(sa.VERIFICATION_EXPORT_CATEGORIES))
    conf = sa.VERIFICATION_EXPORT_CATEGORIES[cat]
    field = next(iter(conf["fields"])) if conf["fields"] else "nama"
    ev = {conf["block"]: [{"field": field, "match": "MISMATCH"}]}
    with mock.patch.object(sa, "_iter_export_tickets", lambda *a, **k: iter([_tiket(ev)])):
        d = sa.compute_verification_export(None, cat)
    assert d["columns"][:2] == [("ticket_id", "Ticket ID"), ("tanggal_submit", "Tanggal Submit")]
    assert d["rows"][0]["tanggal_submit"] == "2026-10-20 12:32:26"


def test_export_agregat_meneruskan_jendela_tanggal_ke_iterator():
    seen = {}

    def _iter(db, campaign=None, campaigns=None, date_start=None, date_end=None):
        seen.update(date_start=date_start, date_end=date_end)
        return iter(())

    with mock.patch.object(sa, "_iter_export_tickets", _iter):
        sa.compute_phase_export(None, "Greeting", date_start=date(2026, 10, 20),
                                date_end=date(2026, 10, 22))
    assert seen == {"date_start": date(2026, 10, 20), "date_end": date(2026, 10, 22)}
