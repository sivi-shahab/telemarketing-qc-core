"""fetch_bundle_checked: gangguan DWH tidak boleh terbaca sebagai "data acuan kosong".

Gerbang PENDING di worker menilai tiket tanpa baris TMS/Ascend sebagai PENDING tanpa
memanggil LLM. Kalau bundle kosong akibat DWH down ikut diperlakukan begitu, tiket
ditandai PENDING tanpa pernah dinilai dan tidak diulang otomatis.
"""
import requests

from qc_core.services import data_dwh


class _Resp:
    def __init__(self, status, body=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._body = body
        self.text = ""

    def json(self):
        return self._body


def _patch_get(monkeypatch, responder):
    calls = []

    def fake_get(url, timeout=None):
        calls.append(url)
        return responder(url)

    monkeypatch.setattr(data_dwh.requests, "get", fake_get)
    data_dwh.clear_cache()
    return calls


def test_404_di_kedua_endpoint_pasti_kosong_dan_dicache(monkeypatch):
    calls = _patch_get(monkeypatch, lambda url: _Resp(404))
    assert data_dwh.fetch_bundle_checked("X1") == ({"cashline": None, "customer": None}, True)
    assert data_dwh.fetch_bundle_checked("X1")[1] is True
    assert len(calls) == 2  # panggilan kedua kena cache


def test_network_error_tidak_pasti_dan_tidak_masuk_cache_data(monkeypatch):
    def boom(url):
        raise requests.ConnectionError("down")

    _patch_get(monkeypatch, boom)
    bundle, pasti = data_dwh.fetch_bundle_checked("X2")
    assert bundle == {"cashline": None, "customer": None}
    assert pasti is False
    # Diingat sebentar sebagai GAGAL, bukan sebagai data kosong.
    assert data_dwh.fetch_bundle_checked("X2")[1] is False

    # Setelah DWH pulih (cache dibersihkan / TTL gagal lewat) data nyata terbaca.
    calls = _patch_get(monkeypatch, lambda url: _Resp(200, {"cashline": {"a": 1}, "customer": None}))
    assert data_dwh.fetch_bundle_checked("X2") == ({"cashline": {"a": 1}, "customer": None}, True)
    assert len(calls) == 1


def test_http_500_tidak_pasti(monkeypatch):
    _patch_get(monkeypatch, lambda url: _Resp(500))
    assert data_dwh.fetch_bundle_checked("X3")[1] is False


def test_fetch_bundle_tetap_mengembalikan_dict(monkeypatch):
    _patch_get(monkeypatch, lambda url: _Resp(500))
    assert data_dwh.fetch_bundle("X4") == {"cashline": None, "customer": None}
