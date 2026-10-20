"""Bagian murni (tanpa DB) dari filter tanggal ``load_date`` App C (20 Oktober 2026).

Test lengkapnya (``test_ticket_load_dates``, ``test_stats_load_date``,
``test_results_filter_load_date``, ``test_load_date_sync``) memakai fixture ``db`` +
``ticket_load_dates_table`` dan tinggal di repo api; suite core tidak punya Postgres.
"""
from datetime import date

from qc_core.compliance import stats_aggregate as sa
from qc_core.db import crud
from qc_core.services import load_date_sync


def d(day):
    return date(2026, 10, day)


def test_input_kosong_tanpa_query():
    # Tanpa sesi DB: kalau fungsi ini sampai membuat query, ``None.query`` akan error.
    assert crud.load_dates_by_ticket(None, []) == {}


def test_recent_dates():
    assert load_date_sync.recent_dates(d(19), 3) == [d(16), d(17), d(18), d(19)]


def test_ticketdates_single_dan_window():
    td = sa.TicketDates((d(10), d(15)), d(1))
    assert td.single() == d(15)
    assert td.in_window(d(12), d(17))
    assert sa.TicketDates((), d(14)).in_window(d(12), d(17))
    multi = sa.TicketDates((d(14), d(16), d(19)), None)
    assert multi.single() == d(19)
    assert not multi.in_window(d(12), d(17))
    assert not sa.TicketDates((), None).in_window(None, None)
    assert sa.TicketDates((d(12),), None).in_window(d(12), None)
    assert sa.TicketDates((d(12),), None).in_window(None, d(12))
