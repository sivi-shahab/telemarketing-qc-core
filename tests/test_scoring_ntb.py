"""Skor campaign New To Bank Eksternal (5 November 2026).

Aturan (prompt ``prompt_ntb_v11`` + keputusan user 5 November 2026):

* skor maksimal ADITIF dari minat: kartu utama 100, + 25 Kartu Tambahan, + 50 Mega
  Ultima Shield (bila Health Declaration tidak NOT_ELIGIBLE); passing grade 90%;
* skor = jumlah poin item yang BERLAKU (SESUAI = bobot, BELUM_SESUAI = 0 kecuali
  kredit parsial, TIDAK_DINILAI = 0 — ikut prompt v11);
* kategori Supplement / MUS yang tidak berlaku untuk varian tidak dihitung;
* ZERO-SCORE bila kartu utama tidak diminati;
* TANPA score bomb dan TANPA veto non-tolerable.

Sumber kasus nyata: tiket 020757P8dx (127,5 / 175, FAIL).
"""
from qc_core.compliance import scoring as s
from qc_core.compliance.two_pass import resync_scores


def _item(code, cat, w, status, tol="NO", score=None):
    if score is None:
        score = w if status == "SESUAI" else (0 if status == "BELUM_SESUAI" else None)
    return {"item_code": code, "category": cat, "weight": w, "status": status,
            "tolerable": tol, "item_score": score, "requirement": f"Agent {code}"}


def _ev(basic="INTERESTED", supl="NOT_INTERESTED", mus="NOT_INTERESTED",
        hd="NOT_REACHED", items=None, n_supl=None):
    return {
        "ntb_interest": {"status": basic},
        "ntb_supplement_interest": {"status": supl, "jumlah_kartu_tambahan": n_supl},
        "ntb_mus_interest": {"status": mus},
        "ntb_mus_eligibility": {"status": hd},
        "maximum_score": 999, "passing_grade": 999,  # angka LLM tidak dipakai
        "ai_score_verification": 0, "ai_score_critical_compliance_check": 0,
        "critical_compliance_check": {"status": "PASS", "checked_items": []},
        "scorecard_result": items or [],
    }


BASIC = "Pengisian Data Basic"
SUPL = "Pengisian Data Supplement"
MUS = "Penjelasan Mega Ultima Shield"


def test_bukan_evaluasi_ntb_tidak_tersentuh():
    cashline = {"cashline_interest": {"status": "INTERESTED"}, "mus_interest": {"status": "INTERESTED"},
                "scorecard_result": []}
    assert not s.is_ntb_evaluation(cashline)
    assert s.max_score(cashline) == 150
    assert not s.is_ntb_evaluation(None)


def test_varian_basic_mus_supl_mengikuti_prompt():
    items = [
        _item("SC_NTB_1", BASIC, 90, "SESUAI"),
        _item("SC_NTB_2", BASIC, 6, "BELUM_SESUAI"),
        _item("SC_NTB_7", "Probing", 4, "TIDAK_DINILAI"),  # kondisional: bernilai 0
        _item("SC_NTB_42", SUPL, 25, "SESUAI"),
        _item("SC_NTB_48", MUS, 40, "SESUAI"),
        _item("SC_NTB_49", MUS, 10, "BELUM_SESUAI"),
    ]
    ev = _ev(supl="INTERESTED", mus="INTERESTED", hd="ELIGIBLE", items=items, n_supl=1)
    assert s.max_score(ev) == 175
    assert s.passing_grade(ev) == 157.5
    assert s.scorecard_score(ev) == 155  # 90 + 25 + 40
    assert s.phase3_score(ev) == 155
    assert s.base_ai_status(ev) == "FAIL"
    assert s.ntb_campaign_interest(ev) == [
        "Kartu Kredit Bank Mega", "Kartu Tambahan (1)", "Mega Ultima Shield"]


def test_tanpa_score_bomb_dan_tanpa_veto():
    items = [_item("SC_NTB_1", BASIC, 95, "SESUAI"), _item("SC_NTB_4", "Greeting", 5, "BELUM_SESUAI", tol="NO")]
    ev = _ev(items=items)
    assert s.non_tolerable_bomb(ev) == 0.0
    assert s.score_bomb_items(ev) == []
    assert not s.has_blocking_intolerable_item(ev)
    assert s.phase3_score(ev) == 95
    assert s.base_ai_status(ev) == "PASS"  # 95 >= 90, item NO gagal tidak memveto


def test_kategori_varian_yang_tidak_berlaku_tidak_dihitung():
    items = [
        _item("SC_NTB_1", BASIC, 100, "SESUAI"),
        _item("SC_NTB_42", SUPL, 25, "BELUM_SESUAI"),   # salah tandai LLM -> diabaikan
        _item("SC_NTB_48", MUS, 50, "SESUAI"),          # tidak berlaku -> tidak menambah
    ]
    ev = _ev(items=items)
    assert s.max_score(ev) == 100
    assert s.scorecard_score(ev) == 100
    assert s.ntb_campaign_interest(ev) == ["Kartu Kredit Bank Mega"]


def test_health_declaration_not_eligible_menggugurkan_mus():
    ev = _ev(supl="INTERESTED", mus="INTERESTED", hd="NOT_ELIGIBLE",
             items=[_item("SC_NTB_48", MUS, 50, "SESUAI")])
    assert s.ntb_flags(ev) == (True, True, False)
    assert s.max_score(ev) == 125
    assert s.scorecard_score(ev) == 0
    assert s.ntb_campaign_interest(ev) == ["Kartu Kredit Bank Mega", "Kartu Tambahan"]


def test_zero_score_bila_kartu_utama_tidak_diminati():
    ev = _ev(basic="NOT_INTERESTED", supl="INTERESTED",
             items=[_item("SC_NTB_1", BASIC, 100, "SESUAI")])
    assert s.no_product_interest(ev)
    assert s.max_score(ev) == 100
    assert s.passing_grade(ev) == 90
    assert s.scorecard_score(ev) == 0
    assert s.base_ai_status(ev) == "FAIL"
    assert s.ntb_campaign_interest(ev) == []


def test_kredit_parsial_dihormati():
    ev = _ev(items=[_item("SC_NTB_1", BASIC, 90, "SESUAI"),
                    _item("SC_NTB_24", BASIC, 10, "BELUM_SESUAI", score=5)])
    assert s.scorecard_score(ev) == 95


def test_resync_scores_menulis_angka_ntb():
    items = [_item("SC_NTB_1", BASIC, 92, "SESUAI"), _item("SC_NTB_2", BASIC, 8, "BELUM_SESUAI")]
    out = resync_scores(_ev(items=items))
    assert out["maximum_score"] == 100
    assert out["passing_grade"] == 90
    assert out["ai_score_phase_2"] == 92
    assert out["ai_score_non_tolerable"] == 0.0
    assert out["ai_score_phase_3"] == 92
    assert out["ai_status"] == "PASS"
