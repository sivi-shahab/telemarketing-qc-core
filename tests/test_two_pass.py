"""Unit test penilaian dua tahap (Fase #3).

Fokusnya pada aturan yang mudah salah dan mahal akibatnya: tahap 2 tidak boleh
memperburuk, item wajib tetap diperiksa tapi tidak boleh menurunkan apa pun, item
kritis yang tertolong harus mengembalikan irisan penaltinya, dan gerbang SLA harus
menghitung dari rekaman TERBARU.
"""
from datetime import datetime

from qc_core.compliance import two_pass as T


def _row(code, status, weight=1.0, category="Penjelasan Mega Cashline", **extra):
    return {"item_code": code, "status": status, "weight": weight, "category": category,
            "item_score": weight if status == "SESUAI" else 0, **extra}


def _eval(rows, maximum_score=108.75, critical=None):
    ev = {"scorecard_result": rows, "maximum_score": maximum_score,
          "passing_grade": 97.88, "ai_score_verification": 0}
    if critical is not None:
        ev["critical_compliance_check"] = {"status": "FAIL", "checked_items": critical}
        ev["ai_score_critical_compliance_check"] = -(maximum_score / 4) * sum(
            1 for c in critical if c["status"] == "FAIL")
    return ev


# --------------------------------------------------------------------------
# items_needing_pass2
# --------------------------------------------------------------------------

def test_item_gagal_dan_pending_dicari_ulang():
    ev = _eval([_row("SC_CL_8", "BELUM_SESUAI"), _row("SC_CL_9", "PENDING"),
                _row("SC_CL_10", "SESUAI")])
    assert T.items_needing_pass2(ev) == ["SC_CL_8", "SC_CL_9"]


def test_item_wajib_ikut_walau_sudah_sesuai():
    """SC_CL_25..32 + SC_CL_37 selalu diperiksa ulang di rekaman perbaikan (aturan #6)."""
    ev = _eval([_row("SC_CL_28", "SESUAI"), _row("SC_CL_37", "SESUAI"),
                _row("SC_CL_10", "SESUAI")])
    assert T.items_needing_pass2(ev) == ["SC_CL_28", "SC_CL_37"]


def test_tidak_dinilai_tidak_pernah_dicari_ulang():
    """Produknya memang tidak diambil — termasuk bila item itu ada di daftar wajib."""
    ev = _eval([_row("SC_CL_38", "TIDAK_DINILAI"), _row("SC_CL_28", "TIDAK_DINILAI")])
    assert T.items_needing_pass2(ev) == []


# --------------------------------------------------------------------------
# merge_pass2
# --------------------------------------------------------------------------

def test_item_gagal_yang_ketemu_jadi_sesuai_penuh():
    base = _eval([_row("SC_CL_8", "BELUM_SESUAI", 4)])
    p2 = _eval([_row("SC_CL_8", "SESUAI", 4, evidence={"quote": "biaya provisi dua persen",
                                                       "ticket_id": "T_2.pdf"},
                     evidence_source="penjelasan", reason="dijelaskan ulang")])
    merged, rincian = T.merge_pass2(base, p2, ["SC_CL_8"])
    row = merged["scorecard_result"][0]
    assert row["status"] == "SESUAI"
    assert row["item_score"] == 4          # bobot penuh kembali
    assert row["evidence_source"] == "penjelasan"
    assert row["pass2"] is True
    assert rincian == [{"item_code": "SC_CL_8", "evidence_source": "penjelasan",
                        "file": "T_2.pdf"}]


def test_lolos_lewat_recap_ditandai_fallback():
    base = _eval([_row("SC_CL_16", "BELUM_SESUAI", 1.5)])
    p2 = _eval([_row("SC_CL_16", "SESUAI", 1.5,
                     evidence={"quote": "tercetak tanggal enam belas", "ticket_id": "T_2.pdf"},
                     evidence_source="fallback_final_konfirmasi")])
    merged, rincian = T.merge_pass2(base, p2, ["SC_CL_16"])
    assert merged["scorecard_result"][0]["evidence_source"] == "fallback_final_konfirmasi"
    assert rincian[0]["evidence_source"] == "fallback_final_konfirmasi"


def test_tahap_dua_tidak_pernah_memperburuk():
    """Rekaman perbaikan 4 menit tidak boleh menjatuhkan item yang benar di utama."""
    base = _eval([_row("SC_CL_11", "SESUAI", 5)])
    p2 = _eval([_row("SC_CL_11", "BELUM_SESUAI", 5)])
    merged, rincian = T.merge_pass2(base, p2, ["SC_CL_11"])
    assert merged["scorecard_result"][0]["status"] == "SESUAI"
    assert rincian == []


