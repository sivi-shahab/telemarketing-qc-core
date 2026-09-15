"""Unit test klasifikasi jenis recording, dengan klien LLM tiruan.

Yang diuji di sini bukan mutu penilaian model — itu tidak bisa dikunci di unit test —
melainkan JARING PENGAMAN-nya: setiap kali klasifikasi tidak bisa dipercaya, seluruh
rekaman harus tetap dinilai. Salah di arah sebaliknya berarti transkrip hilang diam-diam
dari penilaian.
"""
import json

from qc_core.compliance import recording_type as R
from qc_core.prompt.recording_type import (
    TAG_DITUNDA,
    TAG_LAINNYA,
    TAG_PEMBATALAN,
    TAG_PERBAIKAN,
    TAG_UTAMA,
)


# --------------------------------------------------------------------------
# Klien OpenAI-compatible tiruan
# --------------------------------------------------------------------------

class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Completions:
    def __init__(self, content, raises=False):
        self._content = content
        self._raises = raises
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises:
            raise RuntimeError("LLM tidak bisa dihubungi")
        return _Resp(self._content)


class _Chat:
    def __init__(self, completions):
        self.completions = completions


class _Client:
    def __init__(self, content=None, raises=False):
        self.chat = _Chat(_Completions(content, raises))


def _items(*names):
    return [{"file": n, "duration": "5m 0s", "text": f"isi {n}"} for n in names]


def _payload(mapping):
    return json.dumps({
        "recordings": [
            {"file": f, "tag": t, "reason": "alasan"} for f, t in mapping.items()
        ]
    })


# --------------------------------------------------------------------------
# classify_recordings
# --------------------------------------------------------------------------

def test_memetakan_tag_per_berkas():
    client = _Client(_payload({"a.pdf": TAG_UTAMA, "b.pdf": TAG_PEMBATALAN}))
    out = R.classify_recordings(_items("a.pdf", "b.pdf"), client, "m")
    assert out["a.pdf"]["tag"] == TAG_UTAMA
    assert out["b.pdf"]["tag"] == TAG_PEMBATALAN
    assert out["b.pdf"]["reason"] == "alasan"


def test_satu_panggilan_llm_untuk_seluruh_tiket():
    client = _Client(_payload({"a.pdf": TAG_UTAMA, "b.pdf": TAG_PERBAIKAN}))
    R.classify_recordings(_items("a.pdf", "b.pdf"), client, "m")
    assert len(client.chat.completions.calls) == 1


def test_tanpa_rekaman_tidak_memanggil_llm():
    client = _Client(_payload({}))
    assert R.classify_recordings([], client, "m") == {}
    assert client.chat.completions.calls == []


def test_llm_gagal_tidak_melempar_dan_tidak_menyaring():
    client = _Client(raises=True)
    assert R.classify_recordings(_items("a.pdf"), client, "m") == {}


def test_balasan_bukan_json_diabaikan():
    client = _Client("maaf, saya tidak bisa membantu")
    assert R.classify_recordings(_items("a.pdf"), client, "m") == {}


def test_json_berpagar_kode_tetap_terbaca():
    client = _Client("```json\n" + _payload({"a.pdf": TAG_UTAMA}) + "\n```")
    out = R.classify_recordings(_items("a.pdf"), client, "m")
    assert out["a.pdf"]["tag"] == TAG_UTAMA


def test_tag_di_luar_daftar_dan_berkas_asing_dibuang():
    client = _Client(_payload({"a.pdf": "recording_aneh", "hantu.pdf": TAG_PEMBATALAN}))
    assert R.classify_recordings(_items("a.pdf"), client, "m") == {}


def test_reasoning_effort_dan_seed_diteruskan():
    client = _Client(_payload({"a.pdf": TAG_UTAMA}))
    R.classify_recordings(_items("a.pdf"), client, "m", seed=42, reasoning_effort="medium")
    kwargs = client.chat.completions.calls[0]
    assert kwargs["seed"] == 42
    assert kwargs["extra_body"] == {"reasoning_effort": "medium"}


# --------------------------------------------------------------------------
# split_by_recording_type
# --------------------------------------------------------------------------

def test_hanya_tag_terlarang_yang_dicoret():
    tags = {
        "a.pdf": {"tag": TAG_UTAMA, "reason": ""},
        "b.pdf": {"tag": TAG_PEMBATALAN, "reason": "nasabah membatalkan"},
        "c.pdf": {"tag": TAG_DITUNDA, "reason": "nasabah sibuk"},
        "d.pdf": {"tag": TAG_PERBAIKAN, "reason": ""},
    }
    kept, dropped = R.split_by_recording_type(
        ["/tmp/a.pdf", "/tmp/b.pdf", "/tmp/c.pdf", "/tmp/d.pdf"], tags
    )
    assert kept == ["/tmp/a.pdf", "/tmp/d.pdf"]
    assert [d["filename"] for d in dropped] == ["b.pdf", "c.pdf"]
    assert dropped[0]["tag_label"] == "Pembatalan oleh customer"
    assert dropped[0]["reason"] == "nasabah membatalkan"


