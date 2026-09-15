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
