"""load_prompt_module() me-resolve modul prompt lewat STRING, bukan impor biasa.

Karena berupa string di DOCUMENT_TYPES, rewrite impor otomatis tidak menyentuhnya.
Kalau string itu masih "prompt.ocr_ktp" (bukan "qc_core.prompt.ocr_ktp"), tidak ada
yang gagal saat build image -- kegagalannya baru muncul saat task OCR berjalan di
produksi. Test ini yang menangkapnya lebih awal.
"""
import pytest

from qc_core.compliance.documents import DOCUMENT_TYPES, load_prompt_module


@pytest.mark.parametrize(
    "doc_type",
    ["ktp", "kk", "npwp", "cover_buku_tabungan", "mus_exception_confirmation"],
)
def test_load_prompt_module_bisa_diimpor(doc_type):
    module = load_prompt_module(doc_type)
    assert hasattr(module, "build_prompt")


@pytest.mark.parametrize("doc_type", sorted(DOCUMENT_TYPES))
def test_prompt_module_bernamespace(doc_type):
    name = DOCUMENT_TYPES[doc_type]["prompt_module"]
    assert name.startswith("qc_core.prompt."), (
        f"{doc_type} masih menunjuk {name!r} -- string ini tidak ikut ter-rewrite "
        "otomatis dan akan gagal saat runtime OCR"
    )
