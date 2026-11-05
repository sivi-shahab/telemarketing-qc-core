"""Profil campaign: penanda penutup Legal Statement NTB vs Cashline."""
# --- penanda penutup per campaign (pemilihan rekaman utama) -------------------

from qc_core.compliance import recording_validation as RV
from qc_core.compliance.campaign_profile import closing_product_pattern

NTB = "New To Bank Eksternal"  # nama campaign NTB production (NTB_CAMPAIGNS)

_LEGAL_NTB = (
    "Berarti Bapak setuju untuk kami proseskan kartu kredit Mega Visanya ya Pak. "
    "Mohon dibantu dengan kata iya atau setuju Pak."
)


def test_ntb_legal_statement_is_closing_marker():
    assert RV.punya_penanda_penutup(_LEGAL_NTB, closing_product_pattern(NTB))


def test_cashline_pattern_unchanged_ignores_plain_credit_card_phrase():
    # Perilaku Cashline tidak boleh bergeser: tanpa nama produk Cashline/MUS di dekat
    # kata "setuju", kalimat ini BUKAN penanda penutup.
    assert not RV.punya_penanda_penutup(_LEGAL_NTB)
    assert not RV.punya_penanda_penutup(_LEGAL_NTB, closing_product_pattern("cashline"))
    assert closing_product_pattern("unknown") == closing_product_pattern("cashline")


def test_ntb_pattern_still_rejects_setuju_for_document_matters():
    assert not RV.punya_penanda_penutup(
        "Ya, setuju, silakan foto KTP dan upload dokumennya lewat link.",
        closing_product_pattern(NTB),
    )
