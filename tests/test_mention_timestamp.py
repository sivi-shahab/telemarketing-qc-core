"""Pagar timestamp penyebutan nasabah (28 Oktober 2026, tiket 080822Ha4J)."""
from qc_core.compliance.mention_timestamp import fix_mention_timestamp, fix_mention_timestamps

BLOK = {"speaker": "Agent", "timestamp": "00:01.18 -> 18:00.30",
        "text": "Untuk nama ibu kandung? Yosi Nara Ramaya. Terima kasih tadi Ibu."}
PENDEK_1 = {"speaker": "Agent", "timestamp": "02:52.46 -> 02:53.32", "text": "Nok Hasanah."}
PENDEK_2 = {"speaker": "Agent", "timestamp": "02:56.28 -> 02:57.48", "text": "Nok Hasanah."}


def test_timestamp_di_luar_blok_diganti_rentang_blok():
    m = {"value": "Yosi Nara Ramaya", "timestamp": "18:00.68 - 18:08.74", "source_file": "a.pdf"}
    out = fix_mention_timestamp(m, [BLOK])
    assert out["timestamp"] == "00:01.18 - 18:00.30"
    assert out["timestamp_llm"] == "18:00.68 - 18:08.74"
    assert out["timestamp_corrected"] is True


def test_timestamp_benar_dipertahankan():
    m = {"value": "Nok Hasanah", "timestamp": "02:56.28", "source_file": "a.pdf"}
    assert fix_mention_timestamp(m, [PENDEK_1, PENDEK_2]) == m


def test_pecahan_detik_terpotong_masih_dianggap_benar():
    m = {"value": "Nok Hasanah", "timestamp": "02:52", "source_file": "a.pdf"}
    assert fix_mention_timestamp(m, [PENDEK_1, PENDEK_2]) == m


def test_dua_penyebutan_identik_dipetakan_ke_segmen_masing_masing():
    m = {"value": "Nok Hasanah", "timestamp": "03:30.00", "source_file": "a.pdf"}
    out = fix_mention_timestamp(m, [PENDEK_1, PENDEK_2])
    assert out["timestamp"] == "02:56.28 - 02:57.48"      # terdekat


def test_nilai_tidak_ada_di_pdf_dibiarkan():
    m = {"value": "Bos Yula", "timestamp": "06:36.46", "source_file": "a.pdf"}
    assert fix_mention_timestamp(m, [BLOK, PENDEK_1]) == m


def test_idempoten():
    m = {"value": "Yosi Nara Ramaya", "timestamp": "18:00.68", "source_file": "a.pdf"}
    once = fix_mention_timestamp(m, [BLOK])
    assert fix_mention_timestamp(once, [BLOK]) == once


def test_evaluasi_tanpa_perubahan_dikembalikan_utuh():
    ev = {"card_holder_verification": [{"field": "nama_ibu_kandung", "extracted_mentions": [
        {"value": "Nok Hasanah", "timestamp": "02:52.46", "source_file": "a.pdf"}]}]}
    assert fix_mention_timestamps(ev, {"a.pdf": [PENDEK_1]}) is ev


def test_evaluasi_diperbaiki_per_berkas():
    ev = {"card_holder_verification": [{"field": "nama_ibu_kandung", "extracted_mentions": [
        {"value": "Yosi Nara Ramaya", "timestamp": "18:00.68 - 18:08.74", "source_file": "a.pdf"}]}]}
    out = fix_mention_timestamps(ev, {"a.pdf": [BLOK]})
    assert out["card_holder_verification"][0]["extracted_mentions"][0]["timestamp"] == "00:01.18 - 18:00.30"
    assert ev["card_holder_verification"][0]["extracted_mentions"][0]["timestamp"] == "18:00.68 - 18:08.74"
