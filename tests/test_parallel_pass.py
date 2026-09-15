"""Penilaian paralel (10 September 2026): satu panggilan LLM per rekaman, lalu digabung.

Rekaman utama = rekaman TERTUA (index 0) — keputusan Bank Mega 14 September 2026,
MENGGANTIKAN aturan lama "SESUAI terbanyak" (bias ke rekaman penutup singkat lewat
fallback Final Konfirmasi, lihat
docs/csv_bank/12 September 2026/recording_utama_perbaikan_ambiguity.md).
``scorecard_result`` utama jadi dasar; tiap baris non-SESUAI diisi dari rekaman lain
yang menilainya SESUAI (timestamp paling baru bila > 1). Blok di luar
``scorecard_result`` diambil utuh dari keluaran rekaman utama.
"""
from datetime import datetime

from qc_core.compliance import parallel_pass as pp


def _row(code, status, weight=4, **extra):
    r = {"item_code": code, "status": status, "weight": weight, "item_score": weight}
    r.update(extra)
    return r


def _eval(rows, **blocks):
    ev = {"scorecard_result": list(rows)}
    ev.update(blocks)
    return ev


TS = [
    datetime(2026, 7, 14, 10, 0, 0),
    datetime(2026, 7, 14, 13, 0, 0),
    datetime(2026, 7, 15, 9, 0, 0),
]


# --- sesuai_count ---------------------------------------------------------

def test_sesuai_count_hanya_menghitung_status_sesuai():
    ev = _eval([_row("A", "SESUAI"), _row("B", "belum_sesuai"),
                _row("C", " sesuai "), _row("D", "TIDAK_DINILAI")])
    assert pp.sesuai_count(ev) == 2


def test_sesuai_count_scorecard_kosong():
    assert pp.sesuai_count({}) == 0


# --- pick_utama ---------------------------------------------------------

def test_pick_utama_selalu_rekaman_tertua():
    """SESUAI terbanyak TIDAK LAGI relevan — rekaman ke-2 punya SESUAI lebih
    banyak (2 vs 1) tapi index 0 (rekaman tertua, pemanggil menjamin urut
    kronologis) tetap yang dipilih."""
    evals = [
        _eval([_row("A", "SESUAI"), _row("B", "BELUM_SESUAI")]),
        _eval([_row("A", "SESUAI"), _row("B", "SESUAI")]),
        _eval([_row("A", "BELUM_SESUAI"), _row("B", "BELUM_SESUAI")]),
    ]
    assert pp.pick_utama(evals) == 0


def test_pick_utama_satu_rekaman():
    assert pp.pick_utama([_eval([_row("A", "SESUAI")])]) == 0


def test_pick_utama_daftar_kosong_menolak():
    try:
        pp.pick_utama([])
    except ValueError:
        return
    raise AssertionError("harus ValueError")


# --- merge_parallel ---------------------------------------------------------

def test_merge_utama_jadi_dasar_dan_blok_luar_dari_utama():
    utama = _eval(
        [_row("A", "SESUAI"), _row("B", "BELUM_SESUAI")],
        cashline_interest={"status": "INTERESTED"},
        ai_summary="ringkasan utama",
    )
    perbaikan = _eval(
        [_row("A", "BELUM_SESUAI"), _row("B", "BELUM_SESUAI")],
        cashline_interest={"status": "NOT_STATED"},
        ai_summary="ringkasan perbaikan",
    )
    out, isian, _isian_cashline = pp.merge_parallel([utama, perbaikan], ["u.pdf", "p.pdf"],
                                   [TS[0], TS[1]], 0)
    assert out["cashline_interest"] == {"status": "INTERESTED"}
    assert out["ai_summary"] == "ringkasan utama"
    assert isian == []


