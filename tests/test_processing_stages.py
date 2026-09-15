"""Tabel progres pipeline: urutan, label, dan arti ``current_stage``.

Daftar tahap dibaca DUA sisi — worker menulis checkpoint-nya, API menampilkannya —
jadi ia tinggal di core. Test ini menjaga dua hal yang mudah tergelincir: kunci tahap
harus sama persis dengan yang ditulis worker, dan ``current_stage`` adalah tahap yang
SUDAH selesai (yang berjalan adalah satu sesudahnya), bukan yang sedang berjalan.
"""
from qc_core.compliance.processing_stages import (
    PROCESSING_STAGES,
    STAGE_KEYS,
    stage_table,
)


def test_urutan_dan_kunci_stabil():
    assert STAGE_KEYS == (
        "unduh_pdf", "baca_teks_pdf", "klasifikasi_llm", "rangkai_transkrip",
        "campaign_dan_acuan", "penilaian_llm", "gabung_dan_skor", "simpan_hasil",
        "tandai_selesai",
    )
    assert len(PROCESSING_STAGES) == len(STAGE_KEYS)
    assert all(label.strip() for _, label in PROCESSING_STAGES), "setiap tahap wajib punya label"


def test_belum_ada_checkpoint_tahap_pertama_berjalan():
    rows = stage_table(None)
    assert rows[0]["state"] == "berjalan", "None berarti BELUM selesai, bukan sudah"
    assert {r["state"] for r in rows[1:]} == {"menunggu"}


def test_current_stage_adalah_yang_SUDAH_selesai():
    rows = stage_table("klasifikasi_llm")
    by_key = {r["key"]: r["state"] for r in rows}
    assert by_key["unduh_pdf"] == "selesai"
    assert by_key["baca_teks_pdf"] == "selesai"
    assert by_key["klasifikasi_llm"] == "selesai"
    # yang berjalan adalah SATU SESUDAHNYA
    assert by_key["rangkai_transkrip"] == "berjalan"
    assert by_key["campaign_dan_acuan"] == "menunggu"


def test_tahap_terakhir_selesai_tidak_ada_yang_berjalan():
    rows = stage_table("tandai_selesai")
    assert {r["state"] for r in rows} == {"selesai"}


def test_tahap_tak_dikenal_diperlakukan_seperti_None():
    """Hasil lama / nama tahap yang sudah dihapus tidak boleh membuat tabel tampak selesai."""
    assert stage_table("tahap_yang_sudah_tidak_ada") == stage_table(None)


def test_label_ikut_terbawa():
    rows = stage_table("unduh_pdf")
    assert rows[0]["label"] == "Mengunduh rekaman dari penyimpanan"
