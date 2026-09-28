"""Cache DWH bersama di Redis (L2) di belakang cache memori per proses (L1).

28 September 2026: halaman Results menembak ±300 request DWH per load dan butuh
5–28 detik, karena cache memori hanya hidup ``DWH_API_CACHE_TTL_SEC`` (di .env = 5
detik) dan terpisah per proses gunicorn. Redis membuat hasilnya bertahan lintas proses
dan restart:

- data ditemukan (200)        -> disimpan ``REDIS_TTL_SEC`` (30 hari)
- tidak ada di DWH (404)      -> hanya ``REDIS_NEG_TTL_SEC`` (1 jam; data bisa masuk belakangan)
- DWH gagal dihubungi         -> TIDAK disimpan
- ``redis_read=False`` (worker evaluasi) -> selalu ambil segar lalu perbarui Redis
- Redis mati                  -> tetap jalan lewat HTTP, tanpa exception

Tanpa jaringan: HTTP dan Redis diganti tiruan.
"""
import json

import pytest

from qc_core.services import data_dwh

BUNDLE = {"cashline": {"agent_id": "A1", "submit_time": "2026-09-24 12:55:27"}, "customer": {"x": 1}}


class FakeRedis:
    def __init__(self, fail=False):
        self.store, self.ttl, self.fail = {}, {}, fail

    def get(self, key):
        if self.fail:
            raise ConnectionError("redis mati")
        return self.store.get(key)

    def set(self, key, value, ex=None):
        if self.fail:
            raise ConnectionError("redis mati")
        self.store[key], self.ttl[key] = value, ex


@pytest.fixture()
def env(monkeypatch):
    calls = []
    answers = {}

    def fake_fetch(url):
        calls.append(url)
        return answers.get(url.rsplit("/", 1)[-1], (None, None))

    monkeypatch.setattr(data_dwh, "_fetch_from_url", fake_fetch)
    fake = FakeRedis()
    monkeypatch.setattr(data_dwh, "_redis_client", lambda: fake)
    monkeypatch.setattr(data_dwh, "_REDIS_READ", True)
    data_dwh.clear_cache()
    yield calls, answers, fake
    data_dwh.clear_cache()


def test_ttl_bawaan_30_hari_dan_negatif_1_jam():
    assert data_dwh.REDIS_TTL_SEC == 30 * 24 * 3600
    assert data_dwh.REDIS_NEG_TTL_SEC == 3600


def test_data_ditemukan_disimpan_30_hari_dan_dipakai_lintas_proses(env):
    calls, answers, fake = env
    answers["C1"] = (BUNDLE, 200)

    assert data_dwh.fetch_bundle("C1") == BUNDLE
    key = data_dwh._redis_key("C1")
    assert json.loads(fake.store[key]) == BUNDLE
    assert fake.ttl[key] == data_dwh.REDIS_TTL_SEC

    data_dwh.clear_cache()          # proses lain / sesudah restart: L1 kosong
    calls.clear()
    assert data_dwh.fetch_bundle_checked("C1") == (BUNDLE, True)
    assert calls == []              # dilayani Redis, tanpa HTTP


def test_tidak_ada_di_dwh_hanya_disimpan_1_jam(env):
    calls, answers, fake = env
    answers["C2"] = (None, 404)     # kedua endpoint 404

    assert data_dwh.fetch_bundle("C2") == {"cashline": None, "customer": None}
    assert fake.ttl[data_dwh._redis_key("C2")] == data_dwh.REDIS_NEG_TTL_SEC


def test_dwh_gagal_dihubungi_tidak_disimpan(env):
    calls, answers, fake = env
    answers["C3"] = (None, None)    # network error / timeout

    bundle, pasti = data_dwh.fetch_bundle_checked("C3")
    assert pasti is False
    assert data_dwh._redis_key("C3") not in fake.store


def test_worker_evaluasi_selalu_ambil_segar_lalu_perbarui_redis(env, monkeypatch):
    calls, answers, fake = env
    fake.store[data_dwh._redis_key("C4")] = json.dumps({"cashline": {"agent_id": "LAMA"}, "customer": None})
    answers["C4"] = (BUNDLE, 200)
    monkeypatch.setattr(data_dwh, "_REDIS_READ", False)

    assert data_dwh.fetch_bundle("C4") == BUNDLE
    assert calls, "harus menembak DWH, bukan memakai Redis"
    assert json.loads(fake.store[data_dwh._redis_key("C4")]) == BUNDLE


def test_redis_mati_tetap_jalan_lewat_http(env, monkeypatch):
    calls, answers, _ = env
    monkeypatch.setattr(data_dwh, "_redis_client", lambda: FakeRedis(fail=True))
    answers["C5"] = (BUNDLE, 200)

    assert data_dwh.fetch_bundle_checked("C5") == (BUNDLE, True)
