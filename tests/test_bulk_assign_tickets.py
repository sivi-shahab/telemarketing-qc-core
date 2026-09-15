"""Auto Assign membagikan SISA, tidak pernah memindahkan tiket orang.

``bulk_assign_tickets_to_qc`` sengaja tidak memanggil ``assign_ticket_to_qc``: fungsi
itu MENIMPA assignment yang ada dan commit per tiket. Tombol Auto Assign hanya boleh
membagikan tiket yang belum dibagi — menimpa berarti memindahkan tiket yang sedang
dikerjakan QC lain, tanpa ada yang memintanya.

Aturan itu tidak terlihat dari tanda tangan fungsinya dan tidak ada test yang
menjaganya di repo asal, jadi dikunci di sini.
"""
from qc_core.db import crud


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDb:
    """Cukup untuk ``db.query(...).all()`` / ``db.add`` / ``db.commit``."""

    def __init__(self, sudah_terbagi=()):
        self._rows = [(t,) for t in sudah_terbagi]
        self.added = []
        self.commits = 0

    def query(self, *a, **k):
        return _FakeQuery(self._rows)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1


def test_tiket_yang_sudah_dibagi_dilewati_bukan_ditimpa():
    db = _FakeDb(sudah_terbagi=["T-1"])
    n = crud.bulk_assign_tickets_to_qc(db, [("T-1", "qc-b"), ("T-2", "qc-b")])
    assert n == 1
    assert [a.ticket_id for a in db.added] == ["T-2"]
    assert all(a.qc_username != "qc-b" or a.ticket_id == "T-2" for a in db.added)


def test_satu_commit_untuk_seluruh_batch():
    db = _FakeDb()
    crud.bulk_assign_tickets_to_qc(db, [("T-1", "a"), ("T-2", "b"), ("T-3", "c")])
    assert len(db.added) == 3
    assert db.commits == 1, "Auto Assign harus satu commit, bukan commit per tiket"


def test_tiket_kembar_dalam_satu_batch_hanya_sekali():
    db = _FakeDb()
    n = crud.bulk_assign_tickets_to_qc(db, [("T-1", "a"), ("T-1", "b")])
    assert n == 1 and len(db.added) == 1


def test_pasangan_kosong_dan_spasi_dibuang():
    db = _FakeDb()
    assert crud.bulk_assign_tickets_to_qc(db, [("", "a"), ("T-1", ""), (None, None)]) == 0
    assert db.added == [] and db.commits == 0
    db2 = _FakeDb()
    crud.bulk_assign_tickets_to_qc(db2, [("  T-9  ", "  qc-a  ")])
    assert db2.added[0].ticket_id == "T-9" and db2.added[0].qc_username == "qc-a"


def test_assigned_by_ikut_tercatat():
    db = _FakeDb()
    crud.bulk_assign_tickets_to_qc(db, [("T-1", "qc-a")], assigned_by_username="tl-1")
    assert db.added[0].assigned_by_username == "tl-1"


def test_tanpa_pasangan_tidak_menyentuh_database():
    """``db=None`` membuktikannya: kalau ada query yang jalan, ini AttributeError."""
    assert crud.bulk_assign_tickets_to_qc(None, []) == 0
    assert crud.bulk_assign_tickets_to_qc(None, None) == 0


def test_manual_status_marks_tanpa_id_tidak_menyentuh_database():
    assert crud.qc_manual_status_marks(None, []) == {}
    assert crud.qc_manual_status_marks(None, ["  ", ""]) == {}


def test_manual_status_marks_menolak_None_di_dalam_daftar():
    """Perilaku APA ADANYA hasil port, didokumentasikan bukan diperbaiki.

    Penyaring id memakai ``str(r).strip()``, sehingga ``None`` berubah menjadi string
    ``"None"`` yang lolos saringan lalu jatuh di ``uuid.UUID("None")``. Daftar berisi
    None karena itu meledak, bukan dilewati. Tidak berbahaya untuk pemanggil yang ada
    (semuanya mengirim result id sungguhan), dan sengaja TIDAK diubah di sini supaya
    hasil port tetap sama persis dengan repo asal — tetapi dikunci supaya perubahannya
    kelak disengaja, bukan tidak sengaja."""
    import pytest

    with pytest.raises(ValueError):
        crud.qc_manual_status_marks(None, [None])
