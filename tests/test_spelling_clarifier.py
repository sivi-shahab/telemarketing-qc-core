"""Penjelas ejaan pada ucapan nasabah ("Zandra pakai Z") — 5 September 2026.

Nasabah kerap menegaskan cara menulis namanya. Keterangan itu bukan bagian dari
namanya, tetapi tanpa dibuang ia ikut dihitung sebagai huruf pembanding — dan bisa
MENAIKKAN skor secara palsu: "Zandra pakai Z" bernilai 57% terhadap Ascend
"ZANDRA WILIAM" sementara namanya sendiri hanya 46%, karena huruf "pakai z" kebetulan
menyerempet "wiliam".

Uji di bawah menjaga dua sisi sekaligus: penjelasnya benar-benar dibuang, dan
pembersihnya TIDAK memakan kata biasa yang kebetulan berawalan sama.
"""
from qc_core.compliance.static_similarity import _norm_name, similarity_nama


def test_penjelas_ejaan_dibuang():
    assert _norm_name("Zandra pakai Z") == "zandra"
    assert _norm_name("Zandra pake Z") == "zandra"
    assert _norm_name("Stefanus pakai f dani") == "stefanus dani"
    assert _norm_name("Indocement pakai C ya") == "indocement"
    assert _norm_name("Sari huruf S") == "sari"
    assert _norm_name("Bagas dengan G besar") == "bagas"


def test_skor_palsu_hilang():
    """57% -> 46%: angka jujurnya, karena nasabah hanya menyebut nama depan."""
    assert similarity_nama("ZANDRA WILIAM", "Zandra pakai Z") == \
        similarity_nama("ZANDRA WILIAM", "Zandra") == 46.0


def test_kata_biasa_tidak_dimakan():
    """Yang dibuang HANYA bila kata penanda diikuti SATU huruf.

    "Pakai dong. Delapan satu." (tiket 061050ugYQ) harus utuh — "dong" bukan huruf
    tunggal, dan memakannya akan menghapus jawaban tanggal lahir nasabah.
    """
    assert _norm_name("Pakai dong. Delapan satu.") == "pakai dong. delapan satu"
    assert _norm_name("Dewi dengan Sari") == "dewi dengan sari"
    assert _norm_name("Ibu Huruf Indah") == "huruf indah"      # sapaan dibuang, nama utuh


def test_tidak_merusak_normalisasi_lain():
    """Ejaan huruf-per-huruf dan nama bertanda hubung tetap seperti sebelumnya."""
    assert _norm_name("N-G T-J-U L-I-E-N.") == "ng tju lien"
    assert _norm_name("Nur-Aini") == "nur-aini"
    assert _norm_name("Nama ibu kandung, Wong Aiua.") == "wong aiua"


def test_ejaan_plus_penjelas_tetap_terbaca():
    """Penjelas dibuang SESUDAH ejaan digabung, jadi ejaannya tidak ikut hilang."""
    assert _norm_name("Z-A-N-D-R-A pakai Z") == "zandra"
