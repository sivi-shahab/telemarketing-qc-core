"""Skor akhir tidak boleh minus (28 September 2026).

``ai_score_critical_compliance_check`` dan ``non_tolerable_bomb`` adalah suku
negatif yang tidak berbagi anggaran dengan ``phase2`` — cukup banyak item
kritis/non-tolerable gagal dan totalnya bisa minus tanpa batas. Lihat
``scoring.py::phase3_score``.
"""
from qc_core.compliance import scoring


def _eval(critical=0, belum_non_tolerable=0):
    # Tertarik kedua produk -> max_score = 100 + 50 = 150 (scoring.max_score), supaya
    # mus_wajib_tidak_dipenuhi tidak ikut menambah cabang perhitungan lain.
    # Prefiks SC_XX_ (bukan SC_CL_) sengaja dipakai supaya tidak kebetulan tumpang
    # tindih dengan CRITICAL_ITEM_CODES (SC_CL_4, SC_CL_23_1, SC_CL_23_2, SC_CL_37,
    # SC_CL_24) — item di sini harus dihitung non_tolerable_bomb, bukan dikecualikan.
    scorecard_result = [
        {
            "item_code": f"SC_XX_{i}",
            "weight": 10,
            "category": "Lainnya",
            "status": "BELUM_SESUAI",
            "tolerable": "NO",
        }
        for i in range(belum_non_tolerable)
    ]
    return {
        "cashline_interest": {"status": "INTERESTED"},
        "mus_interest": {"status": "INTERESTED"},
        "scorecard_result": scorecard_result,
        "ai_score_critical_compliance_check": critical,
        "maximum_score": 100,
    }


def test_phase3_score_dipatok_0_saat_kritis_besar():
    # phase2 = 150 (tanpa potongan), critical = -300 -> total mentah -150.
    ev = _eval(critical=-300)
    assert scoring.phase3_score(ev) == 0


def test_phase3_score_dipatok_0_saat_bomb_non_tolerable_besar():
    # phase2 = 150 - (10 x 10) = 50; bomb = -(100 x 10%) x 10 = -100 -> total mentah -50.
    ev = _eval(belum_non_tolerable=10)
    assert scoring.phase3_score(ev) == 0


def test_phase3_score_tidak_ikut_terpotong_saat_masih_positif():
    # phase2 = 150, critical = -10 -> total 140, masih positif, tidak boleh terpotong.
    ev = _eval(critical=-10)
    assert scoring.phase3_score(ev) == 140
