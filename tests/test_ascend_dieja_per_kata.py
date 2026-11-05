"""Ejaan kode kata nama ibu kandung — 28 Oktober 2026, tiket 011216CB5w."""
from qc_core.compliance.static_similarity import (
    ascend_dieja_per_kata,
    similarity_nama,
    similarity_nama_ibu,
)


def test_kasus_nyata_jane():
    assert similarity_nama("JANE", "Jakarta Alfa November Echo") < 50
    assert ascend_dieja_per_kata("JANE", "Jakarta Alfa November Echo")
    assert similarity_nama_ibu("JANE", "Jakarta Alfa November Echo") == 100.0


def test_ragam_asr_dan_tanda_baca():
    assert ascend_dieja_per_kata("JANE", "Juliet Alpha November Echo.")
    assert ascend_dieja_per_kata("MSMILE", "Mama Sierra Mama India London Echo")


def test_kebetulan_tidak_lolos():
    assert not ascend_dieja_per_kata("ANI", "Ana Nina Indah")          # bukan kata kode
    assert not ascend_dieja_per_kata("JANE", "Jakarta Alfa November")  # kurang kata
    assert not ascend_dieja_per_kata("JANE", "Jakarta Anwar Nasi Echo")  # hanya 1 kata kode
    assert not ascend_dieja_per_kata("JANE", "Budi Alfa November Echo")  # huruf pertama salah
    assert not ascend_dieja_per_kata("AB", "Alfa Bravo")               # < 3 huruf
    assert not ascend_dieja_per_kata("", "Alfa Bravo Charlie")


def test_nama_biasa_tidak_berubah():
    assert similarity_nama_ibu("SITI AMINAH", "Siti Aminah") == similarity_nama("SITI AMINAH", "Siti Aminah")
