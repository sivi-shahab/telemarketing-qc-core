"""Kewajiban dokumen TIDAK dicabut oleh pelanggaran lain (30 Oktober 2026).

Pembebasan 3 September 2026 dibalik atas arahan user: nama ibu kandung di zona abu-abu
tetap meminta KK walau ada item non-tolerable lain yang gagal.
"""
from qc_core.compliance.documents import (
    card_holder_doc_requirements,
    doc_requirements_waived,
    required_doc_types,
)
from qc_core.compliance.error_codes import apply_static_document_status


def _eval(sim, *, other_failure=True, field="nama_ibu_kandung"):
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


def test_pelanggaran_lain_tidak_mencabut_kewajiban_dokumen():
    ev = _eval(57.0)
    assert not doc_requirements_waived(ev)
    assert required_doc_types(ev) == ["kk"]


def test_zona_abu_abu_pending_walau_ada_pelanggaran_lain():
    out = apply_static_document_status(_eval(57.0), set(), False)
    row = out["card_holder_verification"][0]
    assert row["match"] == "PENDING"
    assert [r["doc_type"] for r in card_holder_doc_requirements(out)] == ["kk"]


def test_tanpa_pelanggaran_lain_sama_saja():
    out = apply_static_document_status(_eval(57.0, other_failure=False), set(), False)
    assert out["card_holder_verification"][0]["match"] == "PENDING"


def test_baris_di_luar_zona_abu_abu_tidak_disentuh():
    ev = _eval(95.0)
    out = apply_static_document_status(ev, set(), False)
    assert out["card_holder_verification"][0]["reason"] == \
        ev["card_holder_verification"][0]["reason"]
