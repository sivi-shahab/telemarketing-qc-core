"""Gerbang dokumen konfirmasi pengecualian MUS penyakit whitelist (11 September 2026).

Lihat docs/csv_bank/11 September 2026/MUS_logic_update.md. Penyakit yang TERMASUK
``mus_exemption.DISEASE_WHITELIST`` butuh screenshot email konfirmasi Bank Mega
sebelum pengecualian MUS-nya benar-benar berlaku; di luar whitelist -> flow normal
tanpa jalur dokumen sama sekali.
"""
from qc_core.compliance import documents as docs
from qc_core.compliance import error_codes as ec
from qc_core.compliance import scoring


def _eval(exemption, mus_item_status="TIDAK_DINILAI", cashline="INTERESTED", mus="NOT_INTERESTED"):
    return {
        "cashline_interest": {"status": cashline},
        "mus_interest": {"status": mus},
        "mus_exemption": exemption,
        "scorecard_result": [
            {"item_code": "SC_CL_17", "weight": 3, "category": "Penjelasan Mega Ultima Shield",
             "status": mus_item_status},
            {"item_code": "SC_CL_38", "weight": 7.5, "category": "Legal Statement Mega Ultima Shield",
             "status": mus_item_status},
        ],
    }


# --- apply_mus_exception_document_status ------------------------------------

def test_bukan_exempt_tidak_disentuh():
    ev = _eval({"status": "NOT_EXEMPT", "disease_listed": False})
    out = ec.apply_mus_exception_document_status(ev)
    assert out is ev


def test_hasil_lama_tanpa_disease_listed_tidak_digerbang():
    """Field belum pernah ditanyakan ke LLM -> tidak adanya bukan berarti di luar
    whitelist. Harus tetap EXEMPT apa adanya."""
    ev = _eval({"status": "EXEMPT", "kategori": "SAKIT"})
    out = ec.apply_mus_exception_document_status(ev, sla_expired=True)
    assert out is ev


def test_penyakit_di_luar_whitelist_turun_segera_tanpa_dokumen():
    ev = _eval({"status": "EXEMPT", "kategori": "SAKIT", "disease_listed": False})
    out = ec.apply_mus_exception_document_status(ev)
    assert out["mus_exemption"]["status"] == "NOT_EXEMPT"


def test_dokumen_terbukti_tetap_exempt():
    ev = _eval({"status": "EXEMPT", "kategori": "SAKIT", "disease_listed": True})
    out = ec.apply_mus_exception_document_status(
        ev, uploaded_types=["mus_exception_confirmation"], doc_confirmed=True,
    )
    assert out is ev


def test_belum_terbukti_dalam_sla_jadi_pending():
    ev = _eval({"status": "EXEMPT", "kategori": "SAKIT", "disease_listed": True})
    out = ec.apply_mus_exception_document_status(ev, sla_expired=False, doc_confirmed=False)
    assert out["mus_exemption"]["status"] == "PENDING"
    assert all(
        it["status"] == "PENDING" for it in out["scorecard_result"]
        if scoring.is_mus_item(it)
    )


def test_belum_terbukti_sla_lewat_jadi_not_exempt():
    ev = _eval({"status": "EXEMPT", "kategori": "SAKIT", "disease_listed": True})
    out = ec.apply_mus_exception_document_status(ev, sla_expired=True, doc_confirmed=False)
    assert out["mus_exemption"]["status"] == "NOT_EXEMPT"
    # TIDAK_DINILAI dibiarkan apa adanya -- scoring.scorecard_score yang memotongnya.
    assert all(
        it["status"] == "TIDAK_DINILAI" for it in out["scorecard_result"]
        if scoring.is_mus_item(it)
    )


# --- dampak ke scoring.mus_wajib_tidak_dipenuhi / skor -----------------------

def test_pending_diperlakukan_sama_dengan_exempt():
    ev = _eval({"status": "PENDING", "kategori": "SAKIT", "disease_listed": True})
    assert scoring.mus_wajib_tidak_dipenuhi(ev) is False
    assert scoring.max_score(ev) == 100


def test_not_exempt_setelah_gerbang_memotong_skor_seperti_biasa():
    ev = _eval({"status": "NOT_EXEMPT", "kategori": "SAKIT", "disease_listed": False})
    assert scoring.mus_wajib_tidak_dipenuhi(ev) is True
    assert scoring.max_score(ev) == 136.75
    assert scoring.scorecard_score(ev) == 136.75 - 10.5  # 2 item TIDAK_DINILAI dipotong penuh


# --- documents.mus_exception_doc_requirements / doc_confirmed ---------------

def test_requirement_muncul_untuk_exempt_disease_listed():
    ev = _eval({"status": "EXEMPT", "disease_listed": True})
    reqs = docs.mus_exception_doc_requirements(ev)
    assert [r["doc_type"] for r in reqs] == ["mus_exception_confirmation"]


def test_requirement_tetap_muncul_saat_pending():
    ev = _eval({"status": "PENDING", "disease_listed": True})
    assert docs.mus_exception_doc_types(ev) == ["mus_exception_confirmation"]


def test_requirement_kosong_di_luar_whitelist_atau_not_exempt():
    assert docs.mus_exception_doc_requirements(
        _eval({"status": "EXEMPT", "disease_listed": False})
    ) == []
    assert docs.mus_exception_doc_requirements(
        _eval({"status": "NOT_EXEMPT", "disease_listed": False})
    ) == []


def test_doc_confirmed_cocok_ticket_id_dan_ada_persetujuan():
    ocr_by_type = {
        "mus_exception_confirmation": {
            "ticket_id_found": "030808fLO1",
            "approval_statement_present": True,
        }
    }
    assert docs.mus_exception_doc_confirmed("030808fLO1", ocr_by_type) is True
    # case-insensitive + trim
    assert docs.mus_exception_doc_confirmed("  030808FLO1  ", ocr_by_type) is True


def test_doc_confirmed_false_saat_ticket_id_tidak_cocok_atau_belum_setuju():
    ocr_by_type = {
        "mus_exception_confirmation": {
            "ticket_id_found": "LAIN-TIKET",
            "approval_statement_present": True,
        }
    }
    assert docs.mus_exception_doc_confirmed("030808fLO1", ocr_by_type) is False

    ocr_by_type2 = {
        "mus_exception_confirmation": {
            "ticket_id_found": "030808fLO1",
            "approval_statement_present": False,
        }
    }
    assert docs.mus_exception_doc_confirmed("030808fLO1", ocr_by_type2) is False


def test_doc_confirmed_false_saat_ocr_belum_selesai():
    assert docs.mus_exception_doc_confirmed("030808fLO1", {}) is False
    assert docs.mus_exception_doc_confirmed("030808fLO1", None) is False