def test_merge_item_non_sesuai_diisi_dari_perbaikan():
    utama = _eval([_row("A", "SESUAI"), _row("B", "BELUM_SESUAI")])
    perbaikan = _eval([_row("A", "SESUAI"),
                       _row("B", "SESUAI", evidence={"ticket_id": "p", "quote": "ada"})])
    out, isian, _isian_cashline = pp.merge_parallel([utama, perbaikan], ["u.pdf", "p.pdf"],
                                   [TS[0], TS[1]], 0)
    baris = {r["item_code"]: r for r in out["scorecard_result"]}
    assert baris["B"]["status"] == "SESUAI"
    assert baris["B"]["evidence"] == {"ticket_id": "p", "quote": "ada"}
    # ditandai supaya stamp_reason_provenance menulis kalimat "dari recording perbaikan"
    assert baris["B"]["pass2"] is True
    assert "pass2" not in baris["A"]          # baris SESUAI dari utama tak disentuh
    assert isian == [{
        "item_code": "B", "dari_status": "BELUM_SESUAI", "ke_status": "SESUAI",
        "sumber_file": "p.pdf", "evidence": {"ticket_id": "p", "quote": "ada"},
    }]


def test_merge_item_sesuai_di_utama_tidak_pernah_ditimpa():
    utama = _eval([_row("A", "SESUAI", evidence={"quote": "utama"})])
    perbaikan = _eval([_row("A", "SESUAI", evidence={"quote": "perbaikan"})])
    out, isian, _isian_cashline = pp.merge_parallel([utama, perbaikan], ["u.pdf", "p.pdf"],
                                   [TS[0], TS[1]], 0)
    assert out["scorecard_result"][0]["evidence"] == {"quote": "utama"}
    assert isian == []


def test_merge_lebih_dari_satu_perbaikan_ambil_timestamp_terbaru():
    utama = _eval([_row("A", "BELUM_SESUAI")])
    p_awal = _eval([_row("A", "SESUAI", evidence={"quote": "awal"})])
    p_akhir = _eval([_row("A", "SESUAI", evidence={"quote": "akhir"})])
    # utama index 0; p_awal TS[1], p_akhir TS[2] (lebih baru)
    out, isian, _isian_cashline = pp.merge_parallel(
        [utama, p_awal, p_akhir], ["u.pdf", "p1.pdf", "p2.pdf"],
        [TS[0], TS[1], TS[2]], 0,
    )
    assert out["scorecard_result"][0]["evidence"] == {"quote": "akhir"}
    assert isian[0]["sumber_file"] == "p2.pdf"


def test_merge_tidak_ada_kandidat_baris_utama_dipertahankan():
    utama = _eval([_row("A", "BELUM_SESUAI", evidence={"quote": "u"})])
    perbaikan = _eval([_row("A", "BELUM_SESUAI")])
    out, isian, _isian_cashline = pp.merge_parallel([utama, perbaikan], ["u.pdf", "p.pdf"],
                                   [TS[0], TS[1]], 0)
    assert out["scorecard_result"][0] == utama["scorecard_result"][0]
    assert isian == []


def test_merge_baris_tanpa_item_code_dibiarkan():
    utama = _eval([{"item_code": None, "status": "BELUM_SESUAI"},
                   _row("A", "BELUM_SESUAI")])
    perbaikan = _eval([{"item_code": None, "status": "SESUAI"},
                       _row("A", "SESUAI", evidence={"q": 1})])
    out, isian, _isian_cashline = pp.merge_parallel([utama, perbaikan], ["u.pdf", "p.pdf"],
                                   [TS[0], TS[1]], 0)
    assert out["scorecard_result"][0] == {"item_code": None, "status": "BELUM_SESUAI"}
    assert [it["item_code"] for it in isian] == ["A"]


def test_merge_urutan_baris_mengikuti_utama():
    utama = _eval([_row("C", "SESUAI"), _row("A", "BELUM_SESUAI"), _row("B", "SESUAI")])
    perbaikan = _eval([_row("A", "SESUAI", evidence={"q": 1})])
    out, _, _isian_cashline = pp.merge_parallel([utama, perbaikan], ["u.pdf", "p.pdf"],
                               [TS[0], TS[1]], 0)
    assert [r["item_code"] for r in out["scorecard_result"]] == ["C", "A", "B"]


