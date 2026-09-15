# Core sebagai Paket Bersama — Rencana Implementasi

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mengubah `core/` yang saat ini disalin (vendored) ke dalam repo api dan worker menjadi paket Python ter-versi `telemarketing-qc-core` yang di-install lewat pip, dengan namespace `qc_core.*`, test yang berpindah ke pemiliknya, dan CI GitHub Actions yang mem-bump versi lintas repo secara otomatis.

**Architecture:** Repo core direstrukturisasi ke layout `src/qc_core/` dengan `pyproject.toml`. Repo api dan worker menghapus direktori `core/`, menambah satu baris dependensi `git+https://...@v1.0.0` di `requirements.txt`, dan mengganti seluruh impor datar (`from db import crud`) menjadi bernamespace (`from qc_core.db import crud`). Dockerfile menjadi multi-stage supaya `git` hanya ada di stage builder. Saat core dirilis dengan tag baru, workflow-nya mengirim `repository_dispatch` yang membuka PR bump di api dan worker.

**Tech Stack:** Python 3.11, setuptools + `pyproject.toml`, pytest, Docker multi-stage (BuildKit), GitHub Actions, Celery, FastAPI, SQLAlchemy.

**Spec:** `docs/superpowers/specs/2026-09-08-core-as-shared-package-design.md` (di repo `telemarketing-qc-core`)

## Global Constraints

- **Tiga repo, tiga working directory.** Semua path di rencana ini relatif terhadap
  akar repo yang disebut di judul task. Akar absolutnya:
  `/data/scorecard_v2/telemarketing-qc-core`, `/data/scorecard_v2/telemarketing-qc-api`,
  `/data/scorecard_v2/telemarketing-qc-worker`.
- **`/data/scorecard_v2/telemarketing-qc-system` adalah baca-saja.** Monolith beku;
  boleh dibaca sebagai rujukan, tidak boleh disunting.
- **Dashboard tidak disentuh sama sekali.** Tidak ada satu pun task yang menyunting
  `telemarketing-qc-dashboard`.
- **Repo core bersifat PUBLIK di GitHub.** Jangan pernah meng-commit transkrip
  nasabah, dokumen KTP/KK/NPWP, `.env`, atau kredensial ke repo ini. Batasan ini
  yang membentuk Task 1.
- **Tidak ada venv dan tidak ada `pytest` di host.** Seluruh test dijalankan di
  dalam container sekali-pakai. Perintah bakunya disebut lengkap di tiap task.
- **Nama namespace: `qc_core`.** Nama distribusi: `telemarketing-qc-core`.
- **Versi rilis pertama: `1.0.0`, tag `v1.0.0`.**
- **Kontrak nama task Celery tidak boleh berubah.** Ketiganya dikirim api by name
  dan harus tetap terdaftar persis seperti ini:
  `worker.tasks.process_document.process_document`,
  `worker.tasks.process_transcript.process_transcript`,
  `worker.tasks.reprocess_ticket.reprocess_ticket`.
- **Yang TIDAK boleh berubah di Dockerfile mana pun:** `COPY certs/bankmegalocal.crt`
  + `update-ca-certificates`, dan `ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt`
  `REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt`. Tanpa ini SETIAP operasi
  S3/MinIO gagal `CERTIFICATE_VERIFY_FAILED`.
- **Urutan task tidak boleh diacak.** Task 1 menegakkan baseline hijau; tanpa itu
  tidak ada cara membuktikan refactor tidak merusak apa pun.

---

## Baseline yang sebenarnya (dibaca sebelum mulai)

Suite api **saat ini merah**, bukan hijau. Hasil eksekusi nyata atas tujuh test
yang akan pindah: **6 gagal, 52 lulus**.

| Gagal | Sebab |
|---|---|
| `test_evaluator.py::test_evaluate_direct_json` | Test menuntut `temperature == 0.0`, padahal default `evaluate()` adalah `1.0` — dan `1.0` itulah nilai yang benar (sama di monolith `dev` **dan** `origin/main`, sama di `worker/config.py:56`, sama di `api/dependencies.py:104`). **Test-nya yang basi, bukan kodenya.** Test ini masuk lewat commit `c514efc` "sync: port aditif dari origin/main". |
| 5 test di `test_pdf_parser.py` | Membaca PDF contoh dari `tests/../example_final/transkrip`. Direktori itu ada di `.gitignore` (baris 25) dan **tidak ada di disk**, jadi test gagal `FileNotFoundError` / `assert 0 == 3` di mesin mana pun yang tidak punya salinan lokalnya. |

Karena repo core publik, PDF transkrip nasabah itu **tidak boleh** di-commit sebagai
fixture. Task 1 menyelesaikan keduanya sebelum ada satu baris pun yang direstrukturisasi.

---

## Peta File

### `telemarketing-qc-core`

| File | Tanggung jawab |
|---|---|
| `pyproject.toml` | **Baru.** Metadata distribusi, dependensi, package-data, konfigurasi pytest |
| `src/qc_core/__init__.py` | **Baru.** `__version__` |
| `src/qc_core/{core_config,sales_lookup}.py` | Dipindah dari akar repo |
| `src/qc_core/{db,compliance,prompt,services}/` | Dipindah dari akar repo |
| `src/qc_core/services/__init__.py` | **Baru.** Saat ini `services/` tidak punya `__init__.py` |
| `tests/conftest.py` | **Baru.** Default environment; tanpa fixture database |
| `tests/test_*.py` | 7 file pindahan dari repo api + test baru untuk `load_prompt_module` |
| `requirements.txt` | **Dihapus** — digantikan `pyproject.toml` |
| `Jenkinsfile` | **Dihapus** |
| `.github/workflows/ci.yml` | **Baru.** pytest + cek impor bocor |
| `.github/workflows/release.yml` | **Baru.** Tag `v*` → wheel + `repository_dispatch` |

### `telemarketing-qc-api`

| File | Tanggung jawab |
|---|---|
| `core/` | **Dihapus seluruhnya** (36 file) |
| `api/requirements.txt` | + baris `telemarketing-qc-core @ git+...@v1.0.0`; − 7 dependensi yang kini milik core |
| `api/**/*.py`, `scripts/`, `tests/` | Rewrite impor ke `qc_core.*` (37 file) |
| `api/Dockerfile` | Multi-stage; 6 baris `COPY core/...` dihapus |
| `Jenkinsfile` | **Dihapus** |
| `.github/workflows/{ci,bump-core}.yml` | **Baru** |

### `telemarketing-qc-worker`

| File | Tanggung jawab |
|---|---|
| `core/` | **Dihapus seluruhnya** (36 file) |
| `worker/requirements.txt` | + baris dependensi core; − 8 dependensi yang kini milik core |
| `worker/**/*.py`, `scripts/` | Rewrite impor ke `qc_core.*` (6 file) |
| `worker/Dockerfile` | Multi-stage |
| `tests/` | **Baru.** Test kontrak nama task Celery |
| `Jenkinsfile` | **Dihapus** |
| `.github/workflows/{ci,bump-core}.yml` | **Baru** |

---

## Task 1: Tegakkan baseline hijau di repo api

**Repo:** `telemarketing-qc-api`

Ini prasyarat mutlak. Refactor besar hanya bisa dibuktikan aman kalau ada baseline
hijau untuk dibandingkan. Task ini **tidak** menyentuh vendoring sama sekali.

**Files:**
- Modify: `tests/test_evaluator.py:125`
- Modify: `tests/test_pdf_parser.py:15` (dan penambahan guard di atasnya)

**Interfaces:**
- Consumes: —
- Produces: suite api hijau (0 gagal), menjadi tolok ukur untuk Task 8 dan Task 11.

- [ ] **Step 1: Jalankan suite penuh untuk merekam baseline merah**

```bash
cd /data/scorecard_v2/telemarketing-qc-api
docker run --rm -v "$PWD":/src -w /src \
  -e PYTHONPATH=/src:/src/core --entrypoint sh local/qc-api:latest \
  -c 'pip install -q pytest >/dev/null 2>&1; python -m pytest tests -q 2>&1 | tail -20'
```

Harapan: ada baris `FAILED tests/test_evaluator.py::test_evaluate_direct_json`
dan lima `FAILED tests/test_pdf_parser.py::...`. Catat jumlah lulus/gagalnya.

- [ ] **Step 2: Perbaiki assertion temperature yang basi**

`evaluate()` di `compliance/evaluator.py:169` ber-default `temperature: float = 1.0`.
Nilai itu konsisten di monolith `dev` maupun `origin/main`, di `worker/config.py:56`
(`llm_temperature: float = 1.0`), dan di `api/dependencies.py:104`
(`float(os.getenv("LLM_TEMPERATURE", "1.0"))`). Jadi test-nya yang salah.

Di `tests/test_evaluator.py`, ganti baris 125:

```python
    assert llm.chat.completions.seen[0]["temperature"] == 1.0
```

Tambahkan komentar tepat di atasnya supaya tidak "diperbaiki" balik oleh orang berikutnya:

```python
    # 1.0 adalah default yang disengaja di evaluate() dan di seluruh pemanggilnya
    # (worker/config.py llm_temperature, api/dependencies.py LLM_TEMPERATURE).
    # Angka 0.0 di sini adalah sisa port dari origin/main (commit c514efc) yang
    # tidak pernah cocok dengan kode di repo ini.
```

- [ ] **Step 3: Jalankan test evaluator, harus lulus**

```bash
cd /data/scorecard_v2/telemarketing-qc-api
docker run --rm -v "$PWD":/src -w /src \
  -e PYTHONPATH=/src:/src/core --entrypoint sh local/qc-api:latest \
  -c 'pip install -q pytest >/dev/null 2>&1; python -m pytest tests/test_evaluator.py -q 2>&1 | tail -5'
```

Harapan: `PASS`, tidak ada kegagalan.

- [ ] **Step 4: Beri guard pada test yang butuh PDF transkrip**