def test_item_di_luar_daftar_diabaikan():
    base = _eval([_row("SC_CL_9", "BELUM_SESUAI")])
    p2 = _eval([_row("SC_CL_9", "SESUAI")])
    merged, rincian = T.merge_pass2(base, p2, ["SC_CL_8"])   # SC_CL_9 tidak diminta
    assert merged["scorecard_result"][0]["status"] == "BELUM_SESUAI"
    assert rincian == []


def test_item_kritis_yang_tertolong_mengembalikan_irisan_penalti():
    """SC_CL_37 kritis: begitu ia lulus di tahap 2, iris -(max/4) harus ikut hilang."""
    critical = [{"item_code": "SC_CL_37", "status": "FAIL", "requirement": "x"},
                {"item_code": "SC_CL_4", "status": "PASS", "requirement": "y"}]
    base = _eval([_row("SC_CL_37", "BELUM_SESUAI", 7.5), _row("SC_CL_4", "SESUAI", 7)],
                 critical=critical)
    assert base["ai_score_critical_compliance_check"] == -27.1875
    p2 = _eval([_row("SC_CL_37", "SESUAI", 7.5, evidence={"ticket_id": "T_2.pdf"},
                     evidence_source="penjelasan")])
    merged, _ = T.merge_pass2(base, p2, ["SC_CL_37"])
    ccc = merged["critical_compliance_check"]
    assert [c["status"] for c in ccc["checked_items"]] == ["PASS", "PASS"]
    assert ccc["status"] == "PASS"
    assert merged["ai_score_critical_compliance_check"] == 0


def test_skor_ikut_dihitung_ulang():
    base = _eval([_row("SC_CL_8", "BELUM_SESUAI", 4), _row("SC_CL_9", "SESUAI", 1)])
    p2 = _eval([_row("SC_CL_8", "SESUAI", 4, evidence={"ticket_id": "T_2.pdf"},
                     evidence_source="penjelasan")])
    merged, _ = T.merge_pass2(base, p2, ["SC_CL_8"])
    # phase_2 = maximum_score dikurangi potongan item BELUM_SESUAI; tidak ada lagi.
    assert merged["ai_score_phase_2"] == base["maximum_score"]


# --------------------------------------------------------------------------
# Gerbang SLA
# --------------------------------------------------------------------------

def _p(stamp):
    return f"/tmp/030808fLO1_{stamp}.pdf"


def test_sla_dihitung_mundur_dari_rekaman_terbaru():
    """14 Juli -> batas tanggal 7 Juli. 10 Juli masuk, 6 Juli tidak."""
    paths = [_p("20260706120000"), _p("20260710111836"), _p("20260714140803")]
    dalam, luar = T.recordings_within_sla(paths)
    assert luar == [_p("20260706120000")]
    assert dalam == [_p("20260710111836"), _p("20260714140803")]


def test_batas_dihitung_per_tanggal_bukan_per_menit():
    """Rekaman 9 Juli 16:49 dengan rekaman terbaru 16 Juli 17:04 TETAP masuk.

    Persis kasus tiket 060526FLPO: dengan presisi menit ia lewat 15 menit dan gugur;
    dengan tanggal kalender ia masuk. Ditegaskan sebagai keputusan bisnis 5 September
    2026 — lihat SLA_WINDOW.
    """
    paths = [_p("20260709164916"), _p("20260716170459")]
    dalam, luar = T.recordings_within_sla(paths)
    assert luar == [] and len(dalam) == 2


def test_sehari_sebelum_batas_tetap_di_luar():
    paths = [_p("20260708235959"), _p("20260716000001")]
    dalam, luar = T.recordings_within_sla(paths)
    assert luar == [_p("20260708235959")]


def test_berkas_tanpa_timestamp_dianggap_masuk():
    """Tidak tahu kapan ia terjadi; menendangnya keluar = menghukum penamaan berkas."""
    paths = ["/tmp/tanpa-stempel.pdf", _p("20260714140803")]
    dalam, luar = T.recordings_within_sla(paths)
    assert luar == [] and len(dalam) == 2


