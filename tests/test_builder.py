"""Builder: heuristik deterministik (varian, pembaca KB longgar, evidence rule, prompt, validasi) dan izin akun."""
import json

from qc_core.builder import assemble, drafting


def test_applies_to_dan_varian_tidak_jelas():
    assert assemble.applies_to_for("Pengisian Data (Agree Supplement)") == "SUPL"
    assert assemble.applies_to_for("T&C Product Mega Ultima Shield") == "MUS"
    assert assemble.applies_to_for("Greeting") is None
    # kategori gabungan tidak ditebak, tetapi ditandai agar manusia memilih
    gabungan = "Final Konfirmasi Basic + Supplement + Mega Ultima Shield"
    assert assemble.applies_to_for(gabungan) is None and assemble.variant_unclear(gabungan)
    assert not assemble.variant_unclear("Greeting")


def test_evidence_rule_menurut_kategori():
    assert drafting.evidence_rule_for("Greeting")["phase_scope"] == "ANY"
    assert drafting.evidence_rule_for("Final Konfirmasi Basic")["phase_scope"] == "FINAL_CONFIRMATION"
    assert drafting.evidence_rule_for("Closing")["prefer"] == "MENTION_IN_CLOSING"


def test_kb_cashline_bentuk_longgar_terbaca():
    # kunci fase langsung di dalam array, baris baru mentah dalam string, dan `""` nyasar sebelum `]`
    text = '[\n\t"conversation_phases": {"A": {"description": "x"}},\n\t{"kb_code": "KB_1", "category": "A", ' \
           '"requirement": "r", "example_phrases": ["satu\nbaris", "dua""\n\t\t]}\n]'
    kb = drafting.parse_kb_lenient(text)
    assert kb is not None and kb[1]["kb_code"] == "KB_1"
    assert drafting.parse_kb_lenient("bukan json") is None


def test_keyword_overlap_dan_fakta():
    assert drafting.keyword_overlap("Agent menanyakan kesediaan waktu nasabah", "Boleh minta waktunya sebentar")
    assert not drafting.keyword_overlap("Agent menanyakan kesediaan waktu nasabah", "Boleh kami lanjutkan sebentar ya")
    corpus = drafting.norm("premi 0,68 persen dari total tagihan")
    assert drafting.fact_flags(["Premi Mega Ultima Shield 0,5%"], corpus) == ["0,5%", "Mega Ultima Shield"]


def test_build_prompt_ganti_nama_dan_peringatan_rujukan():
    base = "Item SC_NTB_4 dan SC_NTB_66-70 di KB_NTB_4. Campaign NTB (New to Bank). NTB VARIANT.\nKampanye NTB biasa."
    text, notes = assemble.build_prompt(base, "ntb", "RI2", "Reinstate2")
    assert "SC_RI2_4" in text and "KB_RI2_4" in text and "SC_NTB_" not in text
    assert "REINSTATE2 VARIANT" in text and "Kampanye Reinstate2 biasa" in text and "NTB (New to Bank)" in text
    assert any("rujukan" in n for n in notes)


def _draft(items):
    return {"items": items}


def _item(code, decision="accepted", source="BARU", weight=2, flags=None, **kw):
    return {"item_code": code, "category": "Greeting", "requirement": "Agent ...", "weight": weight, "tolerable": "NO",
            "applies_to": None, "source": source, "decision": decision, "flags": flags or [],
            "kb": {"example_phrases": [], "scoring_rule": "r"}, **kw}


def test_validasi_blokir_item_kosong_dan_penting_tanpa_tinjau():
    d = _draft([_item("SC_X_1"), _item("SC_X_2", source="BELUM", decision="pending"),
                _item("SC_X_3", weight=5, flags=["penting"])])
    sc, kb = assemble.build_scorecard(d), assemble.build_kb(d)
    v = assemble.validate(d, sc, kb, "prompt")
    assert any("belum diisi" in e for e in v["errors"]) and any("penting" in e for e in v["errors"])
    d["items"][1]["decision"] = "rejected"
    d["items"][2]["ditinjau_manual"] = True
    assert assemble.validate(d, assemble.build_scorecard(d), assemble.build_kb(d), "prompt")["errors"] == []
    assert json.loads(assemble.build_kb(d))[0]["conversation_phases"].keys() == {"Greeting"}
