"""Anotasi penawaran pada ``cust_name`` TMS (export NTB 7 September 2026).

Sejak export itu kolom ``cust_name`` tidak lagi berisi nama nasabah saja:

    GAGA NUGRAHA_45jt_300_175_NPWP_C5.0jt

Nama beranotasi merusak dua hal: ia menjadi ``nama_acuan`` OCR KTP dan ``nama_anak``
OCR KK (OCR lalu membandingkan nama di kartu dengan "NAMA_45jt_300_175_NPWP" dan tidak
akan pernah cocok), serta menjadi ``customer_name`` di tabel Results halaman Sales Agent.

[ADAPTASI] Docstring ASAL di repo monolit juga menyebut padanan Ascend by
``CUST_LOCAL_NAME`` (terukur 0 dari 53 tiket seed cocok mentah, 53 dari 53 setelah
dibersihkan). Alasan itu tidak berlaku di sini: baris CARD HOLDER dicocokkan
Aplikasi A by ``no-ktpkitas``, bukan by nama. Perilaku yang diuji di bawah TIDAK
berubah sedikit pun — hanya alasan kenapa ia penting yang menyusut jadi dua.

Dua arah kesalahan yang dijaga: anotasi yang lolos (nama kotor sampai ke Ascend/OCR),
dan nama asli yang ikut terpangkas hanya karena kebetulan memuat underscore.
"""
from qc_core.compliance.reference_data import customer_name_of, parse_cust_name


# --------------------------------------------------------------------------
# Bentuk penuh
# --------------------------------------------------------------------------

def test_anotasi_lengkap_terurai():
    a = parse_cust_name("GAGA NUGRAHA_45jt_300_175_NPWP_C5.0jt")
    assert a["nama"] == "GAGA NUGRAHA"
    assert a["limit_penawaran"] == 45_000_000
    assert a["persen_limit"] == 300          # 300% dari limit kartu 15jt
    assert a["bunga_persen"] == 1.75         # 175 -> 1,75% per bulan
    assert a["butuh_npwp"] is True
    assert a["opsi_cld"] == 5_000_000
    assert a["new_to_bank"] is False


def test_bentuk_terpendek_tanpa_npwp_dan_cld():
    a = parse_cust_name("YOGI PRATAMA S_15jt_80_209")
    assert a["nama"] == "YOGI PRATAMA S"
    assert (a["limit_penawaran"], a["persen_limit"], a["bunga_persen"]) == (15_000_000, 80, 2.09)
    assert a["butuh_npwp"] is False
    assert a["opsi_cld"] is None


# --------------------------------------------------------------------------
# New To Bank — tidak punya limit kartu berjalan, jadi limit+persen diganti "NTB"
# --------------------------------------------------------------------------

def test_ntb_angka_tunggal_dibaca_sebagai_bunga_bukan_persen():
    a = parse_cust_name("SWASTIKA AJENG DEWANTI_NTB_220")
    assert a["nama"] == "SWASTIKA AJENG DEWANTI"
    assert a["new_to_bank"] is True
    assert a["bunga_persen"] == 2.20
    assert a["persen_limit"] is None         # NTB tidak punya limit acuan
    assert a["limit_penawaran"] is None


def test_ntb_masih_bisa_membawa_npwp_dan_cld():
    assert parse_cust_name("SIMON MANDILA_NTB_220_NPWP")["butuh_npwp"] is True
    assert parse_cust_name("MAYA LISTIA DEWI_NTB_220_C5.0jt")["opsi_cld"] == 5_000_000


# --------------------------------------------------------------------------
# Bentuk cacat yang benar-benar ada di export
# --------------------------------------------------------------------------

def test_underscore_menggantung_di_ekor():
    assert customer_name_of("HATA SEPTIAWAN_12jt_80_209_") == "HATA SEPTIAWAN"


def test_huruf_kecil_dan_spasi_ikut_dikenali():
    assert customer_name_of("  BUDI SANTOSO_15JT_80_209  ") == "BUDI SANTOSO"


# --------------------------------------------------------------------------
# Nama yang TIDAK beranotasi tidak boleh terpangkas
# --------------------------------------------------------------------------

def test_nama_tanpa_anotasi_utuh():
    assert customer_name_of("BUDI SANTOSO") == "BUDI SANTOSO"


def test_underscore_yang_bukan_anotasi_dibiarkan():
    # Kalau ini terpangkas jadi "SITI", tiketnya kehilangan padanan Ascend yang
    # sebenarnya ada — kegagalan yang persis sama dengan yang mau diperbaiki.
    assert customer_name_of("SITI_AISYAH") == "SITI_AISYAH"
    assert customer_name_of("NAMA_TANPA_ANGKA") == "NAMA_TANPA_ANGKA"


def test_kosong_aman():
    assert customer_name_of(None) == ""
    assert customer_name_of("") == ""