def test_playground_030808fLO1_masih_dalam_sla():
    """Dua rekaman valid tiket playground (13:18 & 14:08 pada 14 Juli) -> partial boleh."""
    paths = [_p("20260714131827"), _p("20260714140803")]
    assert T.recordings_within_sla(paths) == (paths, [])


# --------------------------------------------------------------------------
# split_by_tag
# --------------------------------------------------------------------------

def test_pembagian_menurut_tag_dan_keranjang_sisa():
    tags = {"a.pdf": {"tag": "recording_utama"}, "b.pdf": {"tag": "recording_perbaikan"},
            "c.pdf": {"tag": "lainnya"}}
    utama, perbaikan, lain = T.split_by_tag(
        ["/x/a.pdf", "/x/b.pdf", "/x/c.pdf", "/x/d.pdf"], tags)
    assert utama == ["/x/a.pdf"]
    assert perbaikan == ["/x/b.pdf"]
    # ``lainnya`` DAN berkas tanpa tag sama-sama jatuh ke keranjang sisa.
    assert lain == ["/x/c.pdf", "/x/d.pdf"]


# --------------------------------------------------------------------------
# Batas sumber evidence (tahap 2 melihat transkrip utuh, tapi hanya boleh
# mengambil evidence dari rekaman perbaikan)
# --------------------------------------------------------------------------

def test_evidence_dari_rekaman_utama_ditolak():
    """Pintu yang ditutup Fase #3 tidak boleh terbuka lagi lewat tahap 2.

    Tahap 2 menerima transkrip tiket secara utuh sebagai konteks, jadi tanpa penyaring
    ini item yang gagal di rekaman utama bisa "diselamatkan" oleh kutipan dari rekaman
    utama itu juga — persis kebocoran yang sedang dihapus.
    """
    base = _eval([_row("SC_CL_8", "BELUM_SESUAI", 4)])
    p2 = _eval([_row("SC_CL_8", "SESUAI", 4,
                     evidence={"ticket_id": "T_20260714131827"},   # rekaman UTAMA
                     evidence_source="penjelasan")])
    merged, rincian = T.merge_pass2(base, p2, ["SC_CL_8"], ["T_20260714140803.pdf"])
    assert merged["scorecard_result"][0]["status"] == "BELUM_SESUAI"
    assert rincian == []


def test_evidence_dari_rekaman_perbaikan_diterima_dengan_atau_tanpa_pdf():
    base = _eval([_row("SC_CL_8", "BELUM_SESUAI", 4)])
    p2 = _eval([_row("SC_CL_8", "SESUAI", 4,
                     evidence={"ticket_id": "T_20260714140803"},
                     evidence_source="penjelasan")])
    merged, rincian = T.merge_pass2(base, p2, ["SC_CL_8"], ["T_20260714140803.pdf"])
    assert merged["scorecard_result"][0]["status"] == "SESUAI"
    assert len(rincian) == 1


def test_tanpa_daftar_berkas_penyaring_tidak_aktif():
    """Kompatibilitas: pemanggil lama tanpa ``evidence_files`` tetap berjalan."""
    base = _eval([_row("SC_CL_8", "BELUM_SESUAI", 4)])
    p2 = _eval([_row("SC_CL_8", "SESUAI", 4, evidence={"ticket_id": "apa saja"})])
    merged, rincian = T.merge_pass2(base, p2, ["SC_CL_8"])
    assert merged["scorecard_result"][0]["status"] == "SESUAI" and len(rincian) == 1


def test_penanda_fallback_hanya_untuk_kategori_yang_punya_aturannya():
    """Di kategori Final Konfirmasi, evidence dari recap BUKAN fallback — itu sumber
    satu-satunya yang sah. Menandainya "fallback" menyatakan hal yang tidak benar."""
    base = _eval([_row("SC_CL_28", "BELUM_SESUAI", 3, category="Final Konfirmasi Mega Cashline")])
    p2 = _eval([_row("SC_CL_28", "SESUAI", 3, category="Final Konfirmasi Mega Cashline",
                     evidence={"ticket_id": "T_2"},
                     evidence_source="fallback_final_konfirmasi")])
    merged, rincian = T.merge_pass2(base, p2, ["SC_CL_28"], ["T_2.pdf"])
    assert merged["scorecard_result"][0]["status"] == "SESUAI"
    assert merged["scorecard_result"][0]["evidence_source"] is None
    assert rincian[0]["evidence_source"] is None


