"""Client API Microsite (``services.microsite``): bentuk snapshot ``reference_data.microsite_ktp``."""
from unittest import mock

import requests

from qc_core.services import microsite


def _doc(created, data, error=None, warnings=()):
    return {"node_id": "n", "filename": f"KTP_{created}", "document_type": "ktp", "created_at": created,
            "data": data, "warnings": [{"code": w, "message": w} for w in warnings], "error": error}


def test_snapshot_ktp_terbaru_menang_per_field():
    body = {"ticket_id": "T1", "error": None, "skipped": ["selfie: x"], "data": [
        _doc("2026-11-02 10:00:00", {"NIK": "3174071504020006", "NAMA": "BARU", "TTL": ""}, warnings=["mostly_empty"]),
        _doc("2026-11-01 10:00:00", {"NIK": "3174071504020006", "NAMA": "LAMA", "TTL": "JAKARTA, 15-04-2002"}),
        _doc("2026-11-03 10:00:00", {}, error="OCR ktp gagal: HTTP 500"),
        {"document_type": "npwp", "data": {"NAMA": "NPWP"}},
    ]}
    snap = microsite.snapshot_from_response(body)
    assert snap["status"] == microsite.STATUS_OK and snap["error"] is None
    assert snap["values"] == {"nik": "3174071504020006", "nama": "BARU", "tempat_lahir": "JAKARTA", "tanggal_lahir": "2002-04-15"}
    assert [d["created_at"][:10] for d in snap["documents"]] == ["2026-11-01", "2026-11-02", "2026-11-03"]
    assert snap["documents"][1]["warnings"] == ["mostly_empty"] and snap["documents"][2]["error"]


def test_snapshot_tanpa_ktp_dan_error():
    assert microsite.snapshot_from_response({"data": [], "error": None})["status"] == microsite.STATUS_NO_KTP
    assert microsite.snapshot_from_response({"data": [], "error": "Search DMS gagal"})["status"] == microsite.STATUS_ERROR
    assert microsite.snapshot_from_response(None)["status"] == microsite.STATUS_ERROR
    gagal = {"data": [_doc("2026-11-01 10:00:00", {}, error="OCR ktp gagal: timeout")], "error": None}
    assert microsite.snapshot_from_response(gagal)["status"] == microsite.STATUS_ERROR


def test_ttl_tidak_lengkap():
    assert microsite._split_ttl("JAKARTA") == ("JAKARTA", None)
    assert microsite._split_ttl("JAKARTA, 31-02-2002") == ("JAKARTA", None)
    assert microsite._split_ttl("JAKARTA,15/04/2002") == ("JAKARTA", "2002-04-15")
    assert microsite._split_ttl("") == (None, None)


def test_fetch_mati_bila_url_kosong(monkeypatch):
    monkeypatch.setattr(microsite, "MICROSITE_API_BASE_URL", "")
    assert microsite.fetch_ktp("T1") is None


def test_fetch_kirim_api_key_dan_tangani_error(monkeypatch):
    monkeypatch.setattr(microsite, "MICROSITE_API_BASE_URL", "http://ms:8090")
    monkeypatch.setattr(microsite, "MICROSITE_API_KEY", "k")
    ok = mock.Mock(ok=True, status_code=200)
    ok.json.return_value = {"data": [_doc("2026-11-01 10:00:00", {"NIK": "1"})], "error": None}
    with mock.patch.object(microsite.requests, "get", return_value=ok) as get:
        assert microsite.fetch_ktp(" T1 ")["values"] == {"nik": "1"}
    assert get.call_args.args[0] == "http://ms:8090/tickets/T1/ocr/ktp" and get.call_args.kwargs["headers"] == {"X-API-Key": "k"}
    bad = mock.Mock(ok=False, status_code=502, text="Search DMS gagal")
    with mock.patch.object(microsite.requests, "get", return_value=bad):
        assert microsite.fetch_ktp("T1")["status"] == microsite.STATUS_ERROR
    with mock.patch.object(microsite.requests, "get", side_effect=requests.ConnectTimeout("x")):
        assert microsite.fetch_ktp("T1")["status"] == microsite.STATUS_ERROR


def test_values_from_snapshot():
    assert microsite.values_from_snapshot({"values": {"nik": "1"}}) == {"nik": "1"}
    assert microsite.values_from_snapshot(None) == {} and microsite.values_from_snapshot({"values": None}) == {}
