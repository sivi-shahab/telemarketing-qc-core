"""``fix_speaker_roles`` — label Agent/Customer yang tertukar dibalik sebelum dinilai.

Label diarization hulu TIDAK selalu benar (31 dari 217 PDF korpus kalibrasi awal).
Ini bukan soal kerapian tampilan: verifikasi statik card holder menilai UCAPAN
NASABAH, jadi peran yang tertukar membuat jawaban nasabah tidak pernah terhitung.

Fungsi ini SANGAT KONSERVATIF dan sengaja begitu — membalik label yang sebenarnya
sudah benar sama merusaknya dengan membiarkan yang salah.
"""
from qc_core.compliance.call_ownership import fix_speaker_roles


def _seg(speaker, text):
    return {"speaker": speaker, "timestamp": "00:00.00 -> 00:01.00", "text": text}


def _peran(segments):
    return [s["speaker"] for s in segments]


# --------------------------------------------------------------------------
# jalur utama: perkenalan panggilan PERTAMA
# --------------------------------------------------------------------------

def test_perkenalan_di_sisi_nasabah_dibalik():
    segs = [
        _seg("Customer", "Halo selamat siang."),
        _seg("Agent", "Iya, siang."),
        _seg("Customer", "Perkenalkan saya Tamara dari Bank Mega Jakarta."),
    ]
    assert _peran(fix_speaker_roles(segs)) == ["Agent", "Customer", "Agent"]


def test_label_yang_sudah_benar_tidak_disentuh():
    segs = [
        _seg("Agent", "Perkenalkan saya Tamara dari Bank Mega Jakarta."),
        _seg("Customer", "Iya, gimana?"),
    ]
    assert fix_speaker_roles(segs) is segs   # non-destruktif: daftar ASLI dikembalikan


def test_label_netral_dilewati():
    """SPEAKER_0/1 tidak punya peran yang bisa tertukar."""
    segs = [
        _seg("SPEAKER_0", "Perkenalkan saya Tamara dari Bank Mega."),
        _seg("SPEAKER_1", "Iya."),
    ]
    assert fix_speaker_roles(segs) is segs


# --------------------------------------------------------------------------
# cadangan: PANGGILAN SUSULAN (18 September 2026)
# --------------------------------------------------------------------------

def test_panggilan_susulan_tanpa_perkenalan_baku_tetap_dibalik():
    """Tiket 010445fAVG [2] — celah yang ditemukan batch multi-rekaman.

    Panggilan susulan dibuka "dengan Tamara KEMBALI yang kemarin menghubungi",
    tanpa "dari Bank Mega" / "perkenalkan" / "nama saya". ``_ROLE_INTRO`` tidak
    mengenalinya, sehingga sebelum perbaikan ini fungsi menyerah dan label yang
    tertukar dibiarkan — padahal panggilan susulan justru bentuk yang paling
    mungkin dibuka begitu."""
    segs = [
        _seg("Agent", "Halo."),
        _seg("Customer", "Ya, halo, selamat pagi."),
        _seg("Agent", "Iya. He eh."),
        _seg("Customer", "Pak Lordi, dengan Tamara kembali yang kemarin menghubungi Bapak."),
        _seg("Agent", "Oh ya. Gimana?"),
        _seg("Customer", "Izin minta waktunya sebentar ya Pak Lordi."),
    ]
    hasil = _peran(fix_speaker_roles(segs))
    assert hasil[3] == "Agent" and hasil[5] == "Agent"   # skrip agent -> Agent
    assert hasil[1] == "Agent" or hasil[0] == "Customer"  # kedua label ikut bertukar


def test_frasa_skrip_di_sisi_agent_tidak_membalik_apa_pun():
    """Cadangan tunduk pada syarat yang sama: label yang sudah benar dibiarkan."""
    segs = [
        _seg("Agent", "Dengan Tamara kembali. Izin minta waktunya sebentar."),
        _seg("Customer", "Iya boleh."),
    ]
    assert fix_speaker_roles(segs) is segs


def test_seri_tidak_diputuskan():
    """Kedua pihak membawa penanda dengan jumlah sama -> tidak bisa dipastikan,
    jadi tidak disentuh sama sekali."""
    segs = [
        _seg("Agent", "Izin minta waktunya sebentar."),
        _seg("Customer", "Kami informasikan ya."),
    ]
    assert fix_speaker_roles(segs) is segs


def test_tanpa_penanda_apa_pun_dibiarkan():
    segs = [_seg("Agent", "Halo."), _seg("Customer", "Iya.")]
    assert fix_speaker_roles(segs) is segs


def test_daftar_kosong_aman():
    assert fix_speaker_roles([]) == []