def test_lainnya_tetap_dinilai():
    """Keranjang sisa tidak boleh dicoret — isi yang gagal dikenali akan hilang."""
    kept, dropped = R.split_by_recording_type(
        ["/tmp/a.pdf"], {"a.pdf": {"tag": TAG_LAINNYA, "reason": ""}}
    )
    assert kept == ["/tmp/a.pdf"] and dropped == []


def test_berkas_tanpa_tag_tetap_dinilai():
    kept, dropped = R.split_by_recording_type(["/tmp/a.pdf"], {})
    assert kept == ["/tmp/a.pdf"] and dropped == []


def test_semua_dicoret_maka_semua_dikembalikan():
    """Lebih baik menilai berlebih daripada menerbitkan evaluasi kosong."""
    tags = {
        "a.pdf": {"tag": TAG_PEMBATALAN, "reason": ""},
        "b.pdf": {"tag": TAG_DITUNDA, "reason": ""},
    }
    kept, dropped = R.split_by_recording_type(["/tmp/a.pdf", "/tmp/b.pdf"], tags)
    assert kept == ["/tmp/a.pdf", "/tmp/b.pdf"]
    assert dropped == []


# --------------------------------------------------------------------------
# stamp_evidence_tags
# --------------------------------------------------------------------------

_TAGS = {"a.pdf": {"tag": TAG_UTAMA}, "b.pdf": {"tag": TAG_PERBAIKAN}}


def test_tag_ditempel_ke_blok_evidence_berapa_pun_dalamnya():
    ev = {"scorecard_result": [
        {"item_code": "SC_CL_8", "evidence": {"quote": "x", "ticket_id": "b"}},
    ], "cashline_interest": {"evidence": {"quote": "y", "ticket_id": "a"}}}
    out = R.stamp_evidence_tags(ev, _TAGS)
    assert out["scorecard_result"][0]["evidence"]["recording_tag"] == TAG_PERBAIKAN
    assert out["scorecard_result"][0]["evidence"]["recording_tag_label"] == "Recording perbaikan"
    assert out["cashline_interest"]["evidence"]["recording_tag"] == TAG_UTAMA


def test_ticket_id_dengan_akhiran_pdf_tetap_cocok():
    out = R.stamp_evidence_tags({"e": {"ticket_id": "b.pdf"}}, _TAGS)
    assert out["e"]["recording_tag"] == TAG_PERBAIKAN


def test_ticket_id_kosong_atau_asing_dibiarkan():
    out = R.stamp_evidence_tags(
        {"x": {"ticket_id": None}, "y": {"ticket_id": "entah"}}, _TAGS)
    assert "recording_tag" not in out["x"] and "recording_tag" not in out["y"]


def test_tidak_mengubah_masukan():
    ev = {"e": {"ticket_id": "a"}}
    R.stamp_evidence_tags(ev, _TAGS)
    assert ev == {"e": {"ticket_id": "a"}}


# --------------------------------------------------------------------------
# stamp_reason_provenance
# --------------------------------------------------------------------------

def _sc(code, reason, ticket="b", **extra):
    return {"item_code": code, "reason": reason,
            "evidence": {"quote": "q", "ticket_id": ticket}, **extra}


def test_asal_rekaman_masuk_ke_reason():
    ev = {"scorecard_result": [_sc("SC_CL_1", "Agent menyampaikan salam.", ticket="a")]}
    out = R.stamp_reason_provenance(ev, _TAGS)
    assert out["scorecard_result"][0]["reason"] == \
        "Agent menyampaikan salam. - Evidence diambil dari recording utama."


def test_ekor_fase_lama_diganti_bukan_ditumpuk():
    """LLM menulis '- Evidence diambil dari Greeting' (FASE). Dua kalimat berawalan
    sama di satu sel membuat pembacanya menebak mana yang menerangkan apa."""
    ev = {"scorecard_result": [
        _sc("SC_CL_1", "Agent menyampaikan salam. - Evidence diambil dari Greeting", ticket="a")]}
    out = R.stamp_reason_provenance(ev, _TAGS)
    r = out["scorecard_result"][0]["reason"]
    assert r == "Agent menyampaikan salam. - Evidence diambil dari recording utama."
    assert r.count("Evidence diambil dari") == 1


def test_item_yang_tertolong_tahap_dua():
    ev = {"scorecard_result": [
        _sc("SC_CL_7", "Agent menyebut bunga 2,09%.", ticket="b", pass2=True)]}
    out = R.stamp_reason_provenance(ev, _TAGS)
    assert out["scorecard_result"][0]["reason"] == (
        "Agent menyebut bunga 2,09%. - Evidence tidak disebutkan pada recording utama "
        "tetapi disebutkan pada recording perbaikan.")


