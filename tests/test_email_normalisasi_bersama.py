"""Normalisasi email dipakai bersama Cashline & NTB (feedback QC Bank Mega 12 Okt 2026)."""
from qc_core.compliance.spoken_normalize import normalize_email
from qc_core.compliance.error_codes import normalize_dynamic_verification


def test_email_eja_dinormalkan():
    assert normalize_email("DHI LAH titik AS tujuh at gmail dot com") == "dhilah.as7@gmail.com"
    assert normalize_email("erdiwansya lima at gmail dot com") == "erdiwansya5@gmail.com"
    assert normalize_email("hindarto hindarto enam tujuh lima tiga tujuh at gmail dot com") == "hindartohindarto67537@gmail.com"
    assert normalize_email("john double nol at gmail dot com") == "john00@gmail.com"
    assert normalize_email("kentung r-i-i z-a ky at gmail dot com") == "kentungriizaky@gmail.com"
    assert normalize_email("budi-s@gmail.com") == "budi-s@gmail.com"
    assert normalize_email(None) == ""


def _ev(match, extracted, status24="BELUM_SESUAI"):
    rows = [
        {"field": "alamat_email_terdaftar", "reference_value": "DHILAH.AS7@GMAIL.COM",
         "extracted_value": extracted, "match": match, "similarity_percent": 40},
        {"field": "no_telpon_terdaftar", "reference_value": "081", "extracted_value": "081", "match": "MATCH"},
    ]
    return {"card_holder_verification": rows,
            "scorecard_result": [{"item_code": "SC_CL_24", "status": status24, "weight": 5, "item_score": 0}]}


def test_cashline_email_eja_jadi_match_dan_sc_cl_24_pulih():
    out = normalize_dynamic_verification(_ev("MISMATCH", "DHI LAH titik AS tujuh at gmail dot com"))
    row = out["card_holder_verification"][0]
    assert row["match"] == "MATCH" and row["extracted_value"] == "dhilah.as7@gmail.com"
    assert out["scorecard_result"][0]["status"] == "SESUAI"


def test_cashline_email_memang_beda_tetap_mismatch():
    out = normalize_dynamic_verification(_ev("MISMATCH", "andi at gmail dot com"))
    assert out["card_holder_verification"][0]["match"] == "MISMATCH"
    assert out["scorecard_result"][0]["status"] == "BELUM_SESUAI"


def test_email_dinilai_satu_entitas_cashline():
    from qc_core.compliance.error_codes import _email_part_similarity
    assert round(_email_part_similarity("mayanglucu23@gmail.com", "mayanglucu23@yahoo.com"), 1) == 77.3