def test_merge_utama_bukan_index_nol():
    """``merge_parallel`` menerima ``utama_idx`` berapa pun dari pemanggilnya —
    di sini index 1 dipasang langsung (bukan lewat ``pick_utama``, yang sejak
    14 September 2026 SELALU mengembalikan 0/rekaman tertua; lihat
    test_pick_utama_selalu_rekaman_tertua)."""
    r0 = _eval([_row("A", "BELUM_SESUAI"), _row("B", "BELUM_SESUAI")])
    r1 = _eval([_row("A", "SESUAI"), _row("B", "BELUM_SESUAI")])
    r2 = _eval([_row("A", "BELUM_SESUAI"),
                _row("B", "SESUAI", evidence={"q": "r2"})])
    out, isian, _isian_cashline = pp.merge_parallel([r0, r1, r2], ["r0.pdf", "r1.pdf", "r2.pdf"],
                                   [TS[0], TS[1], TS[2]], 1)
    baris = {r["item_code"]: r for r in out["scorecard_result"]}
    assert baris["A"]["status"] == "SESUAI"          # dari utama sendiri
    assert baris["B"]["status"] == "SESUAI"          # diisi dari r2
    assert isian[0]["sumber_file"] == "r2.pdf"


def test_merge_panjang_tidak_cocok_menolak():
    try:
        pp.merge_parallel([_eval([])], ["a.pdf", "b.pdf"], [TS[0]], 0)
    except ValueError:
        return
    raise AssertionError("harus ValueError")


# --- _merge_cashline_data / merge_parallel (cashline_data_extraction/_verification) ---

def _verif_row(field, extracted, reference, match="MATCH", **extra):
    row = {
        "field": field, "match": match, "extracted_value": extracted,
        "reference_value": reference, "reason": f"{field}: {extracted!r} vs {reference!r}",
    }
    row.update(extra)
    return row


def test_cashline_data_tidak_ada_di_evaluasi_manapun_dilewati():
    """Campaign lain / tidak punya blok ini sama sekali -> kunci tidak disentuh."""
    utama = _eval([_row("A", "SESUAI")])
    perbaikan = _eval([_row("A", "SESUAI")])
    out, _, isian_cashline = pp.merge_parallel(
        [utama, perbaikan], ["u.pdf", "p.pdf"], [TS[0], TS[1]], 0
    )
    assert "cashline_data_extraction" not in out
    assert isian_cashline == []


def test_cashline_data_field_kosong_di_utama_diisi_dari_perbaikan():
    """Kasus nyata 030808fLO1: bunga/provisi kosong di rekaman utama, tersedia di
    rekaman perbaikan -> harus diambil dari perbaikan, bukan dibiarkan null."""
    utama = _eval(
        [_row("A", "SESUAI")],
        cashline_data_extraction={"bunga": None, "provisi": None, "nominal_cicilan_per_bulan": "3128000"},
        cashline_data_verification=[
            _verif_row("bunga", None, "2.09%", match="MISMATCH"),
            _verif_row("provisi", None, "2% dari limit kredit", match="MISMATCH"),
            _verif_row("nominal_cicilan_per_bulan", "3128000", "3128333", match="MISMATCH"),
        ],
    )
    perbaikan = _eval(
        [_row("A", "SESUAI")],
        cashline_data_extraction={"bunga": "2.09%", "provisi": "2% dari limit kredit", "nominal_cicilan_per_bulan": "3128333"},
        cashline_data_verification=[
            _verif_row("bunga", "2.09%", "2.09%"),
            _verif_row("provisi", "2% dari limit kredit", "2% dari limit kredit"),
            _verif_row("nominal_cicilan_per_bulan", "3128333", "3128333"),
        ],
    )
    out, _, isian_cashline = pp.merge_parallel(
        [utama, perbaikan], ["u.pdf", "p.pdf"], [TS[0], TS[1]], 0
    )
    assert out["cashline_data_extraction"] == {
        "bunga": "2.09%", "provisi": "2% dari limit kredit", "nominal_cicilan_per_bulan": "3128333",
    }
    verif = {v["field"]: v for v in out["cashline_data_verification"]}
    assert verif["bunga"]["match"] == "MATCH"
    assert verif["provisi"]["match"] == "MATCH"
    # nominal_cicilan_per_bulan: utama SUDAH punya nilai (bukan kosong) tapi SALAH
    # (simulasi awal) -- tetap harus ditimpa oleh nilai final rekaman perbaikan.
    assert verif["nominal_cicilan_per_bulan"]["match"] == "MATCH"
    assert {i["field"] for i in isian_cashline} == {"bunga", "provisi", "nominal_cicilan_per_bulan"}
    assert all(i["sumber_file"] == "p.pdf" for i in isian_cashline)


