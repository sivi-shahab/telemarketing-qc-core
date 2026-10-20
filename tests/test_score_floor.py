"""Skor akhir tidak boleh minus (28 September 2026).

``ai_score_critical_compliance_check`` dan ``non_tolerable_bomb`` adalah suku
negatif yang tidak berbagi anggaran dengan ``phase2`` — cukup banyak item
kritis/non-tolerable gagal dan totalnya bisa minus tanpa batas. Lihat
``scoring.py::phase3_score``.

Angka bobot MUS berbeda antar-branch (35.5/36.75/50 tergantung revisi
scorecard), jadi tes ini sengaja tidak menghardcode total ``max_score`` —
dipakai apa adanya dari ``scoring.max_score`` supaya tetap benar di semua
branch.
"""
from qc_core.compliance import scoring


def _eval(critical=0, belum_non_tolerable=0):
    # Tertarik Mega Cashline saja -> max_score = 100, tanpa cabang
    # mus_wajib_tidak_dipenuhi/mus_cc_interest ikut menambah suku lain.
    # Prefiks SC_XX_ (bukan SC_CL_) sengaja dipakai supaya tidak kebetulan tumpang
    # tindih dengan CRITICAL_ITEM_CODES (SC_CL_4, SC_CL_23_1, SC_CL_23_2, SC_CL_37,
    # SC_CL_24) — item di sini harus dihitung non_tolerable_bomb, bukan dikecualikan.
    scorecard_result = [
        {
            "item_code": f"SC_XX_{i}",
            "weight": 1,
            "category": "Lainnya",
            "status": "BELUM_SESUAI",
            "tolerable": "NO",
        }
        for i in range(belum_non_tolerable)
    ]
    return {
        "cashline_interest": {"status": "INTERESTED"},
        "mus_interest": {"status": "NOT_INTERESTED"},
        "scorecard_result": scorecard_result,
        "ai_score_critical_compliance_check": critical,
        "maximum_score": 100,
    }


def test_phase3_score_dipatok_0_saat_kritis_besar():
    ev = _eval(critical=-10_000)
    assert scoring.phase3_score(ev) == 0


def test_phase3_score_dipatok_0_saat_bomb_non_tolerable_besar():
    # Cukup banyak item non-tolerable BELUM_SESUAI: potongan bobotnya sendiri +
    # bomb 10%/item per pasti melampaui max_score berapa pun itu di branch ini.
    ev = _eval(belum_non_tolerable=1000)
    assert scoring.phase3_score(ev) == 0


def test_phase3_score_tidak_ikut_terpotong_saat_masih_positif():
    ev = _eval(critical=-1)
    max_sc = scoring.max_score(ev)
    assert scoring.phase3_score(ev) == max_sc - 1
