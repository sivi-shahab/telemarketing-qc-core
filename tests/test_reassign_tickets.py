"""Bagi ulang tiket QC nonaktif memindahkan tiket BER-PEMILIK (19 Oktober 2026).

``reassign_tickets_to_qc`` kebalikan ``bulk_assign_tickets_to_qc``: hanya tiket yang
masih punya assignment yang dipindah (tiket yang di sela itu dilepas orang lain tidak
dihidupkan lagi), tiap perpindahan dicatat ``reassign`` dengan pemegang lamanya, dan
semuanya satu commit.
"""
from datetime import datetime
from types import SimpleNamespace

from qc_core.db import crud
from qc_core.db.models import QcAssignmentEvent


class _Q:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *a, **k):
        return self

    def all(self):
        return self._rows


class _Db:
    def __init__(self, rows):
        self._rows = rows
        self.added = []
        self.commits = 0

    def query(self, *a, **k):
        return _Q(self._rows)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1


def _row(tid, qc):
    return SimpleNamespace(ticket_id=tid, qc_username=qc, assigned_by_username="tl",
                           assigned_at=datetime(2026, 10, 19, 1, 0))


def test_tiket_dipindah_dan_dicatat_reassign_dengan_pemegang_lama():
    rows = [_row("T-1", "qc-lama"), _row("T-2", "qc-lama")]
    db = _Db(rows)

    n = crud.reassign_tickets_to_qc(db, [("T-1", "qc-a"), ("T-2", "qc-b")],
                                    assigned_by_username="scheduler")

    assert n == 2 and db.commits == 1
    assert [(r.ticket_id, r.qc_username, r.assigned_by_username) for r in rows] == [
        ("T-1", "qc-a", "scheduler"), ("T-2", "qc-b", "scheduler")]
    assert all(r.assigned_at > datetime(2026, 10, 19, 1, 0) for r in rows)
    events = [e for e in db.added if isinstance(e, QcAssignmentEvent)]
    assert [(e.ticket_id, e.action, e.previous_qc_username, e.qc_username, e.source)
            for e in events] == [
        ("T-1", "reassign", "qc-lama", "qc-a", "qc_nonaktif"),
        ("T-2", "reassign", "qc-lama", "qc-b", "qc_nonaktif")]


def test_tiket_yang_sudah_dilepas_tidak_dihidupkan_lagi():
    db = _Db([_row("T-1", "qc-lama")])  # T-2 sudah tidak punya baris

    n = crud.reassign_tickets_to_qc(db, [("T-1", "qc-a"), ("T-2", "qc-a")])

    assert n == 1
    assert [e.ticket_id for e in db.added] == ["T-1"]


def test_kosong_tidak_commit():
    db = _Db([])
    assert crud.reassign_tickets_to_qc(db, []) == 0
    assert crud.reassign_tickets_to_qc(db, [("T-1", "qc-a")]) == 0
    assert db.commits == 0
