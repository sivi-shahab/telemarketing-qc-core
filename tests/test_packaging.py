"""Package-data harus benar-benar ikut ke dalam paket ter-install.

Dijalankan terhadap qc_core yang di-install (layout src/ memastikan pytest tidak
bisa lulus hanya karena kebetulan membaca folder kerja). Kalau error_reasons.json
tidak ikut, impor di bawah ini gagal -- persis seperti yang akan terjadi di
container produksi.
"""
import importlib.resources

import qc_core


def test_version_terekspos():
    assert qc_core.__version__ == "1.0.0"


def test_error_reasons_json_ikut_ke_paket():
    # Impor ini SENDIRI yang membuka file JSON-nya (error_reasons.py baris 10-13).
    from qc_core.compliance import error_reasons  # noqa: F401

    ref = importlib.resources.files("qc_core.compliance") / "error_reasons.json"
    assert ref.is_file()


def test_spreadsheet_error_reason_ikut_ke_paket():
    ref = importlib.resources.files("qc_core.compliance")
    xlsx = [p.name for p in ref.iterdir() if p.name.endswith(".xlsx")]
    assert xlsx, "file .xlsx Error Reason tidak ikut ke dalam paket"


def test_mus_exemption_json_ikut_ke_paket():
    # Dibaca saat import oleh mus_exemption.py lewat os.path.dirname(__file__),
    # persis seperti error_reasons.json — kalau tidak ikut, wheel-nya lolos build
    # tapi gagal di-import saat runtime.
    from qc_core.compliance import mus_exemption as mx

    ref = importlib.resources.files("qc_core.compliance") / "mus_exemption.json"
    assert ref.is_file()
    assert mx.REGISTER, "daftar pengecualian Bank Mega kosong setelah di-install"


def test_logo_ppt_error_rate_ikut_ke_paket():
    # Dibaca ppt_error_rate.py lewat Path(__file__).parent / "assets" saat deck
    # dibuat — tanpa package-data "assets/*.png" wheel-nya lolos build tapi
    # Generate PPT Error Rate gagal di runtime.
    ref = importlib.resources.files("qc_core.compliance") / "assets" / "bank-mega-logo.png"
    assert ref.is_file()


def test_raster_template_ppt_error_rate_ikut_ke_paket():
    # Background/cover deck (ppt_error_rate._ASSET_DIR / "*.jpg") — butuh
    # package-data "assets/*.jpg"; tanpa itu deck gagal dibuat di runtime.
    from qc_core.compliance import ppt_error_rate as ppt

    paths = [
        ppt._TPL_COVER, ppt._TPL_DIVIDER_TREND, ppt._TPL_DIVIDER_RETURN,
        ppt._TPL_THANKYOU, ppt._TPL_TREND, ppt._TPL_AM, ppt._TPL_SPV,
        ppt._TPL_DETAIL, *ppt._TPL_TOPTLO.values(),
    ]
    missing = [p.name for p in paths if not p.is_file()]
    assert not missing, f"aset .jpg tidak ikut ke paket: {missing}"
