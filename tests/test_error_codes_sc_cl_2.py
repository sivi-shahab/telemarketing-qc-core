"""SC_CL_2 (Greeting - nama on-air) -> B12 vs B29 (18 September 2026).

Sejak SC_CL_2 dinilai LLM sepenuhnya (bukan lagi ditimpa regex Python, lihat
call_ownership.py dan worker/tasks/process_transcript.py), pembeda B12/B29 pindah
ke field top-level ``evaluation["agent_name_said"]`` yang diisi LLM sendiri:
kosong/null -> agent sama sekali tidak menyebutkan nama (B12, derivasi kategori
Greeting biasa); terisi -> agent menyebut SUATU nama yang tidak sesuai NAME ONLINE
(B29). Tiket 020455CL3A: LLM benar mengutip nama "Eveline" yang disebut, tapi tidak
sesuai NAME ONLINE "LINA".
"""
from qc_core.compliance.error_codes import build_error_code_table


def _ev(status, agent_name_said=None):
    return {
        "scorecard_result": [
            {"item_code": "SC_CL_2", "category": "Greeting", "status": status,
             "requirement": "Agent menyebutkan nama agent",
             "reason": "test", "item_score": 0},
        ],
        "agent_name_said": agent_name_said,
    }


def test_tidak_menyebut_nama_sama_sekali_jadi_b12():
    rows = build_error_code_table(_ev("BELUM_SESUAI", agent_name_said=None))
    assert [r["error_code"] for r in rows] == ["B12"]


def test_menyebut_nama_lain_jadi_b29():
    rows = build_error_code_table(_ev("BELUM_SESUAI", agent_name_said="Eveline"))
    assert [r["error_code"] for r in rows] == ["B29"]


def test_sesuai_tidak_menerbitkan_kode_apa_pun():
    rows = build_error_code_table(_ev("SESUAI", agent_name_said="Eveline"))
    assert rows == []


def test_agent_name_said_kosong_string_tetap_b12():
    rows = build_error_code_table(_ev("BELUM_SESUAI", agent_name_said=""))
    assert [r["error_code"] for r in rows] == ["B12"]


# --- SC_NTB_2 (padanan SC_CL_2 di campaign NTB) --------------------------------

from qc_core.compliance.call_ownership import stamp_agent_name_reason
from qc_core.compliance.campaign_profile import agent_from_ntb_tms


def _ev_ntb(status, agent_name_said=None):
    return {
        "scorecard_result": [
            {"item_code": "SC_NTB_2", "category": "Greeting", "status": status,
             "requirement": "Agent menyebutkan nama agent",
             "reason": "test", "item_score": 0},
        ],
        "agent_name_said": agent_name_said,
    }


def test_ntb_menyebut_nama_lain_jadi_b29():
    rows = build_error_code_table(_ev_ntb("BELUM_SESUAI", agent_name_said="Maria"))
    assert [r["error_code"] for r in rows] == ["B29"]


def test_ntb_tidak_menyebut_nama_jadi_b12():
    rows = build_error_code_table(_ev_ntb("BELUM_SESUAI", agent_name_said=None))
    assert [r["error_code"] for r in rows] == ["B12"]


def test_ntb_alasan_menyebut_kedua_nama():
    out = stamp_agent_name_reason(_ev_ntb("BELUM_SESUAI", agent_name_said="Maria"), "AYU")
    assert "nama on-air AYU, yang disebut Maria" in out["scorecard_result"][0]["reason"]


def test_agent_ntb_dibaca_dari_tms_ntb_hanya_untuk_campaign_ntb(monkeypatch):
    monkeypatch.delenv("NTB_CAMPAIGNS", raising=False)  # bawaan: "New To Bank Eksternal"
    assert agent_from_ntb_tms("New To Bank Eksternal") and agent_from_ntb_tms(" new to bank eksternal ")
    assert not agent_from_ntb_tms("cashline") and not agent_from_ntb_tms(None)
    monkeypatch.setenv("NTB_CAMPAIGNS", "New To Bank Eksternal, ntb2")
    assert agent_from_ntb_tms("ntb2") and not agent_from_ntb_tms("ntb3")
