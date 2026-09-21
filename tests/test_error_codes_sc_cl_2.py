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
