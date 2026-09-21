"""Aturan validitas Mega Ultima Shield (Bank Mega, 8 September 2026).

Rekaman valid = nasabah tertarik Mega Cashline DAN Mega Ultima Shield. Cashline saja
TIDAK valid kecuali ada pengecualian. Konsekuensinya pada angka: skor maksimal tetap
136.75 (bukan turun ke 100), 12 item MUS dipotong, sehingga tiket semacam itu mentok
di 100/136.75 = 73,1% — di bawah batas lulus 123.08.

Bobot di bawah memakai ``Score Card Cashline 18092026.xlsx``: Mega Ultima Shield
35.5->36.75 karena SATU item baru, ``SC_CL_43`` (premi tidak dapat dikembalikan bila
customer membatalkan, bobot 1.25) di kategori Final Konfirmasi Mega Ultima Shield.
Revisi sebelumnya (v4, 14 September 2026) menurunkan Mega Cashline 108.75->100 dan
MUS 41.25->35.5.
"""
from qc_core.compliance import mus_exemption as mx
from qc_core.compliance import scoring

# 12 item MUS beserta bobotnya dari Score Card Cashline 18092026; totalnya tepat 36.75.
MUS_ITEMS = [
    ("SC_CL_17", 3, "Penjelasan Mega Ultima Shield"),
    ("SC_CL_18", 3, "Penjelasan Mega Ultima Shield"),
    ("SC_CL_19", 3, "Penjelasan Mega Ultima Shield"),
    ("SC_CL_20", 3, "Penjelasan Mega Ultima Shield"),
    ("SC_CL_21", 3, "Penjelasan Mega Ultima Shield"),
    ("SC_CL_22", 4, "Penjelasan Mega Ultima Shield"),
    ("SC_CL_33", 2.25, "Final Konfirmasi Mega Ultima Shield"),
    ("SC_CL_34", 2.25, "Final Konfirmasi Mega Ultima Shield"),
    ("SC_CL_35", 2.25, "Final Konfirmasi Mega Ultima Shield"),
    ("SC_CL_36", 2.25, "Final Konfirmasi Mega Ultima Shield"),
    ("SC_CL_43", 1.25, "Final Konfirmasi Mega Ultima Shield"),
    ("SC_CL_38", 7.5, "Legal Statement Mega Ultima Shield"),
]


def _eval(mus_status, *, mus_item_status="TIDAK_DINILAI", exemption=None, cashline="INTERESTED"):
    ev = {
        "cashline_interest": {"status": cashline},
        "mus_interest": {"status": mus_status},
        "passing_grade": 97.88,
        "scorecard_result": [
            {"item_code": c, "weight": w, "category": cat, "status": mus_item_status}
            for c, w, cat in MUS_ITEMS
        ],
    }
    if exemption:
        ev["mus_exemption"] = exemption
    return ev


def test_bobot_mus_berjumlah_36_75():
    assert sum(w for _, w, _ in MUS_ITEMS) == 36.75


# --- predikat inti ---------------------------------------------------------

def test_cashline_saja_tidak_valid():
    assert scoring.mus_wajib_tidak_dipenuhi(_eval("NOT_INTERESTED")) is True


def test_not_stated_diperlakukan_sama_dengan_menolak():
    """Agent yang tidak pernah menawarkan MUS adalah pelanggaran yang justru paling
    ingin ditangkap aturan ini — membebaskannya melubangi aturannya sendiri."""
    assert scoring.mus_wajib_tidak_dipenuhi(_eval("NOT_STATED")) is True


def test_kedua_produk_diminati_tetap_valid():
    assert scoring.mus_wajib_tidak_dipenuhi(_eval("INTERESTED")) is False


def test_pengecualian_membebaskan():
    ev = _eval("NOT_INTERESTED", exemption={"status": "EXEMPT", "kategori": "SAKIT"})
    assert scoring.mus_wajib_tidak_dipenuhi(ev) is False


def test_pengecualian_yang_bukan_exempt_tidak_membebaskan():
    ev = _eval("NOT_INTERESTED", exemption={"status": "NOT_EXEMPT", "reason": "-"})
    assert scoring.mus_wajib_tidak_dipenuhi(ev) is True


def test_tanpa_minat_cashline_bukan_urusan_aturan_ini():
    """Yang berlaku ZERO-SCORE RULE, bukan aturan MUS — satu tiket tidak boleh
    dihukum dua kali oleh dua aturan berbeda."""
    ev = _eval("NOT_INTERESTED", cashline="NOT_INTERESTED")
    assert scoring.mus_wajib_tidak_dipenuhi(ev) is False
    assert scoring.no_product_interest(ev) is True


# --- dampak ke angka -------------------------------------------------------

def test_skor_maksimal_tetap_135_5_saat_mus_wajib():
    assert scoring.max_score(_eval("NOT_INTERESTED")) == 136.75
    assert scoring.passing_grade(_eval("NOT_INTERESTED")) == 123.08


def test_skor_maksimal_turun_saat_dikecualikan():
    ev = _eval("NOT_INTERESTED", exemption={"status": "EXEMPT", "kategori": "SAKIT"})
    assert scoring.max_score(ev) == 100
    assert scoring.passing_grade(ev) == 90


