"""Ganti NIP memindahkan semua kolom username (20 Oktober 2026).

``rename_username`` meng-update tiap kolom di ``USERNAME_COLUMNS`` dengan pencocokan
``lower(trim(...))`` dan TIDAK commit; test introspeksi memastikan kolom ``*_username``
baru di model mana pun tidak terlewat.
"""
from types import SimpleNamespace

import pytest

from qc_core.db import crud, models


class _RecQ:
    def __init__(self, db):
        self._db = db
        self._filter = None

    def filter(self, expr):
        self._filter = expr
        return self

    def update(self, values, synchronize_session=None):
        self._db.updates.append(SimpleNamespace(filter=self._filter, values=values))
        return self._db.rowcount


class _RecordingDb:
    def __init__(self, rowcount):
        self.rowcount = rowcount
        self.updates = []
        self.commits = 0

    def query(self, model):
        return _RecQ(self)

    def commit(self):
        self.commits += 1


def test_semua_kolom_username_terdaftar():
    # Kolom *_username baru di model mana pun wajib masuk USERNAME_COLUMNS.
    found = {(m.__tablename__, c.name) for m in models.Base.__subclasses__() if hasattr(m, "__table__")
             for c in m.__table__.columns if c.name.endswith("_username") or c.name == "qc_username"}
    found -= {("user_change_events", "target_username")}
    listed = {(m.__tablename__, c) for m, c in crud.USERNAME_COLUMNS}
    assert found == listed


def test_rename_cocok_case_insensitive_dan_trim():
    db = _RecordingDb(rowcount=2)
    out = crud.rename_username(db, " QC7 ", "21000001")
    assert len(db.updates) == len(crud.USERNAME_COLUMNS)
    sql = str(db.updates[0].filter.compile(compile_kwargs={"literal_binds": True}))
    assert "lower(trim(" in sql and "'qc7'" in sql
    assert all(list(u.values.values()) == ["21000001"] for u in db.updates)
    assert db.commits == 0 and sum(out.values()) == 2 * len(crud.USERNAME_COLUMNS)


def test_rename_kosong_ditolak():
    with pytest.raises(ValueError):
        crud.rename_username(_RecordingDb(0), "qc7", "  ")