PDF di `example_final/transkrip` adalah transkrip panggilan nasabah sungguhan. Ia
ada di `.gitignore` dan **harus tetap begitu** — repo core publik, jadi meng-commit
file ini sebagai fixture akan membocorkan data nasabah. Yang benar adalah membuat
test-nya melewatkan diri (skip) saat fixture tidak tersedia, dan mengizinkan lokasi
fixture ditunjuk lewat environment variable.

Di `tests/test_pdf_parser.py`, ganti baris 15 (`TRANS_DIR = ...`) dengan:

```python
# PDF transkrip berisi data nasabah sungguhan: ia sengaja ada di .gitignore dan
# TIDAK BOLEH di-commit (repo core publik). Test yang membutuhkannya melewatkan
# diri kalau fixture tidak ada, sehingga suite tetap hijau di CI dan di mesin
# developer yang tidak memegang salinannya. Tunjuk lokasi lain lewat:
#     QC_TRANSCRIPT_FIXTURES=/path/ke/transkrip pytest tests/test_pdf_parser.py
TRANS_DIR = os.environ.get(
    "QC_TRANSCRIPT_FIXTURES",
    os.path.join(os.path.dirname(__file__), "..", "example_final", "transkrip"),
)

needs_fixtures = pytest.mark.skipif(
    not os.path.isdir(TRANS_DIR),
    reason=f"fixture transkrip tidak tersedia di {TRANS_DIR} "
           "(set QC_TRANSCRIPT_FIXTURES untuk menjalankannya)",
)
```

- [ ] **Step 5: Pasang marker pada kelima test yang membaca PDF**

Tambahkan `@needs_fixtures` tepat di atas `def` dari kelima fungsi ini di file yang
sama: `test_parse_single_pdf_segments`, `test_parse_pdf_joins_cross_page_text`,
`test_parse_pdf_no_empty_text`, `test_build_transcript_duplicate_suffix_set`,
`test_build_transcript_three_file_session`. Contoh bentuknya:

```python
@needs_fixtures
def test_parse_single_pdf_segments():
    ...
```

Jangan menyentuh `test_parse_filename_timestamp_with_full_path` — ia hanya
mem-parsing string nama file, tidak membuka PDF, dan memang lulus tanpa fixture.

- [ ] **Step 6: Jalankan suite penuh, harus hijau**

```bash
cd /data/scorecard_v2/telemarketing-qc-api
docker run --rm -v "$PWD":/src -w /src \
  -e PYTHONPATH=/src:/src/core --entrypoint sh local/qc-api:latest \
  -c 'pip install -q pytest >/dev/null 2>&1; python -m pytest tests -q 2>&1 | tail -10'
```

Harapan: `0 failed`, dengan 5 test berstatus `skipped`. **Kalau masih ada yang
gagal, berhenti dan laporkan** — jangan lanjut ke Task 2.

- [ ] **Step 7: Commit**

```bash
cd /data/scorecard_v2/telemarketing-qc-api
git add tests/test_evaluator.py tests/test_pdf_parser.py
git commit -m "test: tegakkan baseline hijau sebelum de-vendoring core

test_evaluator menuntut temperature 0.0 padahal default yang disengaja di
evaluate() dan seluruh pemanggilnya adalah 1.0 (sisa port dari origin/main).
test_pdf_parser membaca PDF transkrip nasabah yang gitignored dan tidak ada di
disk; kini ia skip kalau fixture tidak tersedia, dengan lokasi yang bisa
ditunjuk lewat QC_TRANSCRIPT_FIXTURES."
```

---

## Task 2: Restrukturisasi core ke `src/qc_core/`

**Repo:** `telemarketing-qc-core`

**Files:**
- Create: `src/qc_core/__init__.py`, `src/qc_core/services/__init__.py`
- Modify: seluruh `*.py` core (rewrite impor internal)
- Delete: `core_config.py`, `sales_lookup.py`, `db/`, `compliance/`, `prompt/`, `services/` di akar (dipindah, bukan dihapus isinya)

**Interfaces:**
- Consumes: —
- Produces: paket `qc_core` dengan submodul `qc_core.db`, `qc_core.compliance`,
  `qc_core.prompt`, `qc_core.services`, `qc_core.core_config`, `qc_core.sales_lookup`.
  Nama-nama inilah yang dipakai Task 4, 5, 8, dan 11.

- [ ] **Step 1: Pastikan HEAD lokal sudah ter-push**

Rilis `v1.0.0` harus dibuat dari commit yang ada di remote. Cek dulu:

```bash
cd /data/scorecard_v2/telemarketing-qc-core
git log --oneline -1
git log --oneline -1 origin/main
```

Kalau HEAD lokal lebih maju dari `origin/main`, push:

```bash
git push origin HEAD
```

- [ ] **Step 2: Pindahkan file dengan `git mv` (bukan `cp`)**

`git mv` mempertahankan riwayat file; `cp` + `rm` menghapusnya.

```bash
cd /data/scorecard_v2/telemarketing-qc-core
mkdir -p src/qc_core
git mv core_config.py sales_lookup.py db compliance prompt services src/qc_core/
```

- [ ] **Step 3: Buat `__init__.py` untuk paket dan untuk `services/`**

`services/` saat ini **tidak punya** `__init__.py` — ia jalan sebagai namespace
package saat di-copy datar, tetapi di bawah `src/` layout ia harus jadi paket biasa
supaya ikut ter-package oleh setuptools.

```bash
cd /data/scorecard_v2/telemarketing-qc-core
cat > src/qc_core/__init__.py <<'EOF'
"""Kode bersama telemarketing QC: db, compliance, prompt, services.

Di-install sebagai distribusi ``telemarketing-qc-core`` dan dipakai oleh repo
``telemarketing-qc-api`` dan ``telemarketing-qc-worker``. Paket ini TIDAK BOLEH
mengimpor apa pun dari ``api`` maupun ``worker`` — CI menegakkannya.
"""

__version__ = "1.0.0"
EOF
cat > src/qc_core/services/__init__.py <<'EOF'
"""Klien layanan luar: S3/MinIO, DWH API, tickets daily, view streams."""
EOF
git add src/qc_core/__init__.py src/qc_core/services/__init__.py
```

- [ ] **Step 4: Rewrite impor internal core ke `qc_core.*`**

Ada 46 baris impor internal di dalam core sendiri (mis. `from compliance.documents
import ...` di `db/crud.py`). Semuanya harus bernamespace.

```bash
cd /data/scorecard_v2/telemarketing-qc-core
python3 - <<'PY'
import pathlib, re

MODULES = ("db", "compliance", "services", "prompt", "sales_lookup", "core_config")
# (?m) multiline: ^ cocok di tiap baris. \s* mempertahankan indentasi impor lazy
# di dalam fungsi. \b mencegah "dbutils" ikut tertangkap.
pat = re.compile(r"(?m)^(\s*)(from|import)\s+(%s)\b" % "|".join(MODULES))

changed = 0
for p in pathlib.Path("src/qc_core").rglob("*.py"):
    s = p.read_text(encoding="utf-8")
    new = pat.sub(lambda m: f"{m.group(1)}{m.group(2)} qc_core.{m.group(3)}", s)
    if new != s:
        p.write_text(new, encoding="utf-8")
        changed += 1
        print("rewrite:", p)
print("file diubah:", changed)
PY
```

- [ ] **Step 5: Verifikasi tidak ada impor datar yang tersisa**

```bash
cd /data/scorecard_v2/telemarketing-qc-core
grep -rnE '^\s*(from|import)\s+(db|compliance|services|prompt|sales_lookup|core_config)\b' \
  --include='*.py' src/ && echo "MASIH ADA SISA — perbaiki manual" || echo "bersih"
```

Harapan: `bersih`.

- [ ] **Step 6: Commit**

```bash
cd /data/scorecard_v2/telemarketing-qc-core
git add -A
git commit -m "refactor: pindahkan core ke src/qc_core/ dengan namespace sendiri

Nama datar db/compliance/services/prompt akan merebut namespace top-level di
site-packages begitu core di-install sebagai paket. services/ mendapat
__init__.py karena di bawah src/ layout ia harus jadi paket biasa, bukan
namespace package."
```

---

## Task 3: `pyproject.toml` dan pembuktian package-data

**Repo:** `telemarketing-qc-core`

Dua file non-Python **wajib** ikut ke dalam wheel. `compliance/error_reasons.json`
dibaca saat import (`error_reasons.py:10-13` memakai `os.path.dirname(__file__)`),
jadi kalau ia tidak ikut, `import qc_core.compliance.error_reasons` gagal — dan itu
baru ketahuan di produksi. Task ini membuktikan keduanya ikut.

**Files:**
- Create: `pyproject.toml`
- Delete: `requirements.txt`

**Interfaces:**
- Consumes: paket `qc_core` dari Task 2
- Produces: distribusi `telemarketing-qc-core==1.0.0`, dapat di-install lewat
  `pip install -e .` dan `pip install .[test]`.

- [ ] **Step 1: Tulis `pyproject.toml`**

Dependensi diambil dari `requirements.txt` core yang lama, kini dengan batas bawah
eksplisit supaya resolusi tidak berubah diam-diam antar build.

```bash
cd /data/scorecard_v2/telemarketing-qc-core
cat > pyproject.toml <<'EOF'
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "telemarketing-qc-core"
version = "1.0.0"
description = "Kode bersama telemarketing QC: db, compliance, prompt, services"
requires-python = ">=3.11"
dependencies = [
    "sqlalchemy>=2.0",
    "psycopg2-binary>=2.9",
    "boto3>=1.34",
    "openpyxl>=3.1",
    "pdfplumber>=0.11",
    "requests>=2.31",
    "pydantic-settings>=2.0",
    # Merender halaman PDF RIPLAY jadi image sebelum dikirim ke model vision
    # (qc_core/compliance/riplay.py).
    "pypdfium2>=4.25",
]

[project.optional-dependencies]
test = ["pytest>=8.0"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
# WAJIB. error_reasons.json dibaca saat import oleh compliance/error_reasons.py
# lewat os.path.dirname(__file__); tanpa baris ini wheel-nya lolos build tapi
# gagal di-import saat runtime.
"qc_core.compliance" = ["*.json", "*.xlsx"]

[tool.pytest.ini_options]
testpaths = ["tests"]
EOF
git add pyproject.toml
git rm -q requirements.txt
```

