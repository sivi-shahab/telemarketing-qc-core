"""``qc_auto_assign``: rata per campaign dan total sekaligus (13 Oktober 2026).

Salinan uji di telemarketing-qc-api (tests/test_qc_assignment_auto.py dan
tests/test_qc_auto_assign_schedule.py) — modul ini disinkronkan manual ke sana.
"""
import random

from qc_core import qc_auto_assign as auto


def _spread(pairs, qcs, campaign_of, campaign=None):
    counts = {q: 0 for q in qcs}
    for t, q in pairs:
        if campaign is None or campaign_of.get(t) == campaign:
            counts[q] += 1
    return max(counts.values()) - min(counts.values())


def test_rata_per_campaign_dan_total():
    qcs = ["a", "b", "c", "d"]
    sizes = {"Personal Loan": 11, "Megapay": 7, "CashLine NTB": 5, "Reinstate": 2}
    campaign_of = {f"{c}-{i}": c for c, n in sizes.items() for i in range(n)}
    pool = list(campaign_of)
    for seed in range(50):
        pairs = auto.distribute_evenly(pool, qcs, rnd=random.Random(seed), campaign_of=campaign_of)
        assert sorted(t for t, _ in pairs) == sorted(pool)
        assert _spread(pairs, qcs, campaign_of) <= 1
        for c in sizes:
            assert _spread(pairs, qcs, campaign_of, c) <= 1, (seed, c)


def test_tanpa_campaign_tetap_rata_total():
    pairs = auto.distribute_evenly([f"t{i}" for i in range(7)], ["a", "b", "c"], rnd=random.Random(1))
    assert _spread(pairs, ["a", "b", "c"], {}) <= 1


def test_campaign_map_app_c_dulu_lalu_result(monkeypatch):
    monkeypatch.setattr(auto.crud, "campaign_by_ticket_ids", lambda db, ids: {"t1": "Cashline", "t2": "Cashline"})
    monkeypatch.setattr(auto.tickets_daily, "fetch_all",
                        lambda **k: {"items": [{"id": "t1", "campaign": "Personal Loan"}]})
    assert auto.campaign_map(None, ["t1", "t2"]) == {"t1": "Personal Loan", "t2": "Cashline"}


def test_campaign_map_app_c_mati_tidak_memblokir(monkeypatch):
    monkeypatch.setattr(auto.crud, "campaign_by_ticket_ids", lambda db, ids: {"t1": "Cashline"})

    def boom(**k):
        raise auto.tickets_daily.TicketsDailyError("down")

    monkeypatch.setattr(auto.tickets_daily, "fetch_all", boom)
    assert auto.campaign_map(None, ["t1"]) == {"t1": "Cashline"}
