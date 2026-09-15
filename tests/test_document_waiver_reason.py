"""Kalimat baris zona abu-abu saat kewajiban dokumen DICABUT (5 September 2026).

Pembebasan 3 September 2026 menutup jalur dokumen seluruhnya — tidak ada permintaan
berkas, tidak ada tenggat H+2, slot unggah tertutup. Tetapi kalimat pada barisnya masih
ditulis untuk dunia tempat dokumen diminta, sehingga tiket ``030808fLO1`` menampilkan
kolom Match berbunyi MATCH tepat di sebelah alasan "mirip 57%, perlu verifikasi dokumen
KK" — menuntut berkas yang slot unggahnya sudah ditutup.

Yang diuji di sini: kalimatnya diperbaiki, dan TIDAK ADA hal lain yang ikut berubah.
Menurunkan ``match`` ke PENDING akan menghidupkan kembali permintaan dokumen
(``card_holder_doc_requirements`` memungut baris MISMATCH/PENDING), jadi justru
membatalkan aturan yang sedang dipatuhi.
"""
from qc_core.compliance.documents import card_holder_doc_requirements
from qc_core.compliance.error_codes import apply_static_document_status


def _eval(sim, *, other_failure=True, field="nama_ibu_kandung"):
    """Evaluasi minimal: satu baris statik + satu item non-tolerable gagal/lulus.

    ``other_failure`` mengendalikan pembebasan: item non-tolerable lain yang gagal
    (``SC_CL_24``) itulah yang mencabut kewajiban dokumen.
    """
    return {
        "static_rules_version": 2,
        "card_holder_verification": [{
            "field": field,
            "match": "MATCH",
            "similarity_percent": sim,
            "extracted_value": "Zandra pakai Z",
            "reference_value": "ZANDRA WILIAM",
            "reason": "Nama Ibu Kandung disebut \"Zandra pakai Z\", Ascend "
                      "\"ZANDRA WILIAM\" — mirip 57%, perlu verifikasi dokumen KK.",
        }],
        "scorecard_result": [{
            "item_code": "SC_CL_24", "tolerable": "NO",
            "status": "BELUM_SESUAI" if other_failure else "SESUAI",
        }],
    }


def test_kalimat_tidak_lagi_menuntut_dokumen_saat_dibebaskan():
    out = apply_static_document_status(_eval(57.0), set(), False)
    reason = out["card_holder_verification"][0]["reason"]
    assert "TIDAK diminta" in reason
    assert "pelanggaran non-tolerable lain" in reason
    assert "perlu verifikasi dokumen" not in reason
    # Angkanya tetap disebut supaya QC tahu seberapa jauh melesetnya.
    assert "57%" in reason and "80%" in reason


def test_match_dan_permintaan_dokumen_tidak_ikut_berubah():
    """Inti kepatuhan pada aturan 3 September: jalur dokumen tetap tertutup."""
    ev = _eval(57.0)
    out = apply_static_document_status(ev, set(), False)
    assert out["card_holder_verification"][0]["match"] == "MATCH"
    assert card_holder_doc_requirements(out) == card_holder_doc_requirements(ev)
    assert out["scorecard_result"] == ev["scorecard_result"]


def test_tanpa_pembebasan_jalur_lama_tetap_berjalan():
    """Tiket tanpa pelanggaran non-tolerable lain: zona abu-abu -> PENDING, dokumen diminta."""
    out = apply_static_document_status(_eval(57.0, other_failure=False), set(), False)
    row = out["card_holder_verification"][0]
    assert row["match"] == "PENDING"
    assert [r["doc_type"] for r in card_holder_doc_requirements(out)] == ["kk"]


def test_baris_di_luar_zona_abu_abu_tidak_disentuh():
    """>= 80% adalah MATCH bersih — tidak ada dokumen yang pernah diminta di sana."""
    ev = _eval(95.0)
    out = apply_static_document_status(ev, set(), False)
    assert out["card_holder_verification"][0]["reason"] == \
        ev["card_holder_verification"][0]["reason"]


def test_tidak_mengubah_masukan():
    ev = _eval(57.0)
    salinan = ev["card_holder_verification"][0]["reason"]
    apply_static_document_status(ev, set(), False)
    assert ev["card_holder_verification"][0]["reason"] == salinan
