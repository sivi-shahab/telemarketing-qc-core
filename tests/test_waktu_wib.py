"""Pembanding "sekarang" harus WIB, sama dengan data yang dibandingkannya.

Postgres produksi memakai ``TimeZone = Asia/Jakarta``, jadi kolom
``server_default=func.now()`` (mis. ``reprocess_jobs.created_at``) berisi jam WIB, dan
``submit_time`` TMS juga WIB. Container api/worker berjalan dalam UTC, sehingga
``datetime.now()`` tertinggal 7 jam (28 September 2026):

- tenggat reproses "tersangkut" 6 jam efektif menjadi 13 jam;
- tiket kekurangan dokumen baru jatuh FAIL (H+2) 7 jam terlambat.

Sejak migrasi 0060 kolom DB disimpan UTC (sesi dipaksa ``timezone=UTC``), jadi batas
reproses kembali UTC. ``submit_time`` TMS tetap WIB dari hulunya, jadi tenggat H+2
tetap memakai ``crud.now_wib()``.
"""
import inspect
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from qc_core.compliance import stats_aggregate
from qc_core.db import crud


@pytest.fixture()
def container_utc():
    """Jalankan test seperti di container: TZ proses = UTC."""
    old = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    time.tzset()
    yield
    if old is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = old
    time.tzset()


def _wib_sekarang():
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=7)


def test_now_wib_tetap_wib_walau_container_utc(container_utc):
    assert abs(crud.now_wib() - _wib_sekarang()) < timedelta(seconds=5)
    assert crud.now_wib().tzinfo is None  # sebanding dengan kolom DateTime naive


def test_tenggat_h2_sudah_lewat_menurut_jam_wib(container_utc, monkeypatch):
    monkeypatch.setitem(stats_aggregate._DOC_SLA_RUNTIME, "value", True)
    # submit 50 jam lalu (WIB) -> H+2 (48 jam) sudah lewat. Dengan "sekarang" UTC,
    # selisihnya hanya 43 jam dan tiket keliru tetap PENDING.
    submit = (_wib_sekarang() - timedelta(hours=50)).strftime("%Y-%m-%d %H:%M:%S")

    assert stats_aggregate._doc_sla_expired(submit) is True


def test_tenggat_h2_belum_lewat_menurut_jam_wib(container_utc, monkeypatch):
    monkeypatch.setitem(stats_aggregate._DOC_SLA_RUNTIME, "value", True)
    submit = (_wib_sekarang() - timedelta(hours=46)).strftime("%Y-%m-%d %H:%M:%S")

    assert stats_aggregate._doc_sla_expired(submit) is False


def test_statistik_tidak_memakai_jam_container_untuk_tenggat():
    """Semua pemanggil ``_doc_sla_expired`` di modul ini mengirim ``now`` sendiri;
    tidak satu pun boleh berasal dari ``datetime.now()`` (UTC di container)."""
    assert "datetime.now()" not in inspect.getsource(stats_aggregate)


def test_batas_reproses_tersangkut_dihitung_dari_jam_utc(container_utc):
    """``reprocess_jobs.created_at`` disimpan UTC (sesi DB dipaksa timezone=UTC sejak
    migrasi 0060), jadi batasnya UTC — bukan WIB seperti ``submit_time`` TMS."""
    clause = crud._reprocess_item_active_clause()
    _processing, pending_and_fresh = clause.clauses
    (created_cmp,) = [c for c in pending_and_fresh.clauses if "created_at" in str(c)]
    batas = created_cmp.right.value
    utc_sekarang = datetime.now(timezone.utc).replace(tzinfo=None)

    assert abs(batas - (utc_sekarang - crud.REPROCESS_STALE_AFTER)) < timedelta(seconds=5)
