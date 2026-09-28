"""Helper cache Redis bersama (``services/redis_cache.py``).

Dipakai ``crud.result_json_map`` untuk JSON hasil evaluasi (28 September 2026):
mengambil 18 MB JSON dari Postgres remote makan 3,6 detik per halaman Pending
Check/Statistics, padahal baris ``result_data`` tidak pernah diubah sesudah
tersimpan. Redis opsional: tanpa ``REDIS_URL`` atau saat Redis bermasalah, helper
mengembalikan "tidak ada" dan pemanggil jatuh ke Postgres.
"""
import pytest

from qc_core.services import redis_cache


class FakePipe:
    def __init__(self, r):
        self.r, self.ops = r, []

    def set(self, key, value, ex=None):
        self.ops.append((key, value, ex))
        return self

    def execute(self):
        if self.r.fail:
            raise ConnectionError("redis mati")
        for k, v, ex in self.ops:
            self.r.store[k], self.r.ttl[k] = v.encode() if isinstance(v, str) else v, ex
        return [True] * len(self.ops)


class FakeRedis:
    def __init__(self, fail=False):
        self.store, self.ttl, self.fail = {}, {}, fail

    def mget(self, keys):
        if self.fail:
            raise ConnectionError("redis mati")
        return [self.store.get(k) for k in keys]

    def pipeline(self, transaction=False):
        return FakePipe(self)


@pytest.fixture()
def fake(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(redis_cache, "_client", lambda: r)
    redis_cache.reset()
    yield r
    redis_cache.reset()


def test_ttl_bawaan_30_hari():
    assert redis_cache.DEFAULT_TTL_SEC == 30 * 24 * 3600


def test_set_lalu_get_many(fake):
    redis_cache.set_many({"a": "1", "b": "2"})
    assert redis_cache.get_many(["a", "b", "c"]) == {"a": "1", "b": "2"}
    assert fake.ttl["a"] == redis_cache.DEFAULT_TTL_SEC


def test_daftar_kosong_tidak_menyentuh_redis(monkeypatch):
    monkeypatch.setattr(redis_cache, "_client", lambda: (_ for _ in ()).throw(AssertionError("disentuh")))
    assert redis_cache.get_many([]) == {}
    redis_cache.set_many({})


def test_redis_mati_mengembalikan_kosong_dan_berhenti_mencoba(monkeypatch):
    r = FakeRedis(fail=True)
    calls = []
    monkeypatch.setattr(redis_cache, "_client", lambda: calls.append(1) or r)
    redis_cache.reset()

    assert redis_cache.get_many(["a"]) == {}
    redis_cache.set_many({"a": "1"})          # tidak melempar
    assert len(calls) == 1                    # sesudah gagal, jeda — tidak dicoba lagi
    redis_cache.reset()


class FakeLockRedis(FakeRedis):
    def set(self, key, value, ex=None, nx=False):
        if self.fail:
            raise ConnectionError("redis mati")
        if nx and key in self.store:
            return None
        self.store[key], self.ttl[key] = value, ex
        return True

    def delete(self, key):
        self.store.pop(key, None)


def test_kunci_hanya_didapat_sekali_sampai_dilepas(monkeypatch):
    r = FakeLockRedis()
    monkeypatch.setattr(redis_cache, "_client", lambda: r)
    redis_cache.reset()

    assert redis_cache.acquire("lock:a", ttl_sec=60) is True
    assert r.ttl["lock:a"] == 60
    assert redis_cache.acquire("lock:a", ttl_sec=60) is False
    redis_cache.release("lock:a")
    assert redis_cache.acquire("lock:a", ttl_sec=60) is True


def test_kunci_tanpa_redis_tetap_boleh_jalan(monkeypatch):
    """Redis mati/tidak dikonfigurasi: jangan memblokir pekerjaan (fail-open) —
    dobel hitung lebih baik daripada snapshot tidak pernah diperbarui."""
    monkeypatch.setattr(redis_cache, "_client", lambda: FakeLockRedis(fail=True))
    redis_cache.reset()
    assert redis_cache.acquire("lock:b", ttl_sec=60) is True
    redis_cache.reset()
    monkeypatch.setattr(redis_cache, "_client", lambda: None)
    assert redis_cache.acquire("lock:c", ttl_sec=60) is True
