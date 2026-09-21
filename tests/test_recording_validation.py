"""Validasi PDF + pemilihan recording utama untuk tiket multi-rekaman (18 September 2026).

Yang dijaga tes ini adalah dua arah kesalahan yang sama mahalnya: memilih rekaman yang
SALAH sebagai acuan penilaian (seluruh Final Konfirmasi & Legal Statement jatuh padahal
agent memenuhinya di rekaman lain), dan membuang rekaman yang sebenarnya sah.

Angka & kalimat di bawah disalin dari batch sampel 18 September 2026 (4 tiket / 10 PDF)
supaya tes ini tetap berbicara tentang bentuk data yang nyata, bukan bentuk karangan.
"""
from datetime import datetime

import pytest

from qc_core.compliance import recording_validation as RV
from qc_core.prompt.recording_type import TAG_DITUNDA, TAG_LAINNYA, TAG_PEMBATALAN


# --------------------------------------------------------------------------
# penanda penutup (Legal Statement)
# --------------------------------------------------------------------------

def test_pertanyaan_persetujuan_baku_dikenali():
    assert RV.punya_penanda_penutup("Iya, kurang jelas. Apakah Ibu setuju?")


def test_setuju_berdampingan_nama_produk_dikenali():
    """Bentuk yang dipakai 010445fAVG [1]: persetujuan menyebut produknya."""
    assert RV.punya_penanda_penutup(
        "Bapak sudah mengerti dan memahami penjelasan Mega Ultima Shield dan setuju "
        "pengaktifan pada Mega Cashline Bapak."
    )


def test_setuju_urusan_dokumen_bukan_penutup():
    """150125GJW6 [3]: "Ya, setuju" untuk LAMPIRAN DOKUMEN, bukan Legal Statement.

    Inilah sebabnya kata "setuju" tidak boleh dipakai sendirian sebagai penanda."""
    assert not RV.punya_penanda_penutup(
        "Ini nggak apa-apa Bu dilampirkan tadi yang sudah Ibu kirimkan ya kayak gitu. "
        "Ya, setuju. Baik, terima kasih ya Bu ya. Ini Erina bantu lanjutkan prosesnya."
    )


def test_setuju_tanda_tangan_ulang_link_bukan_penutup():
    """190324tCXV [2]: agent lupa minta NPWP, "setuju" untuk tanda tangan ulang link."""
    assert not RV.punya_penanda_penutup(
        "Dengan Evelyn kembali. Tadi mohon maaf sempat lupa nomor NPWP-nya Bapak. "
        "Ditandatangan kembali setuju ya? Setuju. Baik Evelyn kirimkan lagi link-nya ya."
    )


def test_teks_kosong_bukan_penutup():
    assert not RV.punya_penanda_penutup("")


# --------------------------------------------------------------------------
# alasan pembuangan (deskriptif)
# --------------------------------------------------------------------------

def test_penundaan_oleh_customer_dilabeli_tepat():
    tag, alasan = RV._alasan_tolak(
        "Bentar Mbak ya, nggak bisa kalau pagi-pagi gini Mbak, sore kali ya. "
        "Nanti diulang Mbak ya ya", 23.0, 10)
    assert tag == TAG_DITUNDA and "menunda" in alasan.lower()


def test_pembatalan_menang_atas_penundaan():
    """Pembatalan lebih berat daripada penundaan — diperiksa lebih dulu."""
    tag, _ = RV._alasan_tolak("Saya tidak jadi Bu, batal saja. Nanti diulang.", 60.0, 12)
    assert tag == TAG_PEMBATALAN


def test_urusan_dokumen_singkat_dilabeli_lainnya():
    tag, alasan = RV._alasan_tolak(
        "Ibu tadi kan sudah diterima ya untuk dokumennya cuma ini kan Ibu mengirimkan "
        "dua foto ya.", 76.0, 17)
    assert tag == TAG_LAINNYA and "dokumen" in alasan.lower()


def test_tanpa_penanda_apa_pun_jatuh_ke_alasan_umum():
    tag, alasan = RV._alasan_tolak("Halo. Iya. Baik. Terima kasih.", 30.0, 8)
    assert tag == TAG_LAINNYA and "Legal Statement" in alasan


# --------------------------------------------------------------------------
# pemilihan recording utama
# --------------------------------------------------------------------------

def _lap(nama, jam, *, durasi=1200.0, segmen=120, penutup=True, ok=True, teks=None):
    """Satu baris laporan ``periksa_berkas`` buatan.

    ``teks`` bawaannya dibuat UNIK per berkas — kalau tidak, ``_buang_duplikat`` akan
    menggugurkannya sebagai rekaman kembar dan tes jadi menguji hal yang lain."""
    return {
        "path": f"/t/{nama}", "filename": nama,
        "timestamp": datetime(2026, 9, 3, jam, 0, 0),
        "durasi": durasi, "n_segmen": segmen, "teks": teks or f"isi percakapan {nama}",
        "teknis_ok": ok, "masalah": [] if ok else ["rusak"], "penutup": penutup,
    }


def _jalankan(monkeypatch, laporan):
    """Jalankan ``pilih_recording_utama`` atas laporan buatan (PDF tidak disentuh)."""
    peta = {r["path"]: r for r in laporan}
    monkeypatch.setattr(RV, "periksa_berkas", lambda p, t=None: peta[p])
    return RV.pilih_recording_utama([r["path"] for r in laporan], expected_ticket_id="T1")