- [ ] **Step 2: Tulis test yang membuktikan package-data ikut**

Direktori `tests/` belum ada di repo core — buat dulu:

```bash
cd /data/scorecard_v2/telemarketing-qc-core
mkdir -p tests
```

Lalu `tests/test_packaging.py`:

```python
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
```

- [ ] **Step 3: Jalankan test — harus GAGAL dulu kalau `pyproject.toml` salah**

Sengaja dijalankan terhadap wheel yang di-install, bukan folder kerja:

```bash
cd /data/scorecard_v2/telemarketing-qc-core
docker run --rm -v "$PWD":/src -w /tmp --entrypoint sh python:3.11-slim -c '
  pip install -q /src 2>&1 | tail -3
  pip install -q pytest
  cp -r /src/tests /tmp/tests
  python -m pytest /tmp/tests/test_packaging.py -q 2>&1 | tail -15'
```

Harapan: ketiganya `PASS`. Kalau `test_error_reasons_json_ikut_ke_paket` gagal
dengan `FileNotFoundError`, berarti blok `[tool.setuptools.package-data]` salah —
perbaiki sebelum lanjut.

- [ ] **Step 4: Commit**

```bash
cd /data/scorecard_v2/telemarketing-qc-core
git add pyproject.toml tests/test_packaging.py
git commit -m "build: jadikan core distribusi pip (telemarketing-qc-core 1.0.0)

requirements.txt dihapus; pyproject.toml jadi satu-satunya tempat dependensi
core dideklarasikan. error_reasons.json dan spreadsheet Error Reason didaftarkan
sebagai package-data, dengan test yang membuktikannya lewat paket ter-install."
```

---

## Task 4: Buang trik `sys.path` dan bernamespace-kan `prompt_module`

**Repo:** `telemarketing-qc-core`

Dua trik ini adalah konsekuensi langsung dari copy-datar dan kini tidak punya alasan
untuk ada. Yang kedua **tidak tertangkap** oleh rewrite otomatis di Task 2 karena
berupa string, jadi ia adalah risiko nomor satu di seluruh rencana ini: kalau
terlewat, kegagalannya baru muncul saat OCR berjalan di produksi, bukan saat build.

**Files:**
- Modify: `src/qc_core/compliance/documents.py:12-25` (blok `sys.path`), `:29-34` (string `prompt_module`)
- Test: `tests/test_load_prompt_module.py`

**Interfaces:**
- Consumes: `qc_core.prompt.*` dari Task 2
- Produces: `qc_core.compliance.documents.load_prompt_module(doc_type)` yang
  mengembalikan modul prompt untuk `doc_type` ∈ `{"ktp", "kk", "npwp", "cover_buku_tabungan"}`.

- [ ] **Step 1: Tulis test yang gagal lebih dulu**

Buat `tests/test_load_prompt_module.py`:

```python
"""load_prompt_module() me-resolve modul prompt lewat STRING, bukan impor biasa.

Karena berupa string di DOCUMENT_TYPES, rewrite impor otomatis tidak menyentuhnya.
Kalau string itu masih "prompt.ocr_ktp" (bukan "qc_core.prompt.ocr_ktp"), tidak ada
yang gagal saat build image -- kegagalannya baru muncul saat task OCR berjalan di
produksi. Test ini yang menangkapnya lebih awal.
"""
import pytest

from qc_core.compliance.documents import DOCUMENT_TYPES, load_prompt_module


@pytest.mark.parametrize("doc_type", ["ktp", "kk", "npwp", "cover_buku_tabungan"])
def test_load_prompt_module_bisa_diimpor(doc_type):
    module = load_prompt_module(doc_type)
    assert hasattr(module, "build_prompt")


@pytest.mark.parametrize("doc_type", sorted(DOCUMENT_TYPES))
def test_prompt_module_bernamespace(doc_type):
    name = DOCUMENT_TYPES[doc_type]["prompt_module"]
    assert name.startswith("qc_core.prompt."), (
        f"{doc_type} masih menunjuk {name!r} -- string ini tidak ikut ter-rewrite "
        "otomatis dan akan gagal saat runtime OCR"
    )
```

- [ ] **Step 2: Jalankan test, pastikan GAGAL**

```bash
cd /data/scorecard_v2/telemarketing-qc-core
docker run --rm -v "$PWD":/src -w /tmp --entrypoint sh python:3.11-slim -c '
  pip install -q /src pytest 2>&1 | tail -2
  cp -r /src/tests /tmp/tests
  python -m pytest /tmp/tests/test_load_prompt_module.py -q 2>&1 | tail -12'
```

Harapan: GAGAL — `ModuleNotFoundError: No module named 'prompt'` dan/atau
assertion "masih menunjuk 'prompt.ocr_ktp'".

- [ ] **Step 3: Hapus blok penyisipan `sys.path`**

Di `src/qc_core/compliance/documents.py`, hapus seluruh blok baris 20-25 ini:

```python
# Repo root: <repo>/compliance/documents.py -> <repo>. The prompt modules live in
# <repo>/prompt and are imported lazily (importlib) at task runtime; the celery
# worker's sys.path does not reliably include the repo root, so ensure it here.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
```

Setelah itu periksa apakah `sys` dan `os` masih dipakai di file tersebut; buang
`import sys` (dan `import os` kalau memang sudah tidak terpakai) supaya tidak
meninggalkan impor mati:

```bash
cd /data/scorecard_v2/telemarketing-qc-core
grep -n 'sys\.\|os\.' src/qc_core/compliance/documents.py | head
```

- [ ] **Step 4: Bernamespace-kan keempat string `prompt_module`**

Di file yang sama, baris 29-34, ubah keempatnya:

```python
    "ktp": {"label": "KTP", "prompt_module": "qc_core.prompt.ocr_ktp"},
    "kk": {"label": "KK", "prompt_module": "qc_core.prompt.ocr_kk"},
    "npwp": {"label": "NPWP", "prompt_module": "qc_core.prompt.ocr_npwp"},
```

dan yang keempat (bentuknya multi-baris):

```python
        "prompt_module": "qc_core.prompt.ocr_cover_buku_tabungan",
```

- [ ] **Step 5: Jalankan test, harus LULUS**

```bash
cd /data/scorecard_v2/telemarketing-qc-core
docker run --rm -v "$PWD":/src -w /tmp --entrypoint sh python:3.11-slim -c '
  pip install -q /src pytest 2>&1 | tail -2
  cp -r /src/tests /tmp/tests
  python -m pytest /tmp/tests -q 2>&1 | tail -8'
```

Harapan: seluruh test lulus.

- [ ] **Step 6: Commit**

```bash
cd /data/scorecard_v2/telemarketing-qc-core
git add src/qc_core/compliance/documents.py tests/test_load_prompt_module.py
git commit -m "refactor(documents): buang sys.path hack, namespace-kan prompt_module

Penyisipan repo root ke sys.path hanya diperlukan selama core di-copy datar ke
/app. String prompt_module di-resolve lewat importlib sehingga tidak ikut
ter-rewrite otomatis; test baru menjaga keempatnya tetap bernamespace."
```

---

## Task 5: Pindahkan tujuh test milik core

**Repo:** `telemarketing-qc-core` (mengambil dari `telemarketing-qc-api`)

Ketujuh test ini murni menguji kode core. Sudah diverifikasi: **tidak satu pun
memakai fixture `db`/`admin_user`**, jadi tidak butuh koneksi database dan
pemindahannya bersih. (Ketiga test yang butuh fixture `db` —
`test_reprocess_active_flag`, `test_reprocess_filtered`,
`test_rbac_collection_permissions` — tetap di api.)

**Files:**
- Create: `tests/conftest.py`
- Create (pindahan): `tests/test_campaign_kind.py`, `test_cashline_agent_index.py`,
  `test_evaluator.py`, `test_hierarchy_avg_failure_rate.py`,
  `test_missing_docs_snapshot_first.py`, `test_pdf_parser.py`,
  `test_sales_roster_placeholders.py`
- Delete (di repo api): ketujuh file yang sama

**Interfaces:**
- Consumes: paket `qc_core` (Task 2-4)
- Produces: suite test core yang menjadi gerbang rilis untuk Task 7.

- [ ] **Step 1: Salin ketujuh file ke repo core**

```bash
cd /data/scorecard_v2
for t in test_campaign_kind test_cashline_agent_index test_evaluator \
         test_hierarchy_avg_failure_rate test_missing_docs_snapshot_first \
         test_pdf_parser test_sales_roster_placeholders; do
  cp "telemarketing-qc-api/tests/$t.py" "telemarketing-qc-core/tests/$t.py"
done
ls telemarketing-qc-core/tests/
```

- [ ] **Step 2: Rewrite impornya ke `qc_core.*`**

```bash
cd /data/scorecard_v2/telemarketing-qc-core
python3 - <<'PY'
import pathlib, re

MODULES = ("db", "compliance", "services", "prompt", "sales_lookup", "core_config")
pat = re.compile(r"(?m)^(\s*)(from|import)\s+(%s)\b" % "|".join(MODULES))

for p in pathlib.Path("tests").glob("test_*.py"):
    s = p.read_text(encoding="utf-8")
    new = pat.sub(lambda m: f"{m.group(1)}{m.group(2)} qc_core.{m.group(3)}", s)
    if new != s:
        p.write_text(new, encoding="utf-8")
        print("rewrite:", p)
PY
grep -rnE '^\s*(from|import)\s+(db|compliance|services|prompt|sales_lookup|core_config)\b' \
  --include='*.py' tests/ && echo "MASIH ADA SISA" || echo "bersih"
```