def test_item_mus_tidak_dinilai_dipotong_penuh():
    """Tanpa potongan ini skor maksimal naik ke 136.75 sementara 12 item MUS tidak
    dipotong apa pun — tiket cashline-saja justru dapat 36.75 poin gratis."""
    ev = _eval("NOT_INTERESTED")
    assert scoring.scorecard_score(ev) == 100
    assert scoring.base_ai_status(ev) == "FAIL"


def test_item_mus_sesuai_tetap_dihargai():
    """Nasabah menolak SETELAH agent menjelaskan MUS: yang sudah dikerjakan tetap
    dihargai, tidak ikut dihanguskan.

    Kasus ekstrem ini sengaja diuji untuk menegaskan bahwa aturan MUS bekerja lewat
    ARITMETIKA, bukan veto — bila seluruh 11 item MUS bernilai SESUAI, tiketnya
    memang lulus. Di lapangan susunan itu tidak bisa terjadi: SC_CL_38 "Legal
    Statement Mega Ultima Shield" baru SESUAI bila nasabah menyatakan setuju, yang
    dengan sendirinya membuat mus_interest = INTERESTED. Yang realistis adalah
    penjelasan SESUAI tetapi Final Konfirmasi (9) + Legal Statement (7.5) gagal,
    yakni 136.75 - 16.5 = 120.25 — masih di bawah batas lulus 123.08.
    """
    ev = _eval("NOT_INTERESTED", mus_item_status="SESUAI")
    assert scoring.scorecard_score(ev) == 136.75
    assert scoring.base_ai_status(ev) == "PASS"


def test_penolakan_realistis_tetap_tidak_lulus():
    """Penjelasan MUS lengkap, tetapi konfirmasi & legal statement gagal karena
    nasabah menolak — susunan yang sebenarnya terjadi di lapangan."""
    ev = _eval("NOT_INTERESTED", mus_item_status="SESUAI")
    for it in ev["scorecard_result"]:
        if it["category"] != "Penjelasan Mega Ultima Shield":
            it["status"] = "BELUM_SESUAI"
    assert scoring.scorecard_score(ev) == 119
    assert scoring.passing_grade(ev) == 123.08
    assert scoring.base_ai_status(ev) == "FAIL"


def test_belum_sesuai_tidak_dipotong_dua_kali():
    ev = _eval("NOT_INTERESTED", mus_item_status="BELUM_SESUAI")
    assert scoring.scorecard_score(ev) == 136.75 - 36.75


def test_dikecualikan_memakai_perhitungan_lama():
    ev = _eval("NOT_INTERESTED", exemption={"status": "EXEMPT", "kategori": "HAMIL"})
    assert scoring.scorecard_score(ev) == 100
    assert scoring.base_ai_status(ev) == "PASS"


# --- daftar tetap Bank Mega ------------------------------------------------

def test_daftar_memuat_tiket_acuan():
    e = mx.register_entry("030808fLO1")
    assert e is not None
    assert e["kategori"] == mx.KATEGORI_SAKIT
    assert "jantung" in e["reason"].lower()


def test_lookup_abai_huruf_besar_dan_spasi():
    assert mx.register_entry("  030808flo1  ") is not None


def test_tiket_di_luar_daftar():
    assert mx.register_entry("0110505ngB") is None
    assert mx.register_entry("") is None
    assert mx.register_entry(None) is None


def test_resolve_transkrip_tetap_penentu_walau_terdaftar_di_daftar():
    """Transkrip adalah satu-satunya sumber yang menentukan status — daftar Bank Mega
    hanya dicatat sebagai pembanding, tidak pernah menimpa bacaan transkrip."""
    ev = {"mus_exemption": {"status": "EXEMPT", "kategori": "HAMIL", "reason": "dari transkrip"}}
    out = mx.resolve(ev, "030808fLO1")
    assert out["sumber"] == "transkrip"
    assert out["status"] == "EXEMPT"
    assert out["kategori"] == "HAMIL"
    assert out["daftar_bank_mega"]["kategori"] == mx.KATEGORI_SAKIT
    assert out["sepakat"] is True


def test_resolve_daftar_tidak_bisa_membebaskan_tanpa_transkrip():
    """Daftar berkata EXEMPT tetapi transkrip tidak menangkap alasannya: status akhir
    TETAP NOT_EXEMPT, daftar hanya tercatat sebagai pembanding yang tidak sepakat."""
    ev = {"mus_exemption": {"status": "NOT_EXEMPT"}}
    out = mx.resolve(ev, "030808fLO1")
    assert out["status"] == "NOT_EXEMPT"
    assert out["sumber"] == "transkrip"
    assert out["daftar_bank_mega"]["kategori"] == mx.KATEGORI_SAKIT
    assert out["sepakat"] is False


def test_resolve_memakai_transkrip_saat_belum_terdaftar():
    """Tiket yang belum masuk daftar Bank Mega tetap dibebaskan murni dari transkrip."""
    ev = {"mus_exemption": {"status": "EXEMPT", "kategori": "SAKIT", "reason": "riwayat jantung"}}
    out = mx.resolve(ev, "TIKET-BARU-BELUM-TERDAFTAR")
    assert out["sumber"] == "transkrip"
    assert out["kategori"] == mx.KATEGORI_SAKIT
    assert "daftar_bank_mega" not in out


def test_resolve_mengembalikan_none_tanpa_alasan_apa_pun():
    assert mx.resolve({}, "0110505ngB") is None
    assert mx.resolve({"mus_exemption": {"status": "NOT_EXEMPT"}}, "0110505ngB") is None