def test_item_yang_lolos_lewat_recap_disebut_apa_adanya():
    ev = {"scorecard_result": [
        _sc("SC_CL_8", "Agent menyebut provisi 2%.", ticket="b", pass2=True,
            evidence_source="fallback_final_konfirmasi")]}
    out = R.stamp_reason_provenance(ev, _TAGS)
    r = out["scorecard_result"][0]["reason"]
    assert "pembacaan ulang pada segmen Final Konfirmasi" in r
    assert "bukan dari penjelasan tersendiri" in r


def test_baris_tanpa_evidence_tidak_disentuh():
    ev = {"scorecard_result": [
        {"item_code": "SC_CL_17", "reason": "Dilewati: nasabah tidak tertarik MUS.",
         "evidence": {"ticket_id": None}}]}
    out = R.stamp_reason_provenance(ev, _TAGS)
    assert out["scorecard_result"][0]["reason"] == "Dilewati: nasabah tidak tertarik MUS."


def test_tidak_mengubah_masukan_reason():
    ev = {"scorecard_result": [_sc("SC_CL_1", "Agent menyampaikan salam.", ticket="a")]}
    R.stamp_reason_provenance(ev, _TAGS)
    assert ev["scorecard_result"][0]["reason"] == "Agent menyampaikan salam."


# --------------------------------------------------------------------------
# Voting klasifikasi
# --------------------------------------------------------------------------

class _Berurutan:
    """Klien tiruan yang mengembalikan balasan berbeda pada tiap panggilan."""
    def __init__(self, *contents):
        self._q = list(contents)
        self.calls = 0
        self.chat = type("C", (), {"completions": self})()

    def create(self, **kwargs):
        self.calls += 1
        return _Resp(self._q.pop(0) if self._q else self._q)


def test_suara_terbanyak_menang():
    """2 dari 3 percobaan menyebut utama -> utama, walau satu percobaan meleset."""
    c = _Berurutan(_payload({"a.pdf": TAG_UTAMA}),
                   _payload({"a.pdf": TAG_PEMBATALAN}),
                   _payload({"a.pdf": TAG_UTAMA}))
    out = R.classify_recordings(_items("a.pdf"), c, "m", votes=3)
    assert out["a.pdf"]["tag"] == TAG_UTAMA
    assert c.calls == 3


def test_seri_dimenangkan_tag_yang_mempertahankan_rekaman():
    """Lebih baik menilai berlebih daripada diam-diam membuang transkrip."""
    c = _Berurutan(_payload({"a.pdf": TAG_PEMBATALAN}), _payload({"a.pdf": TAG_UTAMA}))
    out = R.classify_recordings(_items("a.pdf"), c, "m", votes=2)
    assert out["a.pdf"]["tag"] == TAG_UTAMA


def test_percobaan_gagal_dilewati_bukan_menjatuhkan():
    c = _Berurutan("bukan json", _payload({"a.pdf": TAG_UTAMA}), "bukan json juga")
    out = R.classify_recordings(_items("a.pdf"), c, "m", votes=3)
    assert out["a.pdf"]["tag"] == TAG_UTAMA


def test_seluruh_percobaan_gagal_maka_tidak_menyaring():
    c = _Berurutan("x", "y", "z")
    assert R.classify_recordings(_items("a.pdf"), c, "m", votes=3) == {}


def test_satu_suara_tidak_memanggil_jalur_voting():
    c = _Berurutan(_payload({"a.pdf": TAG_UTAMA}))
    R.classify_recordings(_items("a.pdf"), c, "m", votes=1)
    assert c.calls == 1


def test_batas_waktu_klasifikasi_diteruskan():
    """Klien memakai LLM_TIMEOUT 1800 s (ukuran panggilan penilaian). Panggilan
    klasifikasi normalnya 8 detik; tanpa batas sendiri, satu sendatan menahan tiket
    setengah jam — terukur 5 September 2026."""
    client = _Client(_payload({"a.pdf": TAG_UTAMA}))
    R.classify_recordings(_items("a.pdf"), client, "m")
    assert client.chat.completions.calls[0]["timeout"] == R.CLASSIFY_TIMEOUT


def test_penanda_tinjau_saat_lebih_banyak_dicoret():
    """Bentuk yang sama dengan kegagalan 030808fLO1: 3 dari 4 rekaman tercoret."""
    assert R.needs_classification_review(["a"], ["b", "c", "d"]) is True
    assert R.needs_classification_review(["a", "b"], ["c", "d"]) is False
    assert R.needs_classification_review(["a", "b", "c"], []) is False
    assert R.needs_classification_review([], []) is False