Harapan: `bersih`.

> Catatan: `test_sales_roster_placeholders.py` memuat **dua** bentuk —
> `import sales_lookup` dan `from sales_lookup import ...`. Regex di atas menangani
> keduanya, tetapi pemakaian `sales_lookup.<atribut>` di badan test ikut perlu
> disesuaikan. Cek dan perbaiki:
>
> ```bash
> grep -n 'sales_lookup\.' tests/test_sales_roster_placeholders.py
> ```
>
> Ubah setiap `sales_lookup.X` menjadi `qc_core.sales_lookup.X`, atau lebih rapi:
> ganti barisnya menjadi `from qc_core import sales_lookup` sehingga badan test
> tidak perlu diubah sama sekali. Pilih cara kedua.

- [ ] **Step 3: Tulis `tests/conftest.py`**

Core tidak punya `api.dependencies`, jadi conftest-nya jauh lebih ramping daripada
milik api — hanya default environment, tanpa fixture database.

```bash
cd /data/scorecard_v2/telemarketing-qc-core
cat > tests/conftest.py <<'EOF'
"""Default environment untuk test core.

Jauh lebih ramping daripada conftest repo api: tidak ada fixture database di sini,
karena ketujuh test yang pindah ke repo ini semuanya murni unit -- yang memakai
fixture `db` (reprocess, rbac) tetap tinggal di repo api bersama
`api.dependencies._make_engine` yang mereka butuhkan.

setdefault, bukan penugasan langsung: kalau seseorang menjalankan test terhadap
infra sungguhan, nilai dari environment-nya tidak ditimpa.
"""
import os

os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6378/0")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
EOF
```

- [ ] **Step 4: Jalankan seluruh suite core**

```bash
cd /data/scorecard_v2/telemarketing-qc-core
docker run --rm -v "$PWD":/src -w /tmp --entrypoint sh python:3.11-slim -c '
  pip install -q "/src[test]" 2>&1 | tail -3
  cp -r /src/tests /tmp/tests
  python -m pytest /tmp/tests -q 2>&1 | tail -12'
```

Harapan: `0 failed`, dengan 5 test `test_pdf_parser` berstatus `skipped` (guard dari
Task 1 ikut terbawa bersama file-nya).

- [ ] **Step 5: Hapus ketujuh file itu dari repo api**

```bash
cd /data/scorecard_v2/telemarketing-qc-api
git rm -q tests/test_campaign_kind.py tests/test_cashline_agent_index.py \
  tests/test_evaluator.py tests/test_hierarchy_avg_failure_rate.py \
  tests/test_missing_docs_snapshot_first.py tests/test_pdf_parser.py \
  tests/test_sales_roster_placeholders.py
ls tests/
```

Harapan: tersisa 10 file `test_*.py`, plus `__init__.py` dan `conftest.py`.

- [ ] **Step 6: Pastikan suite api yang tersisa masih hijau**

```bash
cd /data/scorecard_v2/telemarketing-qc-api
docker run --rm -v "$PWD":/src -w /src \
  -e PYTHONPATH=/src:/src/core --entrypoint sh local/qc-api:latest \
  -c 'pip install -q pytest >/dev/null 2>&1; python -m pytest tests -q 2>&1 | tail -8'
```

Harapan: `0 failed`.

- [ ] **Step 7: Commit di kedua repo**

```bash
cd /data/scorecard_v2/telemarketing-qc-core
git add tests/
git commit -m "test: pindahkan tujuh test milik core dari repo api

Ketujuhnya murni menguji kode core dan tidak memakai fixture db, jadi bisa
pindah tanpa membawa infrastruktur test apa pun. Ini yang memberi arti pada
gerbang rilis: core tidak bisa dirilis rusak."

cd /data/scorecard_v2/telemarketing-qc-api
git commit -q -m "test: serahkan tujuh test milik core ke repo core

Pasangan dari commit di telemarketing-qc-core. Sisa 10 test di sini semuanya
mengimpor api.* dan memang milik repo ini."
git log --oneline -1
```

---

## Task 6: CI repo core

**Repo:** `telemarketing-qc-core`

**Files:**
- Create: `.github/workflows/ci.yml`
- Delete: `Jenkinsfile`

**Interfaces:**
- Consumes: `pyproject.toml` (Task 3), `tests/` (Task 5)
- Produces: status check `test` dan `no-leaking-imports` pada tiap PR.

- [ ] **Step 1: Tulis workflow CI**

Cek "impor bocor" dipertahankan dari `Jenkinsfile` lama — core tidak boleh
bergantung pada repo api maupun worker.

```bash
cd /data/scorecard_v2/telemarketing-qc-core
mkdir -p .github/workflows
cat > .github/workflows/ci.yml <<'EOF'
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      # Sengaja bukan `pip install -e .`: install biasa memaksa test berjalan
      # terhadap paket yang benar-benar ter-install, sehingga package-data yang
      # tidak ikut akan ketahuan di sini, bukan di produksi.
      - run: pip install ".[test]"
      - run: pytest -q

  no-leaking-imports:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      # Core adalah dasar: kalau ia mengimpor api atau worker, dependensinya
      # melingkar dan image-nya pasti gagal. Dipertahankan dari Jenkinsfile lama.
      - name: core tidak boleh mengimpor api atau worker
        run: |
          if grep -rnE '^\s*(from|import)\s+(api|worker)\b' --include='*.py' src/; then
            echo "::error::core mengimpor api/worker -- dependensi melingkar"
            exit 1
          fi
          echo "bersih"
EOF
```

- [ ] **Step 2: Jalankan kedua cek itu secara lokal lebih dulu**

```bash
cd /data/scorecard_v2/telemarketing-qc-core
docker run --rm -v "$PWD":/src -w /tmp --entrypoint sh python:3.11-slim -c '
  pip install -q "/src[test]" 2>&1 | tail -2
  cp -r /src/tests /tmp/tests && python -m pytest /tmp/tests -q 2>&1 | tail -6'
grep -rnE '^\s*(from|import)\s+(api|worker)\b' --include='*.py' src/ \
  && echo "GAGAL: ada impor bocor" || echo "bersih"
```

Harapan: test `0 failed`, dan `bersih`.

- [ ] **Step 3: Hapus Jenkinsfile**

```bash
cd /data/scorecard_v2/telemarketing-qc-core
git rm -q Jenkinsfile
```

- [ ] **Step 4: Commit dan push**

```bash
cd /data/scorecard_v2/telemarketing-qc-core
git add .github/workflows/ci.yml
git commit -m "ci: pindahkan CI core ke GitHub Actions

Cek 'core tidak boleh mengimpor api/worker' dipertahankan dari Jenkinsfile.
Test dijalankan terhadap paket ter-install, bukan folder kerja, supaya
package-data yang tidak ikut ketahuan di CI."
git push origin HEAD
```

- [ ] **Step 5: Pastikan CI hijau di GitHub sebelum lanjut**

```bash
cd /data/scorecard_v2/telemarketing-qc-core
gh run list --limit 3
```

Harapan: run terbaru berstatus `completed success`. Kalau merah, perbaiki dulu —
Task 7 membuat rilis, dan rilis dari CI merah tidak boleh terjadi.

---

## Task 7: Rilis `v1.0.0` dan workflow release

**Repo:** `telemarketing-qc-core`

**Files:**
- Create: `.github/workflows/release.yml`

**Interfaces:**
- Consumes: CI hijau (Task 6)
- Produces: tag `v1.0.0` + GitHub Release berisi wheel; event `repository_dispatch`
  bertipe `core-released` dengan payload `{"version": "1.0.0"}` yang dikonsumsi
  Task 10 dan Task 14.

- [ ] **Step 1: Tulis workflow release**

```bash
cd /data/scorecard_v2/telemarketing-qc-core
cat > .github/workflows/release.yml <<'EOF'
name: Release

on:
  push:
    tags: ["v*"]

jobs:
  release:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    outputs:
      version: ${{ steps.ver.outputs.version }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - id: ver
        run: echo "version=${GITHUB_REF_NAME#v}" >> "$GITHUB_OUTPUT"
      # Gerbang rilis: tag yang test-nya merah tidak boleh jadi Release.
      - run: pip install ".[test]" build
      - run: pytest -q
      - run: python -m build --wheel
      - uses: softprops/action-gh-release@v2
        with:
          files: dist/*.whl

  notify:
    needs: release
    runs-on: ubuntu-latest
    strategy:
      matrix:
        repo: [telemarketing-qc-api, telemarketing-qc-worker]
    steps:
      # PAT dengan scope `repo` pada kedua repo tujuan. GITHUB_TOKEN bawaan
      # TIDAK bisa memicu workflow di repo lain -- ini penyebab paling umum
      # "dispatch terkirim tapi tidak ada yang terjadi".
      - name: Beri tahu ${{ matrix.repo }}
        env:
          GH_TOKEN: ${{ secrets.CROSS_REPO_TOKEN }}
        run: |
          gh api "repos/${{ github.repository_owner }}/${{ matrix.repo }}/dispatches" \
            -f event_type=core-released \
            -F "client_payload[version]=${{ needs.release.outputs.version }}"
EOF
```

- [ ] **Step 2: Buat PAT dan simpan sebagai secret**

Ini langkah manual di GitHub, tidak bisa di-skrip:

1. Buat fine-grained PAT dengan akses **Contents: read & write** dan
   **Pull requests: read & write** pada `telemarketing-qc-api` dan
   `telemarketing-qc-worker`.
2. Simpan sebagai secret bernama `CROSS_REPO_TOKEN` di repo `telemarketing-qc-core`:

```bash
cd /data/scorecard_v2/telemarketing-qc-core
gh secret set CROSS_REPO_TOKEN
```

- [ ] **Step 3: Commit, push, lalu buat tag**