def test_cashline_data_field_valid_di_utama_tidak_ditimpa_bila_perbaikan_kosong():
    utama = _eval(
        [_row("A", "SESUAI")],
        cashline_data_extraction={"nama_bank": "BCA"},
        cashline_data_verification=[_verif_row("nama_bank", "BCA", "BCA")],
    )
    perbaikan = _eval(
        [_row("A", "SESUAI")],
        cashline_data_extraction={"nama_bank": None},
        cashline_data_verification=[],
    )
    out, _, isian_cashline = pp.merge_parallel(
        [utama, perbaikan], ["u.pdf", "p.pdf"], [TS[0], TS[1]], 0
    )
    assert out["cashline_data_extraction"]["nama_bank"] == "BCA"
    assert isian_cashline == []


def test_cashline_data_field_sama_di_kedua_rekaman_tidak_dicatat_sebagai_isian():
    utama = _eval([_row("A", "SESUAI")], cashline_data_extraction={"nama_bank": "BCA"})
    perbaikan = _eval([_row("A", "SESUAI")], cashline_data_extraction={"nama_bank": "BCA"})
    out, _, isian_cashline = pp.merge_parallel(
        [utama, perbaikan], ["u.pdf", "p.pdf"], [TS[0], TS[1]], 0
    )
    assert out["cashline_data_extraction"]["nama_bank"] == "BCA"
    assert isian_cashline == []


def test_cashline_data_lebih_dari_satu_kandidat_ambil_timestamp_terbaru():
    utama = _eval([_row("A", "SESUAI")], cashline_data_extraction={"bunga": None})
    p_awal = _eval([_row("A", "SESUAI")], cashline_data_extraction={"bunga": "1.99%"})
    p_akhir = _eval([_row("A", "SESUAI")], cashline_data_extraction={"bunga": "2.09%"})
    out, _, isian_cashline = pp.merge_parallel(
        [utama, p_awal, p_akhir], ["u.pdf", "p1.pdf", "p2.pdf"],
        [TS[0], TS[1], TS[2]], 0,
    )
    assert out["cashline_data_extraction"]["bunga"] == "2.09%"
    assert isian_cashline[0]["sumber_file"] == "p2.pdf"


# --- aturan Bank Mega "wajib ulang" (Penjelasan gagal -> Final Konfirmasi/Legal
# Statement Mega Cashline harus diulang di rekaman perbaikan) -------------------

def _pj(code, status, **extra):
    return _row(code, status, category="Penjelasan Mega Cashline", **extra)


def _fk(code, status, **extra):
    return _row(code, status, category="Final Konfirmasi Mega Cashline", **extra)


def _ls(code, status, **extra):
    return _row(code, status, category="Legal Statement Mega Cashline", **extra)


def test_wajib_ulang_menimpa_final_konfirmasi_walau_sudah_sesuai_di_utama():
    """SC_CL_27 SESUAI di utama TETAP ditimpa versi perbaikan — kewajibannya
    MENGULANG, bukan sekadar memperbaiki yang gagal."""
    utama = _eval([
        _pj("SC_CL_7", "BELUM_SESUAI"),
        _fk("SC_CL_27", "SESUAI", evidence={"quote": "utama"}),
    ])
    perbaikan = _eval([
        _pj("SC_CL_7", "SESUAI", evidence={"quote": "p"}),
        _fk("SC_CL_27", "SESUAI", evidence={"quote": "perbaikan"}),
    ])
    out, isian, _ = pp.merge_parallel([utama, perbaikan], ["u.pdf", "p.pdf"], [TS[0], TS[1]], 0)
    baris = {r["item_code"]: r for r in out["scorecard_result"]}
    assert baris["SC_CL_27"]["evidence"] == {"quote": "perbaikan"}
    assert baris["SC_CL_27"]["pass2"] is True
    assert any(i["item_code"] == "SC_CL_27" and i["alasan"] == "wajib_ulang_final_konfirmasi_legal_statement"
               for i in isian)


