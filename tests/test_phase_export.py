"""Export agregat per FASE PERCAKAPAN (``compute_phase_export``).

Definisi "gagal" harus sama dengan tab Failure Reason (``_scorecard_failures``), supaya
jumlah baris tiket Not Qualified di export cocok dengan kolom "Failure" kategori itu.

Memakai ``unittest.mock`` (bukan fixture ``monkeypatch``) supaya modul ini bisa
dijalankan tanpa pytest juga — ``stats_aggregate`` mengimpor ``api.*`` yang hanya ada
di image API, yang tidak memuat pytest.
"""
from types import SimpleNamespace
from unittest import mock

try:
    from qc_core.compliance import stats_aggregate as sa
except ImportError:  # image worker tidak memuat paket ``api`` — modul ini dilewati di sana
    import pytest
    pytest.skip("stats_aggregate butuh paket api (hanya ada di image API)",
                allow_module_level=True)


def _item(code, cat, status, **kw):
    return {"item_code": code, "category": cat, "status": status,
            "requirement": f"req {code}", "weight": 2, "reason": f"alasan {code}",
            "evidence": {"timestamp": "00:01.00 - 00:02.00", "quote": "kutipan",
                         "ticket_id": "T1_20260902140527"}, **kw}


def _tiket(items, ai="FAIL", cid="T1"):
    return (SimpleNamespace(campaign="cashline"), cid, {"scorecard_result": items}, ai)


def _jalankan(tikets, fase):
    with mock.patch.object(sa, "_iter_export_tickets", lambda *a, **k: iter(tikets)):
        return sa.compute_phase_export(None, fase)


def test_hanya_item_belum_sesuai_pada_fase_itu():
    d = _jalankan([_tiket([
        _item("SC_CL_1", "Greeting", "SESUAI"),
        _item("SC_CL_2", "Greeting", "BELUM_SESUAI"),
        _item("SC_CL_5", "Probing", "BELUM_SESUAI"),
        _item("SC_CL_6", "Greeting", "TIDAK_DINILAI"),
    ])], "Greeting")
    assert [r["item_code"] for r in d["rows"]] == ["SC_CL_2"]
    assert d["category"] == "fase:Greeting" and d["label"] == "Greeting"


def test_satu_tiket_dua_item_gagal_dua_baris():
    """Sama dengan tab Failure Reason: 'Failure' = total kemunculan, bukan tiket unik."""
    d = _jalankan([_tiket([
        _item("SC_CL_2", "Greeting", "BELUM_SESUAI"),
        _item("SC_CL_3", "Greeting", "BELUM_SESUAI"),
    ])], "Greeting")
    assert len(d["rows"]) == 2


def test_kategori_verifikasi_dicocokkan_lewat_nama_tampilan():
    """Kategori tersimpan 'Verifikasi', tampil 'Verifikasi Statik' (CATEGORY_DISPLAY)."""
    d = _jalankan([_tiket([_item("SC_CL_23_1", "Verifikasi", "BELUM_SESUAI")])],
                  "Verifikasi Statik")
    assert len(d["rows"]) == 1


def test_baris_membawa_status_terbaca_manusia_dan_evidence():
    d = _jalankan([_tiket([_item("SC_CL_2", "Greeting", "BELUM_SESUAI")], ai="PENDING")],
                  "Greeting")
    r = d["rows"][0]
    assert r["ai_status"] == "Pending"          # bukan kode PASS/FAIL/PENDING
    assert r["evidence"] == "kutipan" and r["timestamp"] == "00:01.00 - 00:02.00"
    assert r["sumber_rekaman"] == "T1_20260902140527"


def test_urutan_ticket_lalu_item():
    d = _jalankan([
        _tiket([_item("SC_CL_3", "Greeting", "BELUM_SESUAI"),
                _item("SC_CL_2", "Greeting", "BELUM_SESUAI")], cid="B"),
        _tiket([_item("SC_CL_4", "Greeting", "BELUM_SESUAI")], cid="A"),
    ], "Greeting")
    assert [(r["ticket_id"], r["item_code"]) for r in d["rows"]] == [
        ("A", "SC_CL_4"), ("B", "SC_CL_2"), ("B", "SC_CL_3")]


def test_evidence_kosong_tidak_menjatuhkan_export():
    it = _item("SC_CL_2", "Greeting", "BELUM_SESUAI")
    it["evidence"] = None
    d = _jalankan([_tiket([it])], "Greeting")
    assert d["rows"][0]["evidence"] is None


def test_fase_verifikasi_tidak_jadi_menu():
    fake = lambda *a, **k: ["Greeting", "Verifikasi Statik", "Verifikasi Dinamis", "Probing"]
    with mock.patch.object(sa, "failure_category_columns", fake):
        assert sa.export_phase_labels(None) == ["Greeting", "Probing"]