```bash
cd /data/scorecard_v2/telemarketing-qc-core
git add .github/workflows/release.yml
git commit -m "ci: workflow rilis — wheel + repository_dispatch ke api dan worker"
git push origin HEAD
git tag v1.0.0
git push origin v1.0.0
```

- [ ] **Step 4: Pastikan Release terbentuk**

```bash
cd /data/scorecard_v2/telemarketing-qc-core
gh run list --limit 3
gh release view v1.0.0
```

Harapan: Release `v1.0.0` ada dan memuat satu file `.whl`. Job `notify` boleh gagal
di titik ini — repo api dan worker belum punya handler-nya (Task 10 dan 14).

- [ ] **Step 5: Buktikan paket bisa di-install dari git seperti yang akan dilakukan Dockerfile**

Ini pembuktian terpenting sebelum menyentuh repo api dan worker.

```bash
docker run --rm --entrypoint sh python:3.11-slim -c '
  apt-get update -qq && apt-get install -y -qq --no-install-recommends git >/dev/null
  pip install -q "telemarketing-qc-core @ git+https://github.com/sivi-shahab/telemarketing-qc-core.git@v1.0.0" 2>&1 | tail -3
  python -c "
import qc_core, qc_core.core_config, qc_core.sales_lookup
import qc_core.db.crud, qc_core.db.models
import qc_core.compliance.evaluator, qc_core.compliance.error_reasons
import qc_core.compliance.stats_aggregate, qc_core.services.data_dwh
from qc_core.compliance.documents import load_prompt_module
for d in (\"ktp\", \"kk\", \"npwp\", \"cover_buku_tabungan\"):
    load_prompt_module(d)
print(\"OK\", qc_core.__version__)
"'
```

Harapan: `OK 1.0.0`. Kalau gagal di sini, **jangan lanjut** — Task 8 dan seterusnya
bergantung sepenuhnya pada perintah install ini.

---

## Task 8: De-vendor repo api

**Repo:** `telemarketing-qc-api`

**Files:**
- Delete: `core/` (36 file)
- Modify: `api/requirements.txt`
- Modify: 37 file `*.py` di `api/`, `scripts/`, `tests/`

**Interfaces:**
- Consumes: `telemarketing-qc-core==1.0.0` dari Task 7
- Produces: repo api tanpa `core/`, seluruh impor bernamespace `qc_core.*`.

- [ ] **Step 1: Catat daftar file yang akan berubah**

```bash
cd /data/scorecard_v2/telemarketing-qc-api
grep -rlE '^\s*(from|import)\s+(db|compliance|services|prompt|sales_lookup|core_config)\b' \
  --include='*.py' api scripts tests | sort | tee /tmp/api-import-files.txt | wc -l
```

Harapan: sekitar 30 file (37 termasuk yang di dalam `core/`, yang akan dihapus).

- [ ] **Step 2: Rewrite impor**

Perhatikan `api scripts tests` — direktori `core/` sengaja tidak disebut karena akan dihapus.

```bash
cd /data/scorecard_v2/telemarketing-qc-api
python3 - <<'PY'
import pathlib, re

MODULES = ("db", "compliance", "services", "prompt", "sales_lookup", "core_config")
pat = re.compile(r"(?m)^(\s*)(from|import)\s+(%s)\b" % "|".join(MODULES))

changed = 0
for root in ("api", "scripts", "tests"):
    for p in pathlib.Path(root).rglob("*.py"):
        s = p.read_text(encoding="utf-8")
        new = pat.sub(lambda m: f"{m.group(1)}{m.group(2)} qc_core.{m.group(3)}", s)
        if new != s:
            p.write_text(new, encoding="utf-8")
            changed += 1
            print("rewrite:", p)
print("file diubah:", changed)
PY
```

- [ ] **Step 3: Cari pemakaian bergaya atribut yang luput**

Regex hanya menyentuh baris impor. Pemakaian seperti `sales_lookup.foo()` setelah
`import sales_lookup` tidak ikut berubah.

```bash
cd /data/scorecard_v2/telemarketing-qc-api
grep -rnE '(^|[^.\w])(sales_lookup|core_config)\.' --include='*.py' api scripts tests \
  | grep -v 'qc_core\.'
echo "--- string modul dinamis ---"
grep -rnE '"(db|compliance|services|prompt|sales_lookup|core_config)\.' \
  --include='*.py' api scripts tests
```

Perbaiki setiap baris yang muncul: ubah `import sales_lookup` menjadi
`from qc_core import sales_lookup` supaya badan kodenya tidak perlu disentuh.
Kalau kedua perintah tidak mengeluarkan apa-apa, lanjut.

- [ ] **Step 4: Perbarui `api/requirements.txt`**

Tujuh dependensi ini kini dideklarasikan oleh core dan **harus dihapus dari sini**
supaya tidak ada dua sumber kebenaran versi: `sqlalchemy`, `psycopg2-binary`,
`boto3`, `openpyxl`, `pdfplumber`, `requests>=2.31`, `pydantic-settings`.
Yang **tetap** milik api: `fastapi`, `uvicorn[standard]`, `celery[redis]`,
`alembic`, `python-multipart`, `pypdf`, `openai`, `redis`,
`python-jose[cryptography]`, `passlib[bcrypt]`, `bcrypt==3.2.2`.

```bash
cd /data/scorecard_v2/telemarketing-qc-api
cat > api/requirements.txt <<'EOF'
# Kode bersama. Dependensi core (sqlalchemy, psycopg2-binary, boto3, openpyxl,
# pdfplumber, requests, pydantic-settings, pypdfium2) ikut ter-install dari sini
# dan SENGAJA tidak diulang di bawah -- satu sumber kebenaran versi.
# Baris ini di-bump otomatis oleh .github/workflows/bump-core.yml.
telemarketing-qc-core @ git+https://github.com/sivi-shahab/telemarketing-qc-core.git@v1.0.0

fastapi
uvicorn[standard]
celery[redis]
alembic
python-multipart
pypdf
openai
redis
python-jose[cryptography]
passlib[bcrypt]
bcrypt==3.2.2
EOF
```

- [ ] **Step 5: Hapus direktori `core/`**

```bash
cd /data/scorecard_v2/telemarketing-qc-api
git rm -rq core
ls core 2>&1
```

Harapan: `No such file or directory`.

- [ ] **Step 6: Jalankan suite api terhadap core yang di-install dari git**

Tidak ada lagi `PYTHONPATH=/src:/src/core` — hanya `/src`.

```bash
cd /data/scorecard_v2/telemarketing-qc-api
docker run --rm -v "$PWD":/src -w /src --entrypoint sh python:3.11-slim -c '
  apt-get update -qq && apt-get install -y -qq --no-install-recommends git gcc >/dev/null
  pip install -q -r api/requirements.txt pytest 2>&1 | tail -3
  PYTHONPATH=/src python -m pytest tests -q 2>&1 | tail -12'
```

Harapan: `0 failed` — jumlah lulusnya sama dengan Task 5 Step 6 (10 file test).

- [ ] **Step 7: Commit**

```bash
cd /data/scorecard_v2/telemarketing-qc-api
git add -A
git commit -m "refactor: pakai telemarketing-qc-core sebagai dependensi, bukan salinan

core/ dihapus (36 file, termasuk core/Jenkinsfile dan core/README.md yang ikut
tersalin tanpa alasan). Seluruh impor kini bernamespace qc_core.*. Dependensi
bersama dideklarasikan hanya di pyproject.toml core."
```

---

## Task 9: Dockerfile multi-stage untuk api

**Repo:** `telemarketing-qc-api`

`pip install git+https://...` memerlukan binary `git`. Multi-stage menaruhnya hanya
di stage builder, sehingga image akhir tidak membawa `git` sama sekali.

**Files:**
- Modify: `api/Dockerfile`

**Interfaces:**
- Consumes: `api/requirements.txt` dari Task 8
- Produces: image `qc-api` yang berjalan tanpa `core/` di build context.

- [ ] **Step 1: Tulis ulang `api/Dockerfile`**

Blok sertifikat dan `SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE` disalin **apa adanya** dari
versi lama — tanpa keduanya setiap operasi MinIO gagal `CERTIFICATE_VERIFY_FAILED`.

```bash
cd /data/scorecard_v2/telemarketing-qc-api
cat > api/Dockerfile <<'EOF'
# Image API — self-contained. Core BUKAN lagi folder di repo ini melainkan
# dependensi pip (telemarketing-qc-core, dipin di api/requirements.txt).
#
#   docker build -f api/Dockerfile -t qc-api .

# --- Stage builder: satu-satunya tempat `git` dibutuhkan -------------------
# pip harus meng-clone core dari git+https. Dengan mengubahnya jadi wheel di
# sini, image akhir tidak perlu memasang git sama sekali.
FROM python:3.11-slim AS builder
RUN apt-get update && apt-get install -y --no-install-recommends git gcc \
    && rm -rf /var/lib/apt/lists/*
COPY api/requirements.txt /tmp/requirements.txt
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r /tmp/requirements.txt

# --- Stage runtime --------------------------------------------------------
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Sertifikat cdn.bankmega.local. Server hanya mengirim leaf-nya tanpa CA
# penerbit ("Bank Mega Local Authority"), jadi leaf itu sendiri yang dipercaya
# --- sama seperti trust store host. Tanpa ini SETIAP operasi MinIO gagal
# CERTIFICATE_VERIFY_FAILED, bukan cuma ensure_buckets() saat startup.
COPY certs/bankmegalocal.crt /usr/local/share/ca-certificates/bankmegalocal.crt
RUN update-ca-certificates

# boto3/botocore dan requests membaca CA dari variabel ini, bukan dari trust
# store sistem secara otomatis. Pasangannya ada di qc_core/services/s3_buckets.py.
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# --no-index: seluruh isi terpasang dari wheel hasil stage builder, tidak ada
# satu pun yang ditarik diam-diam dari jaringan saat stage ini berjalan.
COPY api/requirements.txt /tmp/requirements.txt
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r /tmp/requirements.txt \
    && rm -rf /wheels /tmp/requirements.txt

COPY api           /app/api
COPY alembic.ini   /app/alembic.ini
COPY db/migrations /app/db/migrations
COPY scripts       /app/scripts

EXPOSE 4000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:4000/health || exit 1

# API adalah satu-satunya pemilik migrasi Alembic — worker tidak menjalankannya.
CMD ["sh", "-c", "alembic upgrade head && uvicorn api.main:app --host 0.0.0.0 --port 4000"]
EOF
```

