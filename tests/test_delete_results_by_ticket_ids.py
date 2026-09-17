"""Delete All (``crud.delete_results_by_ticket_ids``) dan aturan reprocess tersangkut.

Hanya bagian yang murni unit di sini; test yang memakai fixture ``db`` tetap di
repo api (``tests/test_delete_filtered.py``, ``tests/test_reprocess_active_flag.py``).
"""
from datetime import timedelta

from qc_core.db import crud


class _UntouchableDb:
    def __getattr__(self, name):
        raise AssertionError(f"db.{name} tidak boleh disentuh untuk daftar kosong")


def test_ticket_id_chunks_bersih_unik_dan_dipecah():
    ids = [" T1 ", "T1", "", None, "T2"] + [f"X{i:05d}" for i in range(crud._TICKET_ID_CHUNK)]
    chunks = crud._ticket_id_chunks(ids)
    flat = [t for c in chunks for t in c]
    assert len(flat) == len(set(flat)) == crud._TICKET_ID_CHUNK + 2
    assert "T1" in flat and "" not in flat
    assert all(len(c) <= crud._TICKET_ID_CHUNK for c in chunks)
    assert len(chunks) == 2


def test_daftar_kosong_bukan_hapus_semua():
    db = _UntouchableDb()
    assert crud.delete_results_by_ticket_ids(db, []) == 0
    assert crud.delete_results_by_ticket_ids(db, None) == 0
    assert crud.results_count_by_ticket_ids(db, ["", "  "]) == 0


def test_ambang_pending_tersangkut_enam_jam():
    assert crud.REPROCESS_STALE_AFTER == timedelta(hours=6)


def test_klausa_aktif_processing_tidak_pernah_kedaluwarsa():
    clause = crud._reprocess_item_active_clause()
    processing, pending_and_fresh = clause.clauses
    assert "created_at" not in str(processing)
    assert processing.right.value == "processing"
    assert "created_at" in str(pending_and_fresh)


def test_klausa_aktif_processing_tidak_bergantung_status_job():
    """Membatalkan job hanya melewati item ``pending``; item ``processing``-nya
    tetap dikerjakan worker, jadi tiketnya harus tetap terhitung aktif walau job-nya
    sudah ``cancelled``. ``pending`` hanya dihitung selagi job-nya ``running``."""
    clause = crud._reprocess_item_active_clause()
    processing, pending_and_fresh = clause.clauses
    assert "reprocess_jobs.status" not in str(processing)
    assert "reprocess_jobs.status" in str(pending_and_fresh)
