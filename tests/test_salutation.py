"""Peringatan sapaan: murni informasi, tidak menyentuh skor/scorecard."""
import copy

from qc_core.compliance.salutation import salutation_warnings


def _ev(status="MISMATCH", awal="Ibu", lalu="Bapak", ts="00:00.98 -> 00:03.52"):
    return {
        "scorecard_result": [{"item_code": "SC_CL_1", "status": "SESUAI"}],
        "salutation_check": {
            "status": status,
            "opening_salutation": awal,
            "later_salutation": lalu,
            "evidence": {"timestamp": ts, "quote": "selamat siang Ibu Yemi"},
        },
    }


def test_mismatch_menghasilkan_satu_peringatan():
    w = salutation_warnings(_ev())
    assert len(w) == 1
    assert '"Ibu"' in w[0] and '"Bapak"' in w[0] and "00:00.98" in w[0]
    assert "Tidak mengurangi skor" in w[0]


def test_ok_not_stated_dan_tiket_lama_tanpa_peringatan():
    assert salutation_warnings(_ev(status="OK")) == []
    assert salutation_warnings(_ev(status="NOT_STATED")) == []
    assert salutation_warnings({"scorecard_result": []}) == []
    assert salutation_warnings(None) == []
    assert salutation_warnings({"salutation_check": "MISMATCH"}) == []


def test_status_huruf_kecil_tetap_dikenali_dan_sapaan_kosong_tidak_error():
    w = salutation_warnings(_ev(status="mismatch", awal=None, lalu=None, ts=None))
    assert w == ["Sapaan pembuka berbeda dengan sapaan selanjutnya. Tidak mengurangi skor."]


def test_tidak_mengubah_evaluasi():
    ev = _ev()
    asli = copy.deepcopy(ev)
    salutation_warnings(ev)
    assert ev == asli