def test_wajib_ulang_legal_statement_juga_ikut_ditimpa():
    utama = _eval([
        _pj("SC_CL_7", "BELUM_SESUAI"),
        _ls("SC_CL_37", "SESUAI", evidence={"quote": "utama"}),
    ])
    perbaikan = _eval([
        _pj("SC_CL_7", "SESUAI"),
        _ls("SC_CL_37", "SESUAI", evidence={"quote": "perbaikan"}),
    ])
    out, _, _ = pp.merge_parallel([utama, perbaikan], ["u.pdf", "p.pdf"], [TS[0], TS[1]], 0)
    baris = {r["item_code"]: r for r in out["scorecard_result"]}
    assert baris["SC_CL_37"]["evidence"] == {"quote": "perbaikan"}


def test_wajib_ulang_tidak_diulang_di_perbaikan_tetap_belum_sesuai():
    """Rekaman perbaikan TIDAK benar-benar mengulanginya -> hasil tetap
    BELUM_SESUAI, bersumber dari perbaikan (bukan diam-diam status lama utama)."""
    utama = _eval([
        _pj("SC_CL_7", "BELUM_SESUAI"),
        _fk("SC_CL_27", "SESUAI", evidence={"quote": "utama, harusnya tidak dipakai"}),
    ])
    perbaikan = _eval([
        _pj("SC_CL_7", "SESUAI"),
        _fk("SC_CL_27", "BELUM_SESUAI", evidence={"quote": "perbaikan tidak mengulang effective rate"}),
    ])
    out, _, _ = pp.merge_parallel([utama, perbaikan], ["u.pdf", "p.pdf"], [TS[0], TS[1]], 0)
    baris = {r["item_code"]: r for r in out["scorecard_result"]}
    assert baris["SC_CL_27"]["status"] == "BELUM_SESUAI"
    assert baris["SC_CL_27"]["evidence"] == {"quote": "perbaikan tidak mengulang effective rate"}


def test_wajib_ulang_tidak_berlaku_bila_penjelasan_tidak_gagal():
    utama = _eval([
        _pj("SC_CL_7", "SESUAI"),
        _fk("SC_CL_27", "SESUAI", evidence={"quote": "utama"}),
    ])
    perbaikan = _eval([
        _pj("SC_CL_7", "SESUAI"),
        _fk("SC_CL_27", "SESUAI", evidence={"quote": "perbaikan"}),
    ])
    out, isian, _ = pp.merge_parallel([utama, perbaikan], ["u.pdf", "p.pdf"], [TS[0], TS[1]], 0)
    baris = {r["item_code"]: r for r in out["scorecard_result"]}
    assert baris["SC_CL_27"]["evidence"] == {"quote": "utama"}
    assert isian == []


def test_wajib_ulang_tidak_menyentuh_kategori_lain():
    utama = _eval([
        _pj("SC_CL_7", "BELUM_SESUAI"),
        _row("SC_CL_1", "SESUAI", category="Greeting", evidence={"quote": "utama"}),
    ])
    perbaikan = _eval([
        _pj("SC_CL_7", "SESUAI"),
        _row("SC_CL_1", "SESUAI", category="Greeting", evidence={"quote": "perbaikan"}),
    ])
    out, _, _ = pp.merge_parallel([utama, perbaikan], ["u.pdf", "p.pdf"], [TS[0], TS[1]], 0)
    baris = {r["item_code"]: r for r in out["scorecard_result"]}
    assert baris["SC_CL_1"]["evidence"] == {"quote": "utama"}


def _pj_mus(code, status, **extra):
    return _row(code, status, category="Penjelasan Mega Ultima Shield", **extra)


def _fk_mus(code, status, **extra):
    return _row(code, status, category="Final Konfirmasi Mega Ultima Shield", **extra)


def _ls_mus(code, status, **extra):
    return _row(code, status, category="Legal Statement Mega Ultima Shield", **extra)


