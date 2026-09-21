"""Alasan SC_CL_2 untuk B29 menyebut nama on-air DAN nama yang diucapkan agent."""
from qc_core.compliance.call_ownership import stamp_agent_name_reason
from qc_core.compliance.recording_type import stamp_reason_provenance


def _ev(status="BELUM_SESUAI", said="Eveline", reason="Agent tidak menyebut nama yang cocok dengan Ascend."):
    return {"agent_name_said": said, "scorecard_result": [
        {"item_code": "SC_CL_1", "status": "SESUAI", "reason": "salam"},
        {"item_code": "SC_CL_2", "status": status, "reason": reason,
         "evidence": {"ticket_id": "T1_20260902140527", "quote": "saya Eveline"}},
    ]}


def _sc2(ev):
    return next(r for r in ev["scorecard_result"] if r["item_code"] == "SC_CL_2")


def test_b29_menyebut_nama_onair_dan_nama_yang_disebut():
    r = _sc2(stamp_agent_name_reason(_ev(), "LINA"))["reason"]
    assert r == ("Agent tidak menyebutkan nama yang cocok pada perkenalan "
                 "(nama on-air LINA, yang disebut Eveline).")


def test_akhiran_provenance_tetap_menempel_sesudahnya():
    ev = stamp_agent_name_reason(_ev(), "LINA")
    ev = stamp_reason_provenance(ev, {"T1_20260902140527.pdf": {"tag": "recording_utama"}})
    assert _sc2(ev)["reason"] == (
        "Agent tidak menyebutkan nama yang cocok pada perkenalan "
        "(nama on-air LINA, yang disebut Eveline). - Evidence diambil dari recording utama.")


def test_agent_tidak_ada_di_roster_tetap_menghasilkan_kalimat():
    r = _sc2(stamp_agent_name_reason(_ev(), None))["reason"]
    assert "nama on-air tidak tersedia di roster" in r and "yang disebut Eveline" in r


def test_b12_tanpa_nama_yang_disebut_tidak_disentuh():
    ev = _ev(said=None)
    assert stamp_agent_name_reason(ev, "LINA") is ev


def test_sc_cl_2_sesuai_tidak_disentuh():
    ev = _ev(status="SESUAI", reason="Agent menyebut Lina.")
    assert stamp_agent_name_reason(ev, "LINA") is ev


def test_item_lain_tidak_disentuh_dan_idempotent():
    once = stamp_agent_name_reason(_ev(), "LINA")
    assert next(r for r in once["scorecard_result"] if r["item_code"] == "SC_CL_1")["reason"] == "salam"
    assert stamp_agent_name_reason(once, "LINA") is once


def test_evaluasi_kosong_aman():
    assert stamp_agent_name_reason({}, "LINA") == {}
    assert stamp_agent_name_reason(None, "LINA") is None
