"""Cache App A yang CARD HOLDER-nya null tidak boleh dipercaya di worker.

Regresi yang dijaga (21 Oktober 2026): endpoint cache App A
(``/campaign/cashline-ntb-asscend``) menyimpan baris dengan cashline terisi tetapi
``customer`` null, dan tidak memperbaruinya setelah card holder masuk DWH. Karena
jawabannya HTTP 200, endpoint asli tidak pernah ditanya: 7 dari 9 tiket PENDING
"Data Ascend Kosong" sebenarnya sudah punya card holder di endpoint asli, dan
retry data acuan 30 menit terus melaporkannya ``still_missing``.

Bundle seperti itu juga tidak boleh tinggal 30 hari di Redis: halaman Results
membaca L2 dan ikut melihat card holder kosong.
"""
import pytest

from qc_core.services import data_dwh

CL = {"customer_name": "A", "agent_id": "san801", "submit_time": "2026-10-21 08:03:49"}
CACHE_BASI = {"cashline": CL, "customer": None}
ASLI = {"cashline": CL, "customer": {"cust_name": "A"}}


class _Resp:
    def __init__(self, status, body=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._body = body
        self.text = ""

    def json(self):
        return self._body


class FakeRedis:
    def __init__(self):
        self.store, self.ttl = {}, {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key], self.ttl[key] = value, ex


@pytest.fixture()
def dwh(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(data_dwh, "_redis_client", lambda: fake)

    def _setup(asli):
        calls = []

        def fake_get(url, timeout=None):
            calls.append(url)
            if "cashline-ntb-asscend" in url:
                return _Resp(200, CACHE_BASI)
            return _Resp(200, asli)

        monkeypatch.setattr(data_dwh.requests, "get", fake_get)
        data_dwh.clear_cache()
        return calls

    yield _setup, fake
    data_dwh.set_fill_cashline_ids(False)
    data_dwh.clear_cache()


def test_customer_null_di_cache_ditanyakan_ke_endpoint_asli(dwh):
    setup, _ = dwh
    data_dwh.set_fill_cashline_ids(True)
    calls = setup(ASLI)
    bundle, pasti = data_dwh.fetch_bundle_checked("070817PDvt")
    assert pasti is True
    assert bundle == ASLI
    assert len(calls) == 2


def test_endpoint_asli_juga_null_tetap_kosong(dwh):
    setup, _ = dwh
    data_dwh.set_fill_cashline_ids(True)
    setup(CACHE_BASI)
    bundle, pasti = data_dwh.fetch_bundle_checked("090857V6fU")
    assert pasti is True
    assert bundle["customer"] is None


def test_halaman_api_tanpa_flag_tidak_menunggu_endpoint_asli(dwh):
    setup, _ = dwh
    calls = setup(ASLI)
    assert data_dwh.fetch_bundle_checked("X1")[0] == CACHE_BASI
    assert len(calls) == 1


def test_bundle_tanpa_customer_di_redis_hanya_ttl_negatif(dwh):
    setup, fake = dwh
    setup(ASLI)
    data_dwh.fetch_bundle_checked("X2")
    assert fake.ttl[data_dwh._redis_key("X2")] == data_dwh.REDIS_NEG_TTL_SEC


def test_bundle_lengkap_di_redis_tetap_30_hari(dwh):
    setup, fake = dwh
    data_dwh.set_fill_cashline_ids(True)
    setup(ASLI)
    data_dwh.fetch_bundle_checked("X3")
    assert fake.ttl[data_dwh._redis_key("X3")] == data_dwh.REDIS_TTL_SEC