def test_wajib_ulang_berlaku_juga_untuk_mus():
    """Aturan yang sama berlaku simetris untuk Mega Ultima Shield — Penjelasan
    MUS gagal -> Final Konfirmasi & Legal Statement MUS wajib diulang."""
    utama = _eval([
        _pj_mus("SC_CL_19", "BELUM_SESUAI"),
        _fk_mus("SC_CL_35", "SESUAI", evidence={"quote": "utama"}),
        _ls_mus("SC_CL_38", "SESUAI", evidence={"quote": "utama"}),
    ])
    perbaikan = _eval([
        _pj_mus("SC_CL_19", "SESUAI"),
        _fk_mus("SC_CL_35", "SESUAI", evidence={"quote": "perbaikan"}),
        _ls_mus("SC_CL_38", "SESUAI", evidence={"quote": "perbaikan"}),
    ])
    out, isian, _ = pp.merge_parallel([utama, perbaikan], ["u.pdf", "p.pdf"], [TS[0], TS[1]], 0)
    baris = {r["item_code"]: r for r in out["scorecard_result"]}
    assert baris["SC_CL_35"]["evidence"] == {"quote": "perbaikan"}
    assert baris["SC_CL_38"]["evidence"] == {"quote": "perbaikan"}
    wajib_ulang = {i["item_code"] for i in isian if i.get("alasan") == "wajib_ulang_final_konfirmasi_legal_statement"}
    assert wajib_ulang == {"SC_CL_35", "SC_CL_38"}


def test_wajib_ulang_cashline_gagal_tidak_menyentuh_kategori_mus():
    """Hanya Cashline yang penjelasannya gagal -> kategori MUS TIDAK ikut
    diulang (aturannya per-produk, bukan global)."""
    utama = _eval([
        _pj("SC_CL_7", "BELUM_SESUAI"),
        _fk_mus("SC_CL_35", "SESUAI", evidence={"quote": "utama"}),
    ])
    perbaikan = _eval([
        _pj("SC_CL_7", "SESUAI"),
        _fk_mus("SC_CL_35", "SESUAI", evidence={"quote": "perbaikan"}),
    ])
    out, isian, _ = pp.merge_parallel([utama, perbaikan], ["u.pdf", "p.pdf"], [TS[0], TS[1]], 0)
    baris = {r["item_code"]: r for r in out["scorecard_result"]}
    assert baris["SC_CL_35"]["evidence"] == {"quote": "utama"}
    assert not any(i.get("alasan") == "wajib_ulang_final_konfirmasi_legal_statement" for i in isian)


def test_wajib_ulang_kedua_produk_gagal_sekaligus():
    """Cashline DAN MUS penjelasannya sama-sama gagal -> kedua produk wajib
    diulang sekaligus."""
    utama = _eval([
        _pj("SC_CL_7", "BELUM_SESUAI"),
        _pj_mus("SC_CL_19", "BELUM_SESUAI"),
        _fk("SC_CL_27", "SESUAI", evidence={"quote": "utama-cl"}),
        _fk_mus("SC_CL_35", "SESUAI", evidence={"quote": "utama-mus"}),
    ])
    perbaikan = _eval([
        _pj("SC_CL_7", "SESUAI"),
        _pj_mus("SC_CL_19", "SESUAI"),
        _fk("SC_CL_27", "SESUAI", evidence={"quote": "perbaikan-cl"}),
        _fk_mus("SC_CL_35", "SESUAI", evidence={"quote": "perbaikan-mus"}),
    ])
    out, _, _ = pp.merge_parallel([utama, perbaikan], ["u.pdf", "p.pdf"], [TS[0], TS[1]], 0)
    baris = {r["item_code"]: r for r in out["scorecard_result"]}
    assert baris["SC_CL_27"]["evidence"] == {"quote": "perbaikan-cl"}
    assert baris["SC_CL_35"]["evidence"] == {"quote": "perbaikan-mus"}


def test_wajib_ulang_perbaikan_tidak_menilai_item_dipertahankan():
    """Rekaman perbaikan tidak punya baris untuk item ini sama sekali -> baris
    utama dipertahankan (tidak ada yang bisa dijadikan pengganti)."""
    utama = _eval([
        _pj("SC_CL_7", "BELUM_SESUAI"),
        _fk("SC_CL_27", "SESUAI", evidence={"quote": "utama"}),
    ])
    perbaikan = _eval([_pj("SC_CL_7", "SESUAI")])  # tidak menilai SC_CL_27 sama sekali
    out, _, _ = pp.merge_parallel([utama, perbaikan], ["u.pdf", "p.pdf"], [TS[0], TS[1]], 0)
    baris = {r["item_code"]: r for r in out["scorecard_result"]}
    assert baris["SC_CL_27"]["evidence"] == {"quote": "utama"}