def test_penanda_disimpan_untuk_kategori_penjelasan():
    base = _eval([_row("SC_CL_8", "BELUM_SESUAI", 4)])
    p2 = _eval([_row("SC_CL_8", "SESUAI", 4, evidence={"ticket_id": "T_2"},
                     evidence_source="fallback_final_konfirmasi")])
    merged, _ = T.merge_pass2(base, p2, ["SC_CL_8"], ["T_2.pdf"])
    assert merged["scorecard_result"][0]["evidence_source"] == "fallback_final_konfirmasi"


# --------------------------------------------------------------------------
# Blok verifikasi ikut tahap 2 (5 September 2026)
# --------------------------------------------------------------------------

def _verif(field, match, **extra):
    return {"field": field, "match": match, "reason": f"{field} {match}", **extra}


def test_verifikasi_cashline_ikut_diperbaiki():
    """Tanpa ini scorecard bilang provisi SESUAI sementara verifikasi bilang
    'tidak pernah disebut' — satu tiket, dua kebenaran, plus error code B03 palsu."""
    base = _eval([_row("SC_CL_8", "BELUM_SESUAI", 4)])
    base["cashline_data_verification"] = [_verif("provisi", "MISMATCH"),
                                          _verif("tenor", "MATCH")]
    p2 = _eval([_row("SC_CL_8", "SESUAI", 4, evidence={"ticket_id": "T_2"},
                     evidence_source="penjelasan")])
    p2["cashline_data_verification"] = [
        _verif("provisi", "MATCH", extracted_value="2%", evidence={"ticket_id": "T_2"})]
    merged, rincian = T.merge_pass2(base, p2, ["SC_CL_8"], ["T_2.pdf"])
    prov = [v for v in merged["cashline_data_verification"] if v["field"] == "provisi"][0]
    assert prov["match"] == "MATCH" and prov["pass2"] is True
    assert {"block": "cashline_data_verification", "field": "provisi", "file": "T_2"} in rincian


def test_verifikasi_tidak_pernah_diperburuk():
    base = _eval([_row("SC_CL_8", "SESUAI", 4)])
    base["cashline_data_verification"] = [_verif("tenor", "MATCH")]
    p2 = _eval([_row("SC_CL_8", "SESUAI", 4)])
    p2["cashline_data_verification"] = [_verif("tenor", "MISMATCH",
                                               evidence={"ticket_id": "T_2"})]
    merged, _ = T.merge_pass2(base, p2, ["SC_CL_8"], ["T_2.pdf"])
    assert merged["cashline_data_verification"][0]["match"] == "MATCH"


def test_verifikasi_tanpa_evidence_tetap_digabung():
    """Baris cashline_data_verification TIDAK membawa evidence sama sekali.

    Percobaan pertama tetap memberlakukan penyaring asal-berkas padanya, sehingga
    setiap baris tertolak diam-diam dan penggabungan verifikasi tidak pernah menyala —
    terlihat pada reprocess 030808fLO1 yang B03 Bunga/Provisi-nya tidak kunjung hilang.
    """
    base = _eval([_row("SC_CL_8", "SESUAI", 4)])
    base["cashline_data_verification"] = [_verif("provisi", "MISMATCH")]
    p2 = _eval([_row("SC_CL_8", "SESUAI", 4)])
    p2["cashline_data_verification"] = [_verif("provisi", "MATCH")]   # tanpa evidence
    merged, rincian = T.merge_pass2(base, p2, ["SC_CL_8"], ["T_2.pdf"])
    assert merged["cashline_data_verification"][0]["match"] == "MATCH"
    assert len(rincian) == 1


def test_verifikasi_dengan_evidence_rekaman_utama_ditolak():
    base = _eval([_row("SC_CL_8", "BELUM_SESUAI", 4)])
    base["cashline_data_verification"] = [_verif("provisi", "MISMATCH")]
    p2 = _eval([_row("SC_CL_8", "BELUM_SESUAI", 4)])
    p2["cashline_data_verification"] = [_verif("provisi", "MATCH",
                                               evidence={"ticket_id": "T_1"})]
    merged, rincian = T.merge_pass2(base, p2, ["SC_CL_8"], ["T_2.pdf"])
    assert merged["cashline_data_verification"][0]["match"] == "MISMATCH"
    assert rincian == []


