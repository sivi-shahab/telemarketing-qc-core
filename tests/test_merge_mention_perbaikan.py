from datetime import datetime

from qc_core.compliance.parallel_pass import merge_parallel
from qc_core.compliance.static_similarity import similarity_nama_ibu


def _ev(mentions):
    return {
        "scorecard_result": [],
        "card_holder_verification": [
            {"field": "nama_ibu_kandung", "extracted_value": mentions[-1]["value"], "extracted_mentions": mentions}
        ],
    }


def _m(v, ts, f):
    return {"value": v, "timestamp": ts, "source_file": f}


def test_nama_ibu_rekaman_perbaikan_ikut_digabung():
    utama = _ev([_m("Nuraeni", "07:28", "a.pdf")])
    perbaikan = _ev([_m("Ramlah", "01:11.12", "b.pdf"), _m("Ramlah", "01:13.68", "b.pdf")])
    out, _, _ = merge_parallel(
        [utama, perbaikan], ["a.pdf", "b.pdf"], [datetime(2026, 10, 20, 11), datetime(2026, 10, 20, 12)], 0
    )
    ms = out["card_holder_verification"][0]["extracted_mentions"]
    assert [m["value"] for m in ms] == ["Nuraeni", "Ramlah", "Ramlah"]
    assert max(similarity_nama_ibu("RAMLAH", m["value"]) for m in ms) == 100


def test_penyebutan_sama_tidak_digandakan_dan_input_tidak_diubah():
    a = _ev([_m("Musih", "07:00", "a.pdf")])
    b = _ev([_m("Musih", "07:00", "a.pdf"), _m("Ningsih", "13:13", "a.pdf")])
    out, _, _ = merge_parallel([a, b], ["a.pdf", "b.pdf"], [None, None], 0)
    assert len(out["card_holder_verification"][0]["extracted_mentions"]) == 2
    assert len(a["card_holder_verification"][0]["extracted_mentions"]) == 1


def _row(field, value, match, mentions=()):
    return {"field": field, "extracted_value": value, "match": match, "extracted_mentions": list(mentions)}


def test_field_dinamis_ambil_baris_rekaman_terbaru_yang_terisi():
    a = {"scorecard_result": [], "card_holder_verification": [
        _row("no_telpon_terdaftar", "0811", "MISMATCH", [_m("0811", "01:00", "a.pdf")]),
        _row("alamat_rumah", "Jl A", "MATCH"),
    ]}
    b = {"scorecard_result": [], "card_holder_verification": [
        _row("no_telpon_terdaftar", "0822", "MATCH", [_m("0822", "00:40", "b.pdf")]),
        _row("alamat_rumah", None, "SKIPPED_NULL"),
    ]}
    out, _, _ = merge_parallel([a, b], ["a.pdf", "b.pdf"], [None, None], 0)
    rows = {r["field"]: r for r in out["card_holder_verification"]}
    assert rows["no_telpon_terdaftar"]["extracted_value"] == "0822"
    assert rows["no_telpon_terdaftar"]["match"] == "MATCH"
    assert [m["value"] for m in rows["no_telpon_terdaftar"]["extracted_mentions"]] == ["0811", "0822"]
    assert rows["alamat_rumah"]["extracted_value"] == "Jl A"


def test_field_statik_tetap_baris_utama_dengan_penyebutan_digabung():
    a = {"scorecard_result": [], "card_holder_verification": [
        _row("tanggal_lahir", "10 Desember 1992", "MISMATCH", [_m("10 Desember 1992", "06:00", "a.pdf")])]}
    b = {"scorecard_result": [], "card_holder_verification": [
        _row("tanggal_lahir", "10 Desember 1992", "MATCH", [_m("10 Desember 1992", "01:06", "b.pdf")])]}
    out, _, _ = merge_parallel([a, b], ["a.pdf", "b.pdf"], [None, None], 0)
    r = out["card_holder_verification"][0]
    assert r["match"] == "MISMATCH" and len(r["extracted_mentions"]) == 2