- [ ] **Step 2: Build image**

```bash
cd /data/scorecard_v2/telemarketing-qc-api
docker build -f api/Dockerfile -t qc-api:devendor-test . 2>&1 | tail -20
```

Harapan: build sukses.

- [ ] **Step 3: Buktikan `git` TIDAK ada di image akhir tapi core tetap ter-import**

```bash
docker run --rm --entrypoint sh qc-api:devendor-test -c '
  command -v git && echo "GAGAL: git ikut terbawa" || echo "OK: git tidak ada di image akhir"
  python -c "
import qc_core
from qc_core.db import crud
from qc_core.compliance.documents import load_prompt_module
for d in (\"ktp\", \"kk\", \"npwp\", \"cover_buku_tabungan\"):
    load_prompt_module(d)
import api.main
print(\"OK core\", qc_core.__version__, \"+ api.main ter-import\")
"'
```

Harapan: `OK: git tidak ada di image akhir` dan `OK core 1.0.0 + api.main ter-import`.

- [ ] **Step 4: Buktikan `core/` benar-benar tidak dibutuhkan build context**

```bash
cd /data/scorecard_v2/telemarketing-qc-api
ls core 2>&1 | head -1
docker build -f api/Dockerfile -t qc-api:devendor-test . 2>&1 | tail -3
```

Harapan: `core` tidak ada, build tetap sukses.

- [ ] **Step 5: Commit**

```bash
cd /data/scorecard_v2/telemarketing-qc-api
git add api/Dockerfile
git commit -m "build(api): Dockerfile multi-stage, core dari pip bukan COPY datar

Enam baris COPY core/* hilang. git hanya ada di stage builder untuk mengubah
git+https jadi wheel, sehingga image akhir lebih kecil dan tidak membawa git.
Blok sertifikat bankmegalocal + SSL_CERT_FILE/REQUESTS_CA_BUNDLE tidak berubah."
```

---

## Task 10: CI repo api

**Repo:** `telemarketing-qc-api`

**Files:**
- Create: `.github/workflows/ci.yml`, `.github/workflows/bump-core.yml`
- Delete: `Jenkinsfile`

**Interfaces:**
- Consumes: event `repository_dispatch` bertipe `core-released` dengan
  `client_payload.version` (Task 7)
- Produces: PR otomatis yang mengubah nomor versi di `api/requirements.txt`.

- [ ] **Step 1: Tulis `ci.yml`**

```bash
cd /data/scorecard_v2/telemarketing-qc-api
mkdir -p .github/workflows
cat > .github/workflows/ci.yml <<'EOF'
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r api/requirements.txt pytest
      - run: pytest tests -q
        env:
          PYTHONPATH: ${{ github.workspace }}

  no-worker-import:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      # API mengirim task by name lewat send_task(); ia tidak boleh mengimpor
      # worker, yang memang tidak ada di image API. Dipertahankan dari Jenkinsfile.
      - run: |
          if grep -rnE '^\s*(from|import)\s+worker\b' --include='*.py' api scripts tests; then
            echo "::error::api mengimpor worker -- kirim task by name, jangan impor"
            exit 1
          fi
          echo "bersih"

  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker build -f api/Dockerfile -t qc-api:${{ github.sha }} .
EOF
```

- [ ] **Step 2: Tulis `bump-core.yml`**

```bash
cd /data/scorecard_v2/telemarketing-qc-api
cat > .github/workflows/bump-core.yml <<'EOF'
name: Bump core

# Dikirim oleh workflow Release di telemarketing-qc-core setiap ada tag v*.
on:
  repository_dispatch:
    types: [core-released]
  workflow_dispatch:
    inputs:
      version:
        description: "Versi core, tanpa awalan v (mis. 1.0.1)"
        required: true

jobs:
  bump:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
    steps:
      - uses: actions/checkout@v4

      - id: v
        run: |
          V="${{ github.event.client_payload.version || inputs.version }}"
          if [ -z "$V" ]; then echo "::error::versi kosong"; exit 1; fi
          echo "version=$V" >> "$GITHUB_OUTPUT"

      - name: Ganti nomor versi di api/requirements.txt
        run: |
          sed -i -E \
            "s|(telemarketing-qc-core @ git\+https://github.com/sivi-shahab/telemarketing-qc-core\.git@v).*|\1${{ steps.v.outputs.version }}|" \
            api/requirements.txt
          grep 'telemarketing-qc-core' api/requirements.txt
          # Kalau tidak ada yang berubah, tidak perlu PR.
          git diff --quiet && echo "nochange=1" >> "$GITHUB_ENV" || true

      - if: env.nochange != '1'
        uses: peter-evans/create-pull-request@v6
        with:
          branch: bump-core-${{ steps.v.outputs.version }}
          title: "build: bump qc-core ke v${{ steps.v.outputs.version }}"
          commit-message: "build: bump qc-core ke v${{ steps.v.outputs.version }}"
          body: |
            Bump otomatis dari rilis `telemarketing-qc-core` `v${{ steps.v.outputs.version }}`.

            Changelog: https://github.com/sivi-shahab/telemarketing-qc-core/releases/tag/v${{ steps.v.outputs.version }}

            CI pada PR ini yang memutuskan apakah versi core baru aman untuk repo api.
EOF
```

- [ ] **Step 3: Uji regex `sed`-nya secara lokal sebelum dipercaya**

Ini bagian paling rapuh dari workflow: kalau regex tidak cocok, PR terbentuk tanpa
perubahan apa pun, atau lebih buruk, merusak barisnya.

```bash
cd /data/scorecard_v2/telemarketing-qc-api
cp api/requirements.txt /tmp/req-test.txt
sed -i -E \
  "s|(telemarketing-qc-core @ git\+https://github.com/sivi-shahab/telemarketing-qc-core\.git@v).*|\11.0.1|" \
  /tmp/req-test.txt
grep 'telemarketing-qc-core' /tmp/req-test.txt
diff <(grep -c . api/requirements.txt) <(grep -c . /tmp/req-test.txt) && echo "jumlah baris sama: OK"
```

Harapan: barisnya kini berakhiran `@v1.0.1`, dan jumlah barisnya tidak berubah.

- [ ] **Step 4: Hapus Jenkinsfile, commit, push**

```bash
cd /data/scorecard_v2/telemarketing-qc-api
git rm -q Jenkinsfile
git add .github/workflows/
git commit -m "ci: pindahkan CI api ke GitHub Actions + bump core otomatis

Jenkinsfile lama sudah menyesatkan sejak vendoring: ia masih memanggil
git submodule update --init dan PYTHONPATH=.:core, dua-duanya tidak berlaku.
bump-core.yml menerima repository_dispatch dari rilis core dan membuka PR."
git push origin HEAD
gh run list --limit 3
```

Harapan: CI hijau.

---

## Task 11: De-vendor repo worker

**Repo:** `telemarketing-qc-worker`

Bentuknya sama dengan Task 8 tetapi jauh lebih kecil: hanya 6 file yang mengimpor core.

**Files:**
- Delete: `core/` (36 file)
- Modify: `worker/requirements.txt`
- Modify: `worker/tasks/*.py` dan `scripts/` (6 file)

**Interfaces:**
- Consumes: `telemarketing-qc-core==1.0.0` (Task 7)
- Produces: repo worker tanpa `core/`, impor bernamespace `qc_core.*`.

- [ ] **Step 1: Rewrite impor**

```bash
cd /data/scorecard_v2/telemarketing-qc-worker
python3 - <<'PY'
import pathlib, re

MODULES = ("db", "compliance", "services", "prompt", "sales_lookup", "core_config")
pat = re.compile(r"(?m)^(\s*)(from|import)\s+(%s)\b" % "|".join(MODULES))

changed = 0
for root in ("worker", "scripts"):
    d = pathlib.Path(root)
    if not d.is_dir():
        continue
    for p in d.rglob("*.py"):
        s = p.read_text(encoding="utf-8")
        new = pat.sub(lambda m: f"{m.group(1)}{m.group(2)} qc_core.{m.group(3)}", s)
        if new != s:
            p.write_text(new, encoding="utf-8")
            changed += 1
            print("rewrite:", p)
print("file diubah:", changed)
PY
```

- [ ] **Step 2: Cari sisa pemakaian bergaya atribut dan string modul**

```bash
cd /data/scorecard_v2/telemarketing-qc-worker
grep -rnE '^\s*(from|import)\s+(db|compliance|services|prompt|sales_lookup|core_config)\b' \
  --include='*.py' worker scripts
grep -rnE '(^|[^.\w])(sales_lookup|core_config)\.' --include='*.py' worker scripts | grep -v 'qc_core\.'
grep -rnE '"(db|compliance|services|prompt|sales_lookup|core_config)\.' --include='*.py' worker scripts
```

Harapan: ketiganya tidak mengeluarkan apa-apa. Kalau ada, perbaiki manual.

- [ ] **Step 3: Perbarui `worker/requirements.txt`**

Delapan dependensi ini kini milik core dan dihapus dari sini: `sqlalchemy`,
`psycopg2-binary`, `boto3`, `pdfplumber`, `pypdfium2`, `requests`,
`pydantic-settings`, `openpyxl`. Yang tetap milik worker: `celery[redis]`,
`pillow`, `openai`, `redis`, `flower`, `python-jose[cryptography]`,
`passlib[bcrypt]`, `bcrypt==3.2.2`.