def test_card_holder_tidak_ikut_ditimpa():
    """Identitas nasabah punya jalur normalisasi deterministik sendiri di Python."""
    base = _eval([_row("SC_CL_8", "BELUM_SESUAI", 4)])
    base["card_holder_verification"] = [_verif("nama_ibu_kandung", "MISMATCH")]
    p2 = _eval([_row("SC_CL_8", "SESUAI", 4, evidence={"ticket_id": "T_2"})])
    p2["card_holder_verification"] = [_verif("nama_ibu_kandung", "MATCH",
                                             evidence={"ticket_id": "T_2"})]
    merged, _ = T.merge_pass2(base, p2, ["SC_CL_8"], ["T_2.pdf"])
    assert merged["card_holder_verification"][0]["match"] == "MISMATCH"


def test_verifikasi_membaik_walau_tak_ada_item_scorecard_tertolong():
    base = _eval([_row("SC_CL_8", "BELUM_SESUAI", 4)])
    base["cashline_data_verification"] = [_verif("provisi", "MISMATCH")]
    p2 = _eval([_row("SC_CL_8", "BELUM_SESUAI", 4)])
    p2["cashline_data_verification"] = [_verif("provisi", "MATCH",
                                               evidence={"ticket_id": "T_2"})]
    merged, rincian = T.merge_pass2(base, p2, ["SC_CL_8"], ["T_2.pdf"])
    assert merged["cashline_data_verification"][0]["match"] == "MATCH"
    assert merged["scorecard_result"][0]["status"] == "BELUM_SESUAI"
    assert len(rincian) == 1


def test_baris_verifikasi_yang_naik_tidak_membawa_potongan_lama():
    """Baris MATCH tidak boleh menyisakan item_score negatif dari vonis tahap 1.

    Tabel "Ringkasan Penilaian AI" memungut baris verifikasi ber-item_score negatif ke
    bagian "Pengurangan – Verifikasi data"; tanpa penyetelan ulang ini tiket 030808fLO1
    menampilkan tiga baris pengurangan yang alasannya justru berbunyi "sesuai TMS".
    """
    base = _eval([_row("SC_CL_8", "SESUAI", 4)])
    base["cashline_data_verification"] = [_verif("provisi", "MISMATCH", item_score=-4)]
    p2 = _eval([_row("SC_CL_8", "SESUAI", 4)])
    p2["cashline_data_verification"] = [_verif("provisi", "MATCH")]
    merged, _ = T.merge_pass2(base, p2, ["SC_CL_8"], ["T_2.pdf"])
    assert merged["cashline_data_verification"][0]["item_score"] == 0


def test_skor_positif_dari_tahap_2_dipertahankan():
    base = _eval([_row("SC_CL_8", "SESUAI", 4)])
    base["cashline_data_verification"] = [_verif("provisi", "MISMATCH", item_score=-4)]
    p2 = _eval([_row("SC_CL_8", "SESUAI", 4)])
    p2["cashline_data_verification"] = [_verif("provisi", "MATCH", item_score=2)]
    merged, _ = T.merge_pass2(base, p2, ["SC_CL_8"], ["T_2.pdf"])
    assert merged["cashline_data_verification"][0]["item_score"] == 2


# --------------------------------------------------------------------------
# resync_scores dipanggil untuk SETIAP tiket (5 September 2026)
# --------------------------------------------------------------------------

def test_iris_non_tolerable_ikut_tersimpan():
    """Suku yang selama ini hilang: LLM tidak mengenal iris 10% item non-tolerable,
    sehingga 180107uT48 tersimpan berskor 94 padahal yang berlaku 19."""
    ev = _eval([_row("SC_CL_7", "BELUM_SESUAI", 1, tolerable="NO"),
                _row("SC_CL_8", "BELUM_SESUAI", 4, tolerable="NO")],
               maximum_score=150)
    ev["ai_score_phase_3"] = 999          # angka mentah LLM yang keliru
    out = T.resync_scores(ev)
    assert out["ai_score_non_tolerable"] == -30.0      # 2 item x 10% x 150
    assert out["ai_score_phase_3"] == 145 - 30         # phase2 145, bomb -30
    assert out["ai_score_phase_3"] != 999


def test_blok_kritis_tidak_disentuh():
    """Menyelaraskannya butuh keputusan arah; hanya sah lewat merge_pass2."""
    critical = [{"item_code": "SC_CL_24", "status": "FAIL", "requirement": "x"}]
    ev = _eval([_row("SC_CL_24", "SESUAI", 15)], critical=critical)
    out = T.resync_scores(ev)
    assert out["critical_compliance_check"]["checked_items"][0]["status"] == "FAIL"
