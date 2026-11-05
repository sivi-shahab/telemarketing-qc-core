"""Kutipan evidence tidak boleh dikarang (28 Oktober 2026): pemeriksa keberadaan kutipan di transkrip mentah."""
from qc_core.compliance.evidence_check import apply_evidence_check_segments, haystack, quote_pieces, support

SEGS = [
    {"speaker": "Agent", "timestamp": "12:29.38 -> 12:56.80",
     "text": "Informasi lebih lanjut dapat menghubungi Mega Call Center kita di 080454 1020. Sebelum kami proses lebih "
             "lanjut dengan ini Ibu memberikan persetujuan atas data pribadi yang diberikan kepada Bank Mega."},
    {"speaker": "Customer", "timestamp": "03:15.42 -> 03:16.42", "text": "Tanggal 23 Desember."},
    {"speaker": "Agent", "timestamp": "03:17.00 -> 03:19.00", "text": "Baik, terima kasih Pak."},
    {"speaker": "Customer", "timestamp": "03:20.24 -> 03:21.94", "text": "Tahun 1992."},
]
KARANGAN = "Pada saat proses analisa apabila analis kami memerlukan dokumen tambahan, mohon kesediaan Bapak/Ibu untuk melengkapinya."


def _ev(status, quote, code="SC_RI_31"):
    return {"scorecard_result": [{"item_code": code, "status": status, "weight": 3, "item_score": 3 if status == "SESUAI" else 0,
                                  "requirement": "Agent mengonfirmasi kesediaan melengkapi dokumen.", "reason": "r",
                                  "evidence": {"timestamp": "12:29", "quote": quote, "ticket_id": "T1"}}]}


def test_kutipan_nyata_terdukung_penuh():
    hay = haystack(SEGS)
    assert support("Informasi lebih lanjut dapat menghubungi Mega Call Center kita di 080454 1020.", hay) == 1.0


def test_kutipan_karangan_tidak_terdukung():
    assert support(KARANGAN, haystack(SEGS)) == 0.0


def test_kutipan_sambungan_dua_segmen_terpisah_tetap_terdukung():
    # "Tanggal 23 Desember. Tahun 1992." = dua segmen dengan ucapan agent di antaranya (tiket Cashline 5965eafd)
    assert support("Tanggal 23 Desember. Tahun 1992.", haystack(SEGS)) == 1.0


def test_label_timestamp_dan_pemisah_dibuang():
    assert quote_pieces("[Agent] [03:15.42 - 03:16.42] Tanggal 23 Desember | Customer: Tahun 1992") == [["tanggal", "23", "desember"], ["tahun", "1992"]]


def test_kutipan_didominasi_angka_tidak_diperiksa():
    assert support("kosong delapan empat dua delapan satu dua tiga", haystack(SEGS)) is None


def test_sesuai_dengan_kutipan_karangan_diturunkan():
    out = apply_evidence_check_segments(_ev("SESUAI", KARANGAN), SEGS)
    row = out["scorecard_result"][0]
    assert row["status"] == "BELUM_SESUAI" and row["item_score"] == 0
    assert row["evidence"]["quote"] is None and row["evidence_check"]["quote_llm"] == KARANGAN
    assert row["evidence_check"]["tindakan"] == "diturunkan_ke_belum_sesuai" and "SC_" not in row["reason"]
    assert out["evidence_check"]["diturunkan"] == ["SC_RI_31"]


def test_belum_sesuai_dengan_kutipan_karangan_hanya_ditandai():
    out = apply_evidence_check_segments(_ev("BELUM_SESUAI", KARANGAN), SEGS)
    row = out["scorecard_result"][0]
    assert row["status"] == "BELUM_SESUAI" and row["evidence"]["quote"] == KARANGAN
    assert row["evidence_check"]["tindakan"] == "ditandai" and out["evidence_check"]["ditandai"] == ["SC_RI_31"]


def test_kutipan_nyata_tidak_mengubah_apa_pun():
    ev = _ev("SESUAI", "Sebelum kami proses lebih lanjut dengan ini Ibu memberikan persetujuan atas data pribadi")
    assert apply_evidence_check_segments(ev, SEGS) is ev


def test_tidak_dinilai_dan_tanpa_kutipan_dilewati():
    assert apply_evidence_check_segments(_ev("TIDAK_DINILAI", KARANGAN), SEGS)["scorecard_result"][0]["status"] == "TIDAK_DINILAI"
    ev = _ev("SESUAI", None)
    assert apply_evidence_check_segments(ev, SEGS) is ev


def test_tanpa_transkrip_tidak_berbuat_apa_pun(monkeypatch):
    ev = _ev("SESUAI", KARANGAN)
    assert apply_evidence_check_segments(ev, []) is ev


def test_sakelar_darurat(monkeypatch):
    from qc_core.compliance import evidence_check
    monkeypatch.setenv("EVIDENCE_CHECK", "off")
    ev = _ev("SESUAI", KARANGAN)
    assert evidence_check.apply_evidence_check(ev, ["x.pdf"]) is ev