```bash
cd /data/scorecard_v2/telemarketing-qc-worker
cat > worker/requirements.txt <<'EOF'
# Kode bersama. Dependensi core (sqlalchemy, psycopg2-binary, boto3, pdfplumber,
# pypdfium2, requests, pydantic-settings, openpyxl) ikut ter-install dari sini
# dan SENGAJA tidak diulang di bawah -- satu sumber kebenaran versi.
# Baris ini di-bump otomatis oleh .github/workflows/bump-core.yml.
telemarketing-qc-core @ git+https://github.com/sivi-shahab/telemarketing-qc-core.git@v1.0.0

celery[redis]
pillow
openai
redis
flower
python-jose[cryptography]
passlib[bcrypt]
bcrypt==3.2.2
EOF
```

- [ ] **Step 4: Hapus `core/` dan commit**

```bash
cd /data/scorecard_v2/telemarketing-qc-worker
git rm -rq core
git add -A
git commit -m "refactor: pakai telemarketing-qc-core sebagai dependensi, bukan salinan

Pasangan dari perubahan yang sama di repo api."
```

---

## Task 12: Dockerfile multi-stage untuk worker

**Repo:** `telemarketing-qc-worker`

**Files:**
- Modify: `worker/Dockerfile`

**Interfaces:**
- Consumes: `worker/requirements.txt` (Task 11)
- Produces: image `qc-worker` yang dipakai service `worker` dan `flower`.

- [ ] **Step 1: Tulis ulang `worker/Dockerfile`**

```bash
cd /data/scorecard_v2/telemarketing-qc-worker
cat > worker/Dockerfile <<'EOF'
# Image worker — self-contained. Core BUKAN lagi folder di repo ini melainkan
# dependensi pip (telemarketing-qc-core, dipin di worker/requirements.txt).
# Image yang sama dipakai service `worker` dan `flower` (bedanya cuma command).
#
#   docker build -f worker/Dockerfile -t qc-worker .

# --- Stage builder: satu-satunya tempat `git` dibutuhkan -------------------
FROM python:3.11-slim AS builder
RUN apt-get update && apt-get install -y --no-install-recommends git gcc \
    && rm -rf /var/lib/apt/lists/*
COPY worker/requirements.txt /tmp/requirements.txt
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r /tmp/requirements.txt

# --- Stage runtime --------------------------------------------------------
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Sertifikat cdn.bankmega.local. Server hanya mengirim leaf-nya tanpa CA
# penerbit ("Bank Mega Local Authority"), jadi leaf itu sendiri yang dipercaya
# --- sama seperti trust store host, dan sama dengan image API.
COPY certs/bankmegalocal.crt /usr/local/share/ca-certificates/bankmegalocal.crt
RUN update-ca-certificates

# boto3/botocore membaca CA dari SSL_CERT_FILE / REQUESTS_CA_BUNDLE, bukan dari
# trust store sistem secara otomatis. Pasangannya di qc_core/services/s3_buckets.py.
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

COPY worker/requirements.txt /tmp/requirements.txt
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r /tmp/requirements.txt \
    && rm -rf /wheels /tmp/requirements.txt

COPY worker  /app/worker
COPY scripts /app/scripts

# Tempat kerja unduhan transkrip/dokumen sebelum diproses.
RUN mkdir -p /tmp/audio

CMD ["celery", "-A", "worker.celery_app", "worker", "--loglevel=info"]
EOF
```

- [ ] **Step 2: Build dan buktikan modul prompt bisa di-resolve**

`prompt/` dulu di-COPY eksplisit dengan komentar bahwa tanpanya "error-nya baru
muncul saat runtime OCR, bukan saat build". Kini ia datang lewat paket — dan
pembuktiannya harus tetap eksplisit.

```bash
cd /data/scorecard_v2/telemarketing-qc-worker
docker build -f worker/Dockerfile -t qc-worker:devendor-test . 2>&1 | tail -15
docker run --rm --entrypoint sh qc-worker:devendor-test -c '
  command -v git && echo "GAGAL: git ikut terbawa" || echo "OK: git tidak ada di image akhir"
  python -c "
from qc_core.compliance.documents import load_prompt_module
for d in (\"ktp\", \"kk\", \"npwp\", \"cover_buku_tabungan\"):
    assert hasattr(load_prompt_module(d), \"build_prompt\")
print(\"OK: keempat modul prompt ter-resolve\")
"'
```

Harapan: kedua baris `OK`.

- [ ] **Step 3: Buktikan ketiga task Celery tetap terdaftar dengan nama yang sama**

Ini kontrak dengan api, yang mengirim task by name. Kalau nama berubah, task
menggantung di antrian tanpa error yang jelas.

```bash
docker run --rm --entrypoint sh qc-worker:devendor-test -c '
  python -c "
from worker.celery_app import celery_app
import worker.tasks.process_document, worker.tasks.process_transcript, worker.tasks.reprocess_ticket
names = set(celery_app.tasks)
for n in (
    \"worker.tasks.process_document.process_document\",
    \"worker.tasks.process_transcript.process_transcript\",
    \"worker.tasks.reprocess_ticket.reprocess_ticket\",
):
    assert n in names, n
print(\"OK: ketiga task terdaftar\")
"'
```

Harapan: `OK: ketiga task terdaftar`.

- [ ] **Step 4: Commit**

```bash
cd /data/scorecard_v2/telemarketing-qc-worker
git add worker/Dockerfile
git commit -m "build(worker): Dockerfile multi-stage, core dari pip bukan COPY datar

prompt/ kini datang lewat paket, bukan COPY eksplisit; resolusinya dibuktikan
saat build lewat load_prompt_module untuk keempat tipe dokumen."
```

---

## Task 13: Test untuk repo worker

**Repo:** `telemarketing-qc-worker`

Repo worker saat ini nol test. Yang paling berharga untuk diuji bukan logika
internal task, melainkan **kontrak dengan api**: ketiga nama task harus tetap
terdaftar. Tanpa test ini, PR bump core lolos ke worker tanpa satu pun pemeriksaan.

**Files:**
- Create: `tests/__init__.py`, `tests/conftest.py`, `tests/test_task_registry.py`

**Interfaces:**
- Consumes: `worker.celery_app.celery_app`, modul di `worker.tasks.*`
- Produces: status check `test` pada PR repo worker (dipakai Task 14).

- [ ] **Step 1: Tulis test kontrak**

```bash
cd /data/scorecard_v2/telemarketing-qc-worker
mkdir -p tests
: > tests/__init__.py
cat > tests/conftest.py <<'EOF'
"""Default environment supaya import worker.config tidak butuh .env sungguhan."""
import os

os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6378/0")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
EOF
```

Lalu `tests/test_task_registry.py`:

```python
"""Kontrak nama task antara api dan worker.

API tidak pernah mengimpor kode worker: ia memanggil
``celery_app.send_task("<nama>", ...)`` dengan string yang di-hardcode di
``api/celery_client.py``. Jadi nama task adalah antarmuka publik antar repo.
Kalau salah satunya berubah, tidak ada yang error saat build -- task-nya hanya
menggantung di antrian tanpa ada yang mengambil.

Test ini juga menjadi pemeriksaan pertama yang dilalui PR bump qc-core: kalau
rilis core baru membuat modul task gagal di-import, kegagalannya muncul di sini.
"""
import pytest

# Nama yang dikirim api. Sinkron dengan api/celery_client.py di repo
# telemarketing-qc-api -- jangan diubah tanpa mengubah keduanya sekaligus.
EXPECTED_TASKS = (
    "worker.tasks.process_document.process_document",
    "worker.tasks.process_transcript.process_transcript",
    "worker.tasks.reprocess_ticket.reprocess_ticket",
)


@pytest.fixture(scope="module")
def registry():
    from worker.celery_app import celery_app
    # Import eksplisit: task baru terdaftar saat modulnya di-import.
    import worker.tasks.process_document  # noqa: F401
    import worker.tasks.process_transcript  # noqa: F401
    import worker.tasks.reprocess_ticket  # noqa: F401

    return celery_app.tasks


@pytest.mark.parametrize("name", EXPECTED_TASKS)
def test_task_terdaftar_dengan_nama_yang_dipakai_api(name, registry):
    assert name in registry, (
        f"{name} tidak terdaftar. API mengirim task dengan nama ini lewat "
        "send_task(); kalau namanya berubah, task menggantung di antrian."
    )


@pytest.mark.parametrize(
    "module_name",
    [
        "worker.tasks.process_document",
        "worker.tasks.process_transcript",
        "worker.tasks.reprocess_ticket",
    ],
)
def test_modul_task_bisa_diimpor(module_name):
    """Gerbang paling murah untuk PR bump qc-core.

    Ketiga modul ini mengimpor qc_core.db, qc_core.compliance.*, dan
    qc_core.services.*; kalau rilis core baru menghapus atau mengganti nama
    sesuatu yang dipakai worker, ImportError-nya muncul di sini.
    """
    import importlib

    assert importlib.import_module(module_name) is not None
```

- [ ] **Step 2: Jalankan test di dalam image worker**

```bash
cd /data/scorecard_v2/telemarketing-qc-worker
docker run --rm -v "$PWD":/src -w /app --entrypoint sh qc-worker:devendor-test -c '
  pip install -q pytest
  cp -r /src/tests /app/tests
  python -m pytest /app/tests -q 2>&1 | tail -12'
```

Harapan: 6 test lulus (3 nama task + 3 modul), `0 failed`.

- [ ] **Step 3: Commit**

```bash
cd /data/scorecard_v2/telemarketing-qc-worker
git add tests/
git commit -m "test(worker): jaga kontrak nama task Celery dengan api

Repo worker sebelumnya nol test, jadi PR bump qc-core akan lolos tanpa satu pun
pemeriksaan. Yang diuji adalah antarmuka lintas-repo yang sesungguhnya: ketiga
nama task yang dikirim api lewat send_task(), plus keterimporan modulnya."
```

