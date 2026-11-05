"""SC_NTB_22: TIDAK_DINILAI selama Source Data handphone belum ada (27 Oktober 2026)."""
from qc_core.compliance.ntb_verification import apply_handphone_belum_dinilai, apply_verification_verdicts


def _ev(status="BELUM_SESUAI", extraction=None):
    return {"ntb_application_extraction": extraction or {}, "scorecard_result": [
        {"item_code": "SC_NTB_1", "status": "SESUAI", "weight": 1, "item_score": 1},
        {"item_code": "SC_NTB_22", "status": status, "weight": 2, "item_score": 0, "reason": "llm"},
    ]}


def _sc22(ev):
    return next(r for r in ev["scorecard_result"] if r["item_code"] == "SC_NTB_22")


def test_belum_sesuai_dari_llm_jadi_tidak_dinilai():
    ev = apply_handphone_belum_dinilai(_ev("BELUM_SESUAI"), {"handphone": "085816952802"})
    r = _sc22(ev)
    assert r["status"] == "TIDAK_DINILAI" and r["item_score"] == 0 and "Microsite" in r["reason"]


def test_sesuai_dari_llm_juga_tidak_dinilai():
    assert _sc22(apply_handphone_belum_dinilai(_ev("SESUAI"), {"handphone": "085816952802"}))["status"] == "TIDAK_DINILAI"


def test_nomor_sama_dengan_keluarga_dekat_tetap_belum_sesuai():
    tms = {"handphone": "085816952802", "handphone-keluarga-dekat": "085816952802"}
    ev = apply_verification_verdicts(_ev("SESUAI"), tms)
    assert _sc22(ev)["status"] == "BELUM_SESUAI"
    assert _sc22(apply_handphone_belum_dinilai(ev, tms))["status"] == "BELUM_SESUAI"


def test_tanpa_item_atau_bukan_dict_tidak_berbuat_apa_apa():
    ev = {"scorecard_result": [{"item_code": "SC_NTB_1", "status": "SESUAI"}]}
    assert apply_handphone_belum_dinilai(ev, {}) is ev
    assert apply_handphone_belum_dinilai(None, {}) is None