def test_satu_pdf_tidak_pernah_divalidasi(monkeypatch):
    """JARING PENGAMAN 1 — yang mengunci janji "50 tiket single-recording tidak bergeser".

    Berkas satu-satunya jadi utama WALAU laporannya gagal total."""
    def _jangan_dipanggil(*a, **k):
        raise AssertionError("periksa_berkas tidak boleh dipanggil untuk tiket 1 PDF")
    monkeypatch.setattr(RV, "periksa_berkas", _jangan_dipanggil)
    h = RV.pilih_recording_utama(["/t/satu.pdf"], expected_ticket_id="T1")
    assert h["utama"] == "/t/satu.pdf"
    assert h["dibuang"] == [] and h["fallback"] == "tiket satu rekaman"


def test_tertua_dari_yang_lolos_bukan_tertua_mutlak(monkeypatch):
    """Kasus 0308549YQ4 — inti seluruh rancangan ini.

    Yang tertua (08:00) adalah panggilan yang verifikasinya gagal lalu ditunda agent:
    substantif tetapi TANPA penutup. Yang benar adalah rekaman 13:00 yang tuntas."""
    h = _jalankan(monkeypatch, [
        _lap("pagi.pdf", 8, durasi=360.0, segmen=41, penutup=False),
        _lap("siang.pdf", 13, durasi=1397.0, segmen=121, penutup=True),
    ])
    assert h["utama"] == "/t/siang.pdf"
    assert [d["filename"] for d in h["dibuang"]] == ["pagi.pdf"]


def test_dua_rekaman_lengkap_ambil_yang_tertua(monkeypatch):
    """Kasus 010445fAVG — keduanya berpenutup penuh; yang tertua menang, yang muda
    menjadi pendamping (bukan dibuang)."""
    h = _jalankan(monkeypatch, [
        _lap("kedua.pdf", 9), _lap("pertama.pdf", 8),
    ])
    assert h["utama"] == "/t/pertama.pdf"
    assert h["pendamping"] == ["/t/kedua.pdf"]
    assert h["dibuang"] == []


def test_nol_kandidat_mengembalikan_semua(monkeypatch):
    """JARING PENGAMAN 2 — lebih baik menilai berlebih daripada evaluasi kosong."""
    h = _jalankan(monkeypatch, [
        _lap("a.pdf", 9, penutup=False), _lap("b.pdf", 8, penutup=False),
    ])
    assert h["utama"] == "/t/b.pdf"          # tertua
    assert h["pendamping"] == ["/t/a.pdf"]
    assert h["dibuang"] == []                 # tidak ada yang dicoret saat fallback
    assert h["fallback"] == "tidak ada rekaman yang lolos validasi"


def test_gagal_teknis_tidak_bisa_jadi_utama(monkeypatch):
    h = _jalankan(monkeypatch, [
        _lap("rusak.pdf", 8, ok=False), _lap("sehat.pdf", 9),
    ])
    assert h["utama"] == "/t/sehat.pdf"
    assert [d["filename"] for d in h["dibuang"]] == ["rusak.pdf"]


def test_terlalu_pendek_tidak_bisa_jadi_utama(monkeypatch):
    """Penggalan berpenutup pun tetap gugur bila di bawah lantai substansi."""
    h = _jalankan(monkeypatch, [
        _lap("penggalan.pdf", 8, durasi=27.0, segmen=9),
        _lap("penuh.pdf", 9),
    ])
    assert h["utama"] == "/t/penuh.pdf"


def test_tanpa_timestamp_tidak_pernah_menang_tertua(monkeypatch):
    """Berkas tanpa timestamp gugur di gerbang teknis 1.4, jadi tidak ikut diperebutkan."""
    tanpa = _lap("tanpa.pdf", 8, ok=False)
    tanpa["timestamp"] = None
    h = _jalankan(monkeypatch, [tanpa, _lap("ada.pdf", 9)])
    assert h["utama"] == "/t/ada.pdf"


def test_duplikat_digugurkan_yang_pertama_bertahan():
    """Rekaman kembar menggandakan bobot evidence yang sama."""
    a = _lap("a.pdf", 8, teks="sama persis")
    b = _lap("b.pdf", 9, teks="sama persis")
    hasil = RV._buang_duplikat([a, b])
    assert hasil[0]["teknis_ok"] is True
    assert hasil[1]["teknis_ok"] is False
    assert "Duplikat" in hasil[1]["masalah"][-1]


def test_daftar_kosong_aman():
    h = RV.pilih_recording_utama([])
    assert h["utama"] is None and h["dibuang"] == []


def test_tags_by_file_menandai_utama_dan_buangan():
    hasil = {
        "utama": "/t/u.pdf", "pendamping": ["/t/p.pdf"],
        "dibuang": [{"path": "/t/x.pdf", "filename": "x.pdf",
                     "tag": TAG_DITUNDA, "tag_label": "Ditunda", "reason": "sebab"}],
    }
    peta = RV.tags_by_file(hasil)
    assert peta["u.pdf"]["tag"] == "recording_utama"
    assert peta["p.pdf"]["tag"] == "recording_perbaikan"   # pendamping, bukan utama
    assert peta["x.pdf"]["tag"] == TAG_DITUNDA and peta["x.pdf"]["reason"] == "sebab"
