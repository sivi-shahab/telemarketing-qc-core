"""``stamp_reason_speaker`` — pengucap evidence memakai label ASLI transkrip."""
from qc_core.compliance import reason_speaker as rs

SEGS = [
    {"speaker": "Agent", "timestamp": "00:01.00 -> 00:02.00",
     "text": "Tanggal lahir Ibu boleh dibantu? Sebelas Februari sembilan sembilan tujuh. Baik terima kasih."},
    {"speaker": "Customer", "timestamp": "00:03.00 -> 00:04.00", "text": "Iya betul sekali."},
]


def _ev(quote, reason, ticket="T_1"):
    return {"scorecard_result": [{"item_code": "SC_CL_23_1", "status": "BELUM_SESUAI",
                                  "reason": reason, "evidence": {"quote": quote, "ticket_id": ticket}}]}


def _patch(monkeypatch, segs=SEGS):
    monkeypatch.setattr(rs, "parse_transcript_pdf", lambda p: segs)
    monkeypatch.setattr(rs, "ticket_id_from_filename", lambda p: "T_1")


def test_label_asli_ditempel_sebelum_ekor(monkeypatch):
    _patch(monkeypatch)
    ev = _ev("Sebelas Februari sembilan sembilan tujuh. Baik terima kasih.",
             "Agent tidak memperoleh jawaban tanggal lahir pada verifikasi statik. - Evidence diambil dari recording utama.")
    out = rs.stamp_reason_speaker(ev, ["x.pdf"])["scorecard_result"][0]["reason"]
    assert out == ("Agent tidak memperoleh jawaban tanggal lahir pada verifikasi statik. "
                   "Kutipan evidence berlabel Agent pada transkrip asli. - Evidence diambil dari recording utama.")


def test_idempoten(monkeypatch):
    _patch(monkeypatch)
    ev = _ev("Sebelas Februari sembilan sembilan tujuh", "Alasan.")
    once = rs.stamp_reason_speaker(ev, ["x.pdf"])
    assert rs.stamp_reason_speaker(once, ["x.pdf"]) is once


def test_kutipan_tak_ditemukan_atau_kosong_dibiarkan(monkeypatch):
    _patch(monkeypatch)
    ev = _ev("kalimat yang tidak pernah diucapkan di rekaman ini", "Alasan.")
    assert rs.stamp_reason_speaker(ev, ["x.pdf"]) is ev
    ev2 = _ev(None, "Alasan.")
    assert rs.stamp_reason_speaker(ev2, ["x.pdf"]) is ev2


def test_dua_label_bila_kutipan_membentang(monkeypatch):
    _patch(monkeypatch)
    ev = _ev("Baik terima kasih ... Iya betul sekali", "Alasan.")
    out = rs.stamp_reason_speaker(ev, ["x.pdf"])["scorecard_result"][0]["reason"]
    assert "berlabel Agent dan Customer pada transkrip asli" in out
