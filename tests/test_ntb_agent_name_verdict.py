"""SC_NTB_2 dan SC_CL_2: status dari kemiripan agent_name_said vs NAME ONLINE (28 Oktober 2026)."""
from qc_core.compliance.call_ownership import apply_ntb_agent_name_verdict


def _ev(said, status="BELUM_SESUAI"):
    return {"agent_name_said": said, "scorecard_result": [
        {"item_code": "SC_NTB_1", "status": "SESUAI", "weight": 1, "item_score": 1},
        {"item_code": "SC_NTB_2", "status": status, "weight": 2, "item_score": 0 if status != "SESUAI" else 2,
         "reason": "llm", "point_of_improvement": "x"},
    ]}


def _sc2(ev):
    return next(r for r in ev["scorecard_result"] if r["item_code"] == "SC_NTB_2")


def test_ejaan_asr_mirip_jadi_sesuai():
    for said, on_air in (("Riska", "FRISKA"), ("Yuda", "YUDHA"), ("Galu", "GALUH")):
        r = _sc2(apply_ntb_agent_name_verdict(_ev(said), on_air))
        assert r["status"] == "SESUAI" and r["item_score"] == 2 and r["point_of_improvement"] is None
        assert said in r["reason"] and on_air in r["reason"]


def test_nama_lain_jadi_belum_sesuai_walau_llm_sesuai():
    for said, on_air in (("Michelle", "FRISCA"), ("Aurel", "ACEL")):
        r = _sc2(apply_ntb_agent_name_verdict(_ev(said, "SESUAI"), on_air))
        assert r["status"] == "BELUM_SESUAI" and r["item_score"] == 0


def test_tidak_memperkenalkan_diri_status_llm_dibiarkan():
    ev = _ev(None)
    assert apply_ntb_agent_name_verdict(ev, "FRISKA") is ev and _sc2(ev)["status"] == "BELUM_SESUAI"


def test_name_online_kosong_tidak_berbuat_apa_apa():
    assert _sc2(apply_ntb_agent_name_verdict(_ev("Riska", "SESUAI"), ""))["status"] == "SESUAI"


def test_nama_depan_dari_nama_lengkap():
    assert _sc2(apply_ntb_agent_name_verdict(_ev("Riska Adetria"), "FRISKA"))["status"] == "SESUAI"


def test_cashline_sc_cl_2_ikut_aturan_yang_sama():
    """Aturan nama agent konsisten antar campaign (28 Oktober 2026)."""
    def ev(said, status):
        return {"agent_name_said": said, "scorecard_result": [
            {"item_code": "SC_CL_2", "status": status, "weight": 2, "item_score": 2 if status == "SESUAI" else 0,
             "reason": "llm", "point_of_improvement": "x"}]}
    r = apply_ntb_agent_name_verdict(ev("Eveline", "SESUAI"), "EFELIN")["scorecard_result"][0]
    assert r["status"] == "BELUM_SESUAI" and r["item_score"] == 0          # 71,4% < 75%
    r = apply_ntb_agent_name_verdict(ev("Riska", "BELUM_SESUAI"), "FRISKA")["scorecard_result"][0]
    assert r["status"] == "SESUAI" and r["item_score"] == 2
    e = ev(None, "BELUM_SESUAI")
    assert apply_ntb_agent_name_verdict(e, "FRISKA") is e                  # tidak memperkenalkan diri: B12


def test_item_lain_tidak_disentuh():
    ev = {"agent_name_said": "Eveline", "scorecard_result": [{"item_code": "SC_CL_3", "status": "SESUAI", "weight": 2}]}
    assert apply_ntb_agent_name_verdict(ev, "LINA")["scorecard_result"][0]["status"] == "SESUAI"


def test_ekstraksi_llm_keliru_tapi_kode_mencocokkan_tetap_sesuai():
    """Tiket 0105265aTJ: agent_name_said terisi nama nasabah; kode menemukan "galu" ~ GALUH."""
    chk = {"match": True, "detected": ["memang"], "score": 80.0,
           "reason": 'Nama "galu" di transkrip cocok dengan NAME ONLINE "GALUH" (80%).'}
    ev = _ev("Bu Silvia Franjiska"); ev["customer_full_name"] = "Silvia Fransiska"
    r = _sc2(apply_ntb_agent_name_verdict(ev, "GALUH", chk))
    assert r["status"] == "SESUAI" and r["item_score"] == 2
    assert r["reason"] == chk["reason"]


def test_keduanya_tidak_cocok_tetap_belum_sesuai():
    chk = {"match": False, "detected": ["kan"], "score": 0.0, "reason": "tidak ditemukan"}
    for said, on_air in (("Michelle", "FRISCA"), ("Aurel", "ACEL")):
        assert _sc2(apply_ntb_agent_name_verdict(_ev(said, "SESUAI"), on_air, chk))["status"] == "BELUM_SESUAI"


def test_cadangan_kode_tidak_dipakai_bila_nama_agent_masuk_akal():
    """130957fnu6: agent "Daffa", on-air ZAFRAN; "jafran" muncul di tempat lain -> tetap BELUM_SESUAI."""
    chk = {"match": True, "detected": ["Daffa"], "score": 83.3,
           "reason": 'Nama "jafran" di transkrip cocok dengan NAME ONLINE "ZAFRAN" (83%).'}
    ev = _ev("Daffa", "SESUAI"); ev["customer_full_name"] = "Budi Santoso"
    assert _sc2(apply_ntb_agent_name_verdict(ev, "ZAFRAN", chk))["status"] == "BELUM_SESUAI"
