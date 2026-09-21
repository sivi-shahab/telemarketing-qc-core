"""Nama on-air wajib dipakai saat perkenalan (7 September 2026, konfirmasi Bank Mega).

``agent_name_verdict()`` diuji di sini bukan lagi untuk menimpa skor SC_CL_2 — sejak
18 September 2026 (tiket 020455CL3A) itemnya dinilai LLM sepenuhnya, dibantu blok
referensi NAME ONLINE di prompt (``apply_agent_name_verdict`` dihapus). Fungsi ini
tetap dipakai untuk info diagnostik (``agent_name_check``) dan oleh
``filter_calls_by_agent`` (kepemilikan panggilan) — jadi akurasinya tetap penting.

Yang dijaga tes ini adalah dua arah kesalahan yang sama mahalnya: menjatuhkan agent yang
sebenarnya menyebut namanya (detektor jangkar terbukti meleset di 37 dari 111 rekaman
seed 7 September), dan meloloskan yang memakai nama asli atau nama orang lain.
"""
from qc_core.compliance.call_ownership import agent_name_verdict

ROSTER = ("ANDINI", "AUREL", "NISA", "IKA", "RAIZEL", "VADLI")


def _teks(*kalimat):
    return {f"rek{i}.pdf": k for i, k in enumerate(kalimat)}


# --------------------------------------------------------------------------
# Cocok
# --------------------------------------------------------------------------

def test_perkenalan_dengan_nama_on_air_lolos():
    v = agent_name_verdict(_teks("Halo, saya Andini dari Bank Mega"), "ANDINI", ROSTER)
    assert v["match"] is True


def test_detektor_meleset_tetapi_nama_ada_di_transkrip():
    """Kesempatan kedua. Jangkar sering menangkap kata biasa — "PUSPA" pernah terbaca
    ['kredit','notifikasi','diskon'] — dan tanpa cadangan ini 37 rekaman dijatuhkan
    padahal namanya jelas terucap."""
    v = agent_name_verdict(
        _teks("Terima kasih, nanti notifikasi dari Bank Mega. Dengan Puspa ya Bu."),
        "PUSPA", ROSTER)
    assert v["match"] is True


def test_cukup_disebut_di_salah_satu_rekaman():
    """Aturan KB kategori Greeting: terpenuhi di panggilan mana pun sudah cukup."""
    v = agent_name_verdict(
        _teks("Halo Pak, dari Bank Mega ya", "Iya Pak, dengan Aurel dari Bank Mega"),
        "AUREL", ROSTER)
    assert v["match"] is True


def test_salah_dengar_masih_diterima_untuk_nama_panjang():
    v = agent_name_verdict(_teks("saya Andiny dari Bank Mega"), "ANDINI", ROSTER)
    assert v["match"] is True


# --------------------------------------------------------------------------
# Gagal
# --------------------------------------------------------------------------

def test_memakai_nama_asli_digagalkan():
    """Kasus 0104090bPC: MUHAMMAD ZIDAN menyebut "Zidan", on-air RAIZEL."""
    v = agent_name_verdict(_teks("perkenalkan Ibu dengan Zidan dari Bank Mega"),
                           "RAIZEL", ROSTER, "MUHAMMAD ZIDAN REGI PERMANA")
    assert v["match"] is False
    assert "NAMA ASLI" in v["reason"] and "Zidan" in v["reason"]


def test_nama_asli_sebagai_potongan_kata_juga_digagalkan():
    """Kasus 2704044zjw: LULU SABERINA menyebut "Erina", on-air SABRINA."""
    v = agent_name_verdict(_teks("Pak, dengan Erina kembali dari Bank Mega"),
                           "SABRINA", ROSTER, "LULU SABERINA")
    assert v["match"] is False
    assert "NAMA ASLI" in v["reason"]


def test_memakai_nama_on_air_orang_lain_disebut_tegas():
    v = agent_name_verdict(_teks("izin waktunya dengan Nisa dari Bank Mega"),
                           "KIA", ROSTER, "NURYULIASARI")
    assert v["match"] is False
    assert "agent LAIN" in v["reason"] and "Nisa" in v["reason"]


def test_kebisingan_detektor_tidak_pernah_dikutip():
    """QC yang membaca "agent memperkenalkan diri sebagai 'mematikan'" akan berhenti
    mempercayai laporannya."""
    v = agent_name_verdict(_teks("nanti saya bantu mematikan dari Bank Mega ya"),
                           "TITIN", ROSTER, "KHATARINE")
    assert v["match"] is False
    assert "mematikan" not in v["reason"]


def test_nama_pendek_tidak_dicocokkan_fuzzy():
    """"Oke"/"jika" 67% terhadap "IKE" — fuzzy pada nama sependek itu meloloskan dan
    menjatuhkan sama serampangannya."""
    v = agent_name_verdict(_teks("Oke Pak, jika berkenan, dari Bank Mega"), "IKE", ROSTER)
    assert v["match"] is False


def test_vokatif_sisipan_sebelum_dari_tidak_menyembunyikan_nama():
    """Tiket 020455CL3A: "...saya Eveline, Ibu dari Bank Mega..." — vokatif "Ibu"
    tersisip ANTARA nama dan "dari" dulu membuat pemangkasan mundur berhenti di "Ibu"
    (stopword) sebelum sampai ke "Eveline", sehingga detected=[] padahal nama jelas
    terucap. "Eveline" tidak cocok NAME ONLINE "LINA" manapun di roster."""
    v = agent_name_verdict(
        _teks("Baik. Ibu, ee, izin saya Eveline, Ibu dari Bank Mega Jakarta, "
              "izin minta waktunya sebentar boleh Ibu?"),
        "LINA", ROSTER)
    assert "Eveline" in v["detected"]
    assert v["match"] is False


def test_disfluensi_dari_dari_tidak_tertangkap_sebagai_nama():
    """Tiket 020455CL3A (kalimat lain di panggilan yang sama): disfluensi ASR
    "...fasilitas dari, dari Bank Mega..." dulu membuat kata "dari" itu sendiri
    tertangkap sebagai kandidat nama (persis kata kunci jangkarnya sendiri)."""
    v = agent_name_verdict(
        _teks("Bapak bisa menikmati fasilitas dari, dari Bank Mega untuk kebutuhan "
              "finansial."),
        "LINA", ROSTER)
    assert "dari" not in v["detected"]


# --------------------------------------------------------------------------
# Tidak dinilai
# --------------------------------------------------------------------------

def test_agent_tidak_ada_di_roster_tidak_dihukum():
    v = agent_name_verdict(_teks("saya Rina dari Bank Mega"), "", ROSTER)
    assert v["match"] is None
