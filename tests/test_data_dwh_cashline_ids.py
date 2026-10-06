"""Cache App A yang belum memuat ``agent_id``/``submit_time`` tidak boleh dipercaya.

Regresi yang dijaga (6 Oktober 2026): 176 dari 350 snapshot ``reference_data``
Cashline tidak punya key ``agent_id`` & ``submit_time`` (30 field, bukan 32).
Endpoint cache App A (``/campaign/cashline-ntb-asscend``) masih menyimpan baris lama
yang dibuat sebelum kedua field itu masuk daftar field cache-nya, dan karena
jawabannya HTTP 200, endpoint asli tidak pernah ditanya. Akibatnya tiket "Agent
Tidak Terpetakan" dan tenggat H+2 dianggap lewat (submit_time kosong).

Pengisian ulang hanya aktif di worker / skrip backfill (``set_fill_cashline_ids``)
— halaman API tidak boleh menunggu endpoint asli yang lambat untuk setiap tiket.
"""
import pytest
import requests

from qc_core.services import data_dwh

CACHE_LAMA = {"cashline": {"customer_name": "A", "limit": "10"}, "customer": {"x": 1}}
ASLI = {"cashline": {"customer_name": "A", "limit": "10", "agent_id": "san801",
                     "submit_time": "2026-09-25 14:57:39"}, "customer": {"x": 1}}


class _Resp:
    def __init__(self, status, body=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._body = body
        self.text = ""

    def json(self):
        return self._body


@pytest.fixture()
def dwh(monkeypatch):
    def _setup(asli):
        calls = []

        def fake_get(url, timeout=None):
            calls.append(url)
            if "cashline-ntb-asscend" in url:
                return _Resp(200, CACHE_LAMA)
            return asli(url)

        monkeypatch.setattr(data_dwh.requests, "get", fake_get)
        data_dwh.clear_cache()
        return calls

    yield _setup
    data_dwh.set_fill_cashline_ids(False)
    data_dwh.clear_cache()


def test_cache_tanpa_agent_id_jatuh_ke_endpoint_asli(dwh):
    data_dwh.set_fill_cashline_ids(True)
    calls = dwh(lambda url: _Resp(200, ASLI))
    bundle, pasti = data_dwh.fetch_bundle_checked("191025vctb")
    assert pasti is True
    assert bundle["cashline"]["agent_id"] == "san801"
    assert bundle["cashline"]["submit_time"] == "2026-09-25 14:57:39"
    assert len(calls) == 2


def test_endpoint_asli_gagal_tetap_pakai_cache(dwh):
    data_dwh.set_fill_cashline_ids(True)

    def boom(url):
        raise requests.Timeout("lambat")

    dwh(boom)
    bundle, pasti = data_dwh.fetch_bundle_checked("X9")
    assert pasti is True
    assert bundle == CACHE_LAMA


def test_tanpa_flag_perilaku_lama_satu_panggilan(dwh):
    calls = dwh(lambda url: _Resp(200, ASLI))
    bundle, _ = data_dwh.fetch_bundle_checked("X10")
    assert bundle == CACHE_LAMA
    assert len(calls) == 1


def test_key_ada_walau_null_tidak_memicu_fallback(dwh, monkeypatch):
    data_dwh.set_fill_cashline_ids(True)
    lengkap = {"cashline": {"agent_id": None, "submit_time": None}, "customer": None}
    calls = []

    def fake_get(url, timeout=None):
        calls.append(url)
        return _Resp(200, lengkap)

    monkeypatch.setattr(data_dwh.requests, "get", fake_get)
    data_dwh.clear_cache()
    assert data_dwh.fetch_bundle_checked("X11")[0] == lengkap
    assert len(calls) == 1