---

## Task 14: CI repo worker

**Repo:** `telemarketing-qc-worker`

**Files:**
- Create: `.github/workflows/ci.yml`, `.github/workflows/bump-core.yml`
- Delete: `Jenkinsfile`

**Interfaces:**
- Consumes: `tests/` (Task 13), event `core-released` (Task 7)
- Produces: PR bump otomatis di repo worker.

- [ ] **Step 1: Tulis `ci.yml`**

```bash
cd /data/scorecard_v2/telemarketing-qc-worker
mkdir -p .github/workflows
cat > .github/workflows/ci.yml <<'EOF'
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r worker/requirements.txt pytest
      - run: pytest tests -q
        env:
          PYTHONPATH: ${{ github.workspace }}

  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker build -f worker/Dockerfile -t qc-worker:${{ github.sha }} .
EOF
```

- [ ] **Step 2: Tulis `bump-core.yml`**

Identik dengan milik api kecuali path `worker/requirements.txt` dan judul PR-nya.

```bash
cd /data/scorecard_v2/telemarketing-qc-worker
cat > .github/workflows/bump-core.yml <<'EOF'
name: Bump core

on:
  repository_dispatch:
    types: [core-released]
  workflow_dispatch:
    inputs:
      version:
        description: "Versi core, tanpa awalan v (mis. 1.0.1)"
        required: true

jobs:
  bump:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
    steps:
      - uses: actions/checkout@v4

      - id: v
        run: |
          V="${{ github.event.client_payload.version || inputs.version }}"
          if [ -z "$V" ]; then echo "::error::versi kosong"; exit 1; fi
          echo "version=$V" >> "$GITHUB_OUTPUT"

      - name: Ganti nomor versi di worker/requirements.txt
        run: |
          sed -i -E \
            "s|(telemarketing-qc-core @ git\+https://github.com/sivi-shahab/telemarketing-qc-core\.git@v).*|\1${{ steps.v.outputs.version }}|" \
            worker/requirements.txt
          grep 'telemarketing-qc-core' worker/requirements.txt
          git diff --quiet && echo "nochange=1" >> "$GITHUB_ENV" || true

      - if: env.nochange != '1'
        uses: peter-evans/create-pull-request@v6
        with:
          branch: bump-core-${{ steps.v.outputs.version }}
          title: "build: bump qc-core ke v${{ steps.v.outputs.version }}"
          commit-message: "build: bump qc-core ke v${{ steps.v.outputs.version }}"
          body: |
            Bump otomatis dari rilis `telemarketing-qc-core` `v${{ steps.v.outputs.version }}`.

            Changelog: https://github.com/sivi-shahab/telemarketing-qc-core/releases/tag/v${{ steps.v.outputs.version }}

            CI pada PR ini yang memutuskan apakah versi core baru aman untuk repo worker.
EOF
```

- [ ] **Step 3: Uji regex `sed`-nya secara lokal**

```bash
cd /data/scorecard_v2/telemarketing-qc-worker
cp worker/requirements.txt /tmp/wreq-test.txt
sed -i -E \
  "s|(telemarketing-qc-core @ git\+https://github.com/sivi-shahab/telemarketing-qc-core\.git@v).*|\11.0.1|" \
  /tmp/wreq-test.txt
grep 'telemarketing-qc-core' /tmp/wreq-test.txt
```

Harapan: barisnya berakhiran `@v1.0.1`.

- [ ] **Step 4: Hapus Jenkinsfile, commit, push kedua repo**

```bash
cd /data/scorecard_v2/telemarketing-qc-worker
git rm -q Jenkinsfile
git add .github/workflows/
git commit -m "ci: pindahkan CI worker ke GitHub Actions + bump core otomatis"
git push origin HEAD
gh run list --limit 3
```

Harapan: CI hijau.

---

## Task 15: Buktikan rantai bump otomatis dari ujung ke ujung

Sampai titik ini setiap bagian sudah diuji sendiri-sendiri, tetapi rantai
core → dispatch → PR di dua repo **belum pernah dijalankan utuh**. Task ini
membuktikannya dengan rilis kecil yang sungguhan.

**Files:**
- Modify: `pyproject.toml`, `src/qc_core/__init__.py` (di repo core)

**Interfaces:**
- Consumes: Task 7, 10, 14
- Produces: bukti bahwa rilis core membuka PR bump di api dan worker tanpa
  seorang pun menyunting kode kedua repo itu.

- [ ] **Step 1: Naikkan versi core ke 1.0.1**

```bash
cd /data/scorecard_v2/telemarketing-qc-core
sed -i 's/^version = "1.0.0"$/version = "1.0.1"/' pyproject.toml
sed -i 's/^__version__ = "1.0.0"$/__version__ = "1.0.1"/' src/qc_core/__init__.py
grep -n 'version' pyproject.toml src/qc_core/__init__.py | grep '1\.0\.'
```

- [ ] **Step 2: Sesuaikan test versi**

`tests/test_packaging.py::test_version_terekspos` mem-pin `1.0.0`. Agar tidak perlu
disunting setiap rilis, ikat ia ke metadata distribusi, bukan ke angka literal:

```python
def test_version_terekspos():
    """__version__ harus sama dengan versi distribusi yang ter-install.

    Diikat ke metadata, bukan ke angka literal, supaya rilis berikutnya tidak
    perlu menyunting test ini -- tetapi __init__.py yang lupa dinaikkan tetap
    tertangkap.
    """
    from importlib.metadata import version

    assert qc_core.__version__ == version("telemarketing-qc-core")
```

Tambahkan `from importlib.metadata import version` di dalam fungsi seperti di atas
(bukan di puncak file) supaya alasannya tetap terbaca di tempatnya.

- [ ] **Step 3: Jalankan test, commit, rilis**

```bash
cd /data/scorecard_v2/telemarketing-qc-core
docker run --rm -v "$PWD":/src -w /tmp --entrypoint sh python:3.11-slim -c '
  pip install -q "/src[test]" 2>&1 | tail -2
  cp -r /src/tests /tmp/tests && python -m pytest /tmp/tests -q 2>&1 | tail -6'
git add pyproject.toml src/qc_core/__init__.py tests/test_packaging.py
git commit -m "chore: rilis 1.0.1 — uji rantai bump otomatis ujung ke ujung

Versi diikat ke metadata distribusi supaya test tidak perlu disunting tiap rilis."
git push origin HEAD
git tag v1.0.1 && git push origin v1.0.1
```

- [ ] **Step 4: Pastikan PR bump terbuka di kedua repo**

```bash
sleep 60
gh pr list --repo sivi-shahab/telemarketing-qc-api --search "bump qc-core"
gh pr list --repo sivi-shahab/telemarketing-qc-worker --search "bump qc-core"
```

Harapan: satu PR terbuka di masing-masing repo, berjudul `build: bump qc-core ke v1.0.1`.

**Kalau tidak ada PR yang terbuka**, penyebab paling mungkin, berurutan:
1. Secret `CROSS_REPO_TOKEN` tidak ada atau kurang scope — cek log job `notify` di
   run Release repo core.
2. Setting repo tujuan melarang Actions membuat PR — aktifkan **Settings → Actions →
   General → Allow GitHub Actions to create and approve pull requests**.
3. Regex `sed` tidak cocok sehingga `nochange=1` — jalankan `workflow_dispatch`
   manual dengan input versi untuk melihat log-nya.

- [ ] **Step 5: Merge kedua PR setelah CI-nya hijau**

```bash
gh pr checks --repo sivi-shahab/telemarketing-qc-api
gh pr checks --repo sivi-shahab/telemarketing-qc-worker
```

Merge hanya kalau kedua-duanya hijau. Ini menutup lingkaran: sejak titik ini,
perubahan core sampai ke api dan worker tanpa seorang pun menyunting kode kedua repo.

- [ ] **Step 6: Perbarui README ketiga repo**

Ketiganya masih menjelaskan core sebagai folder yang di-copy. Perbarui bagian
instalasi/arsitekturnya supaya menyebut:

- Core adalah distribusi pip `telemarketing-qc-core`, di-pin di `requirements.txt`.
- Impor bernamespace `qc_core.*`.
- Untuk pengembangan lokal: `pip install -e ../telemarketing-qc-core` membuat
  perubahan core langsung terasa di api/worker tanpa perlu rilis.
- Rilis core = naikkan `version` di `pyproject.toml` + `__version__`, tag `vX.Y.Z`,
  push tag; PR bump terbuka sendiri di api dan worker.

```bash
cd /data/scorecard_v2/telemarketing-qc-core && git add README.md && git commit -m "docs: core kini paket pip, bukan folder yang disalin" && git push origin HEAD
cd /data/scorecard_v2/telemarketing-qc-api  && git add README.md && git commit -m "docs: core kini dependensi pip dengan namespace qc_core" && git push origin HEAD
cd /data/scorecard_v2/telemarketing-qc-worker && git add README.md && git commit -m "docs: core kini dependensi pip dengan namespace qc_core" && git push origin HEAD
```

---

## Verifikasi akhir

- [ ] `telemarketing-qc-api/core/` dan `telemarketing-qc-worker/core/` tidak ada lagi
- [ ] `grep -rn "^from db\|^from compliance\|^import sales_lookup"` di api dan worker tidak menghasilkan apa-apa
- [ ] Suite core hijau; suite api hijau (10 file); suite worker hijau (6 test)
- [ ] `docker build` sukses di kedua repo tanpa `core/` di build context
- [ ] `command -v git` gagal di dalam image `qc-api` dan `qc-worker`
- [ ] Ketiga nama task Celery masih terdaftar
- [ ] Rilis `v1.0.1` membuka PR bump di api dan worker tanpa campur tangan manusia
- [ ] Tidak ada `Jenkinsfile` tersisa di ketiga repo
- [ ] Tidak ada transkrip nasabah atau `.env` yang ter-commit ke repo core yang publik
