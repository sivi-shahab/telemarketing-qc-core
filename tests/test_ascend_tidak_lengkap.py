"""Aturan "Ascend tidak lengkap" untuk nama ibu kandung (28 Oktober 2026, tiket 071043hfNF)."""
import pytest

from qc_core.compliance.static_similarity import (
    ascend_tidak_lengkap,
    best_static_match,
    similarity_nama,
    similarity_nama_ibu,
)


@pytest.mark.parametrize("ascend, ucapan, expected", [
    ("ENOK", "Nok Hasanah", 75.0),          # kasus nyata: Hasanah diabaikan, "nok" vs "enok" = 75 -> zona PENDING
    ("ANNA", "Anna Maria", 100.0),
    ("SUMI", "Sumi Rahayu", 100.0),
    ("UMI RODHIYAH", "Siti Umi Rodhiyah", 100.0),
    ("SRI", "Sri Wahyuni", 100.0),          # tanpa syarat jangkar: kata tambahan tetap diabaikan
])
def test_kata_tambahan_diabaikan_lalu_similarity_biasa(ascend, ucapan, expected):
    assert similarity_nama_ibu(ascend, ucapan) == expected


def test_enok_nok_hasanah_masuk_zona_pending():
    sc = similarity_nama_ibu("ENOK", "Nok Hasanah")
    assert 50 <= sc < 80
    assert ascend_tidak_lengkap("ENOK", "Nok Hasanah") is True


@pytest.mark.parametrize("ascend, ucapan", [
    ("ELLYWARTI", "Dewi Wati"),
    ("ENOK", "Enok"),                   # jumlah token sama: jalur skor biasa
    ("ENOK HASANAH", "Nok"),            # ucapan lebih PENDEK dari Ascend
])
def test_bukan_kasus_ascend_tidak_lengkap(ascend, ucapan):
    assert ascend_tidak_lengkap(ascend, ucapan) is False
    assert similarity_nama_ibu(ascend, ucapan) == similarity_nama(ascend, ucapan)


def test_efek_samping_salah_dengar_naik_ke_zona_pending():
    # Konsekuensi yang diketahui: jendela satu kata membuat salah dengar ASR yang dulu
    # MISMATCH (31) naik ke zona abu-abu (PENDING + KK). Sengaja, atas arahan user.
    assert similarity_nama("FARIDA", "Kharidja Kuncoro") == 31.0
    assert similarity_nama_ibu("FARIDA", "Kharidja Kuncoro") == 62.0
    assert similarity_nama_ibu("ELLYWARTI", "Dewi Wati") < 50


def test_hanya_menaikkan_nilai():
    for a, b in [("TARSIKEM", "Tarsih Kem"), ("T SIMONO", "Tirto Simono"),
                 ("SESKAFIEN RUMENGAN", "SAS KASIEN RUNGGAN")]:
        assert similarity_nama_ibu(a, b) >= similarity_nama(a, b)


def test_best_static_match_memilih_penyebutan_lengkap():
    assert best_static_match("nama_ibu_kandung", "ENOK", ["Nok Hasanah"]) == ("Nok Hasanah", 75.0)


# --- Aturan ALIAS: "XX ALIAS YY" di Ascend, menyebut salah satu nama sudah sah ---
from qc_core.compliance.static_similarity import ascend_alias_parts, best_alias_part


def test_alias_dipecah():
    assert ascend_alias_parts("HO SIU LANG ALIAS LANNY") == ["HO SIU LANG", "LANNY"]
    assert ascend_alias_parts("ENOK") == []
    assert ascend_alias_parts("ALIAS LANNY") == []          # sisi kosong: bukan alias


@pytest.mark.parametrize("ucapan", ["Lanny", "Ho Siu Lang", "ho siu lang"])
def test_menyebut_salah_satu_nama_alias_cocok(ucapan):
    assert similarity_nama_ibu("HO SIU LANG ALIAS LANNY", ucapan) >= 80


def test_alias_tidak_meloloskan_nama_lain():
    assert similarity_nama_ibu("HO SIU LANG ALIAS LANNY", "Musila") < 50
    assert similarity_nama_ibu("HO SIU LANG ALIAS LANNY", "Bos Yula") < 50


def test_alias_hanya_menaikkan_nilai():
    ref = "HO SIU LANG ALIAS LANNY"
    for u in ["Lanny", "Musila", "Ho Siu Lang Lanny"]:
        assert similarity_nama_ibu(ref, u) >= similarity_nama(ref, u)


def test_acuan_tanpa_alias_tidak_berubah():
    assert best_alias_part("ENOK", "Enok") is None


# --- Round-up ke ambang MATCH (9 Nov 2026) ----------------------------------
from qc_core.compliance.static_similarity import roundup_to_threshold


@pytest.mark.parametrize("score, threshold, expected", [
    (78.0, 80.0, 80.0),
    (79.0, 80.0, 80.0),
    (77.0, 80.0, 77.0),     # di luar jendela
    (80.0, 80.0, 80.0),
    (88.0, 90.0, 90.0),     # ambang dinamis (aturan lama nama ibu)
    (87.0, 90.0, 87.0),
    (None, 80.0, None),
])
def test_roundup_to_threshold(score, threshold, expected):
    assert roundup_to_threshold(score, threshold) == expected


def _eval(ref, ucapan, llm_sim=70):
    return {"static_rules_version": 2, "card_holder_verification": [{
        "field": "nama_ibu_kandung", "reference_value": ref, "extracted_value": ucapan,
        "extracted_mentions": [{"timestamp": "00:01.00", "value": ucapan}],
        "similarity_percent": llm_sim, "match": "MISMATCH", "reason": "x"}]}


def test_normalize_membulatkan_78_ke_80_dan_mencatat_asalnya():
    from qc_core.compliance.error_codes import normalize_static_verification
    # "sumarni" vs "sumarno": 1 substitusi dari 7 huruf = 85,7 -> pakai pasangan 78,x di bawah
    ref, ucapan = "ABCDEFGHI", "ABCDEFGHX"   # 8/9 = 88,9 (bukan kasus); cari pasangan 78-79 langsung
    from qc_core.compliance.static_similarity import similarity_nama_ibu
    for a, b in [("ABCDEFGHI", "ABCDEFXYI"), ("ABCDEFGHIJ", "ABCDEFGXYZ"), ("ABCDEFGHIJKLM", "ABCDEFGHIJXYZ")]:
        if similarity_nama_ibu(a, b) in (78.0, 79.0):
            ref, ucapan = a, b
            break
    raw = similarity_nama_ibu(ref, ucapan)
    assert raw in (78.0, 79.0)
    row = normalize_static_verification(_eval(ref, ucapan))["card_holder_verification"][0]
    assert row["similarity_percent"] == 80.0
    assert row["similarity_roundup_from"] == raw
    assert row["match"] == "MATCH"
    assert "dibulatkan" in row["reason"]
