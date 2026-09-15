"""``results.current_stage`` — kolom progres pipeline yang dibaca dashboard.

Kolomnya dideklarasikan di model, jadi SQLAlchemy akan menuliskannya ke dalam
SETIAP ``SELECT`` atas ``results``. Kalau migrasinya belum jalan di database,
bukan cuma fitur progresnya yang mati — seluruh query Result ikut gagal. Test ini
mengunci bentuk kolomnya supaya ia tidak pernah berbeda dari migrasi yang
menciptakannya (``0053`` di repo telemarketing-qc-api; BUKAN ``0052``, yang sudah
dipakai ``0052_perm_tl_qc_upload_sales_database``).
"""
from sqlalchemy import String

from qc_core.db import crud
from qc_core.db.models import Result


def test_kolom_current_stage_ada_di_model():
    col = Result.__table__.columns.get("current_stage")
    assert col is not None, "results.current_stage hilang dari model"


def test_current_stage_string_50_dan_boleh_null():
    col = Result.__table__.columns["current_stage"]
    assert isinstance(col.type, String)
    assert col.type.length == 50, "panjangnya harus sama dengan migrasi (String(50))"
    assert col.nullable, "NULL sebelum checkpoint pertama — hasil lama tidak di-backfill"


class _FakeQuery:
    def __init__(self, sink):
        self._sink = sink

    def filter(self, *a, **k):
        return self

    def update(self, values):
        self._sink["updated"] = values
        return 1


class _FakeDb:
    def __init__(self):
        self.sink = {}
        self.commits = 0

    def query(self, *a, **k):
        return _FakeQuery(self.sink)

    def commit(self):
        self.commits += 1


def test_set_result_stage_menulis_dan_commit_langsung():
    """Commit langsung, bukan ditunda: API membaca progres SELAGI tiket diproses."""
    db = _FakeDb()
    crud.set_result_stage(db, "11111111-1111-1111-1111-111111111111", "penilaian_llm")
    assert db.sink["updated"] == {"current_stage": "penilaian_llm"}
    assert db.commits == 1
