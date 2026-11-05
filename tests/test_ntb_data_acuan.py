"""Data acuan campaign New To Bank Eksternal (5 November 2026).

NTB hanya punya baris TMS NTB di App A (``/campaign/new-to-bank-eksternal/{id}``) —
tanpa TMS Cashline dan tanpa card holder Ascend. Test ini menjaga tiga kabel:
deteksi campaign (``NTB_CAMPAIGNS``), klien endpoint NTB, dan keputusan retry data
acuan untuk rencana NTB (di repo worker). Tanpa DB/Redis/DWH.
"""
import json
from datetime import datetime

import pytest
import requests

NOW = datetime(2026, 11, 5, 3, 30)


# --- deteksi campaign --------------------------------------------------------------

def test_is_ntb_bawaan_new_to_bank_eksternal(monkeypatch):
    from qc_core.compliance.campaign_kind import is_ntb

    monkeypatch.delenv("NTB_CAMPAIGNS", raising=False)
    assert is_ntb("New To Bank Eksternal")
    assert is_ntb("  new to bank eksternal ")
    assert not is_ntb("Cashline")
    assert not is_ntb(None)


def test_is_ntb_env_kosong_mematikan(monkeypatch):
    from qc_core.compliance.campaign_kind import is_ntb

    monkeypatch.setenv("NTB_CAMPAIGNS", "")
    assert not is_ntb("New To Bank Eksternal")


# --- klien endpoint NTB ------------------------------------------------------------

class _Resp:
    def __init__(self, status, body=None, text=""):
        self.status_code = status
        self._body = body
        self.text = text
        self.ok = 200 <= status < 300

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def _get(monkeypatch, resp):
    from qc_core.services import data_dwh

    seen = []

    def fake(url, timeout):
        seen.append(url)
        if isinstance(resp, Exception):
            raise resp
        return resp

    monkeypatch.setattr(data_dwh.requests, "get", fake)
    return data_dwh, seen


def test_fetch_ntb_200(monkeypatch):
    row = {"result_id": "040845DQJG", "agent_id": "fikri801"}
    data_dwh, seen = _get(monkeypatch, _Resp(200, {"campaign": row}))

    assert data_dwh.fetch_ntb_checked(" 040845DQJG ") == (row, True)
    assert seen[0].endswith("/campaign/new-to-bank-eksternal/040845DQJG")


def test_fetch_ntb_404_berarti_pasti_kosong(monkeypatch):
    data_dwh, _ = _get(monkeypatch, _Resp(404, {"detail": "x"}))
    assert data_dwh.fetch_ntb_checked("0101073k1C") == (None, True)


@pytest.mark.parametrize("resp", [
    _Resp(500, text="boom"),
    _Resp(200, ValueError("bukan json")),
    requests.ConnectionError("down"),
])
def test_fetch_ntb_gagal_bukan_bukti_kosong(monkeypatch, resp):
    data_dwh, _ = _get(monkeypatch, resp)
    assert data_dwh.fetch_ntb_checked("x") == (None, False)


def test_fetch_ntb_id_kosong_tanpa_http(monkeypatch):
    data_dwh, seen = _get(monkeypatch, _Resp(200, {"campaign": {}}))
    assert data_dwh.fetch_ntb_checked("  ") == (None, True)
    assert seen == []
