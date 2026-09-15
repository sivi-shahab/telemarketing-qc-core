"""Dokumen yang sudah diunggah tidak selalu boleh dihitung "sudah diunggah".

Dua sebab berbeda mencoretnya, dan keduanya HARUS dipakai di tempat yang sama:

* jenisnya keliru — slot KTP diisi KK (sejak 14 Agustus 2026);
* jenisnya benar tetapi isinya tidak cocok dengan acuan bank (sejak 3 September 2026).

Sebelumnya ``_missing_docs_map`` dan ``document_status_map`` masing-masing menyalin
logikanya sendiri, dan hanya sebab pertama yang tercakup. ``_unproven_doc_types``
menyatukannya. Test ini menjaga penyatuan itu: berkas ``stats_aggregate.py``
di-merge TANGAN (bukan disalin utuh dari repo monolit, karena sumber datanya di sini
sudah pindah ke snapshot DWH), jadi dua pemanggil itu gampang tertinggal satu.
"""
from qc_core.compliance import stats_aggregate as sa


# Slot KTP diisi dokumen yang terbaca sebagai KK -> jenis keliru.
_JENIS_KELIRU = ("ktp", {"jenis_dokumen": "KK"})
# Slot KTP berisi KTP, tetapi NIK-nya tidak cocok dengan acuan bank.
_ISI_TIDAK_COCOK = ("ktp", {
    "jenis_dokumen": "KTP",
    "verifications": [
        {"field": "nik", "acuan": "3171000000000002",
         "document": "3171000000000001", "match": False, "similarity": 93},
    ],
})
# Jenis benar, seluruh field terbukti cocok.
_BERSIH = ("npwp", {
    "jenis_dokumen": "NPWP",
    "verifications": [
        {"field": "nomor_npwp", "acuan": "09.254.294.3-407.000",
         "document": "09.254.294.3-407.000", "match": True, "similarity": 100},
    ],
})
# Tidak ada acuan pembanding -> "tidak tahu", BUKAN "tidak cocok".
_TANPA_ACUAN = ("ktp", {
    "jenis_dokumen": "KTP",
    "verifications": [
        {"field": "nik", "acuan": "", "document": "3171000000000001", "match": False},
    ],
})
# Berkas tidak terbaca -> keluhan mutu berkas, bukan salah jenis.
_TIDAK_JELAS = ("ktp", {"jenis_dokumen": "TIDAK_JELAS"})


def test_jenis_keliru_dicoret():
    assert "ktp" in sa._unproven_doc_types([_JENIS_KELIRU])


def test_isi_tidak_cocok_ikut_dicoret():
    assert "ktp" in sa._unproven_doc_types([_ISI_TIDAK_COCOK])


def test_dokumen_bersih_tidak_dicoret():
    assert sa._unproven_doc_types([_BERSIH]) == set()


def test_tanpa_acuan_bukan_tidak_cocok():
    """Tidak ada pembanding berarti tidak tahu — dokumennya tidak boleh dicoret."""
    assert sa._unproven_doc_types([_TANPA_ACUAN]) == set()


def test_berkas_tidak_terbaca_bukan_salah_jenis():
    assert sa._unproven_doc_types([_TIDAK_JELAS]) == set()


def test_tanpa_dokumen_aman():
    assert sa._unproven_doc_types([]) == set()
    assert sa._unproven_doc_types(None) == set()


def test_mismatch_terbawa_ke_baris_error_code():
    """``mismatched_document_types`` memberi label + daftar field ke C03."""
    rows = sa.mismatched_document_types([_ISI_TIDAK_COCOK])
    assert rows, "dokumen yang isinya tidak cocok harus menghasilkan baris mismatch"
    assert rows[0]["label"] == "KTP"
    assert "nik" in rows[0]["fields"]


def test_dokumen_bersih_tidak_menghasilkan_mismatch():
    assert sa.mismatched_document_types([_BERSIH]) == []
