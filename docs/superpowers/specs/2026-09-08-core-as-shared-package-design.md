# Core sebagai paket bersama, bukan salinan

Tanggal: 2026-09-08
Status: disetujui, siap masuk rencana implementasi
Repo terdampak: `telemarketing-qc-core`, `telemarketing-qc-api`, `telemarketing-qc-worker`

## Masalah

`core/` di repo api dan worker adalah **salinan penuh** repo `telemarketing-qc-core`
yang ikut di-commit (`feat(core): vendor modul core ke repo api untuk build image`).
Konsekuensinya:

- Setiap perubahan core menuntut commit salinan di dua repo lain. Sinkronisasi
  dijaga oleh disiplin manusia, bukan oleh mesin.
- Tidak ada yang mencatat versi core mana yang ada di dalam sebuah image, jadi
  rollback core secara mandiri tidak mungkin.
- Impor bersifat datar (`from db import crud`), dipertahankan dengan menyalin isi
  core **rata ke `/app`** di Dockerfile. Kode core lalu memakai trik `sys.path`
  untuk menutupi konsekuensinya.
- `Jenkinsfile` repo api sudah tidak sinkron dengan kenyataan: ia masih memanggil
  `git submodule update --init --recursive` dan `PYTHONPATH=.:core`, sisa dari
  rencana submodule yang tidak jadi dipakai.

Saat ditulis, isi ketiga salinan identik kecuali `README.md` — jadi ini dikerjakan
sebelum drift benar-benar terjadi, bukan sesudahnya.

## Sasaran

Core menjadi **dependensi ter-install yang di-versi**. Perubahan core sampai ke api
dan worker tanpa seorang pun menyunting kode kedua repo itu, tetapi setiap image
tetap mencatat persis versi core yang dikandungnya.

## Bukan sasaran

- **Dashboard.** Frontend Vite/JS, tidak punya `core/`, bicara ke api lewat HTTP.
  Tidak ada satu file pun yang berubah.
- **Manifest Kubernetes.** Belum ada di keempat repo (yang ada baru
  docker-compose). Menjadi spec tersendiri setelah pekerjaan ini selesai.
  Kubernetes tidak mengubah desain ini: yang di-deploy ke cluster adalah image
  `qc-api` dan `qc-worker` yang sudah jadi, dan berbagi kode selesai di tahap build.
- **Perubahan perilaku apa pun.** Seluruh pekerjaan ini build-time. Container yang
  sedang berjalan di produksi tidak tersentuh sampai image baru di-deploy.

## Keputusan

| Keputusan | Pilihan | Alasan |
|---|---|---|
| Distribusi | `pip install` dari git tag | Repo core publik (GitHub API balas 200 tanpa kredensial), jadi tidak perlu deploy token. Satu-satunya opsi yang sekaligus menyelesaikan `pytest` lokal dan IDE tanpa trik `PYTHONPATH`. |
| Namespace | `qc_core.*` | Nama datar `db`, `prompt`, `services` akan merebut namespace top-level di `site-packages`; tabrakan dengan dependensi pihak ketiga muncul sebagai `ImportError` yang sangat sulit dilacak. |
| Versioning | Pin versi + bump otomatis | Build reproducible dan rollback tetap mungkin, tanpa manusia menyunting api/worker. |
| CI | GitHub Actions | Kode sudah di GitHub; bump PR lintas-repo bisa dibuka tanpa infrastruktur tambahan. Jenkinsfile yang ada memang harus ditulis ulang apa pun pilihannya. |

Ditolak: **base image Docker** menyelesaikan build tapi tidak menyelesaikan test —
`pytest` tetap butuh core di `sys.path`, jadi tetap perlu mekanisme kedua. Layak
ditambahkan kemudian murni sebagai cache dependensi berat (`pdfplumber`,
`pypdfium2`), di atas pondasi paket. **Submodule** memindahkan masalah tanpa
menghapusnya: `core/` tetap ada di working tree, pin tetap perlu di-commit di dua
repo, dan `--init` yang terlewat membuat build gagal senyap. **PyPI internal**
sebetulnya tujuan akhir paling ideal, tapi tidak ditemukan jejak Nexus/Artifactory
di konfigurasi mana pun; migrasi ke sana nanti hanya mengganti satu baris
`requirements.txt` karena bentuk paketnya sudah benar.

## Arsitektur

### Paket core

```
telemarketing-qc-core/
├── pyproject.toml
├── src/qc_core/
│   ├── __init__.py            # __version__
│   ├── core_config.py
│   ├── sales_lookup.py
│   ├── db/          __init__.py  crud.py  models.py
│   ├── compliance/  ... error_reasons.json, *.xlsx
│   ├── prompt/      _common.py  ocr_ktp.py  ocr_kk.py  ocr_npwp.py
│   │                ocr_cover_buku_tabungan.py
│   └── services/    data_dwh.py  s3_buckets.py  tickets_daily.py
│                    view_streams.py
└── tests/
```

Layout `src/` dipilih supaya `pytest` tidak bisa lulus hanya karena kebetulan
membaca folder kerja; ia memaksa test menguji paket yang benar-benar ter-install.

`pyproject.toml` mendeklarasikan distribusi `telemarketing-qc-core` versi `1.0.0`,
dependensi (dipindah dari `requirements.txt`, kini dengan batas bawah eksplisit),
dan **package-data**. Dua file non-Python wajib ikut ke dalam wheel:

- `compliance/error_reasons.json` — dibaca saat import oleh `error_reasons.py`
  lewat `os.path.dirname(__file__)`. Kalau tidak ikut, import core gagal.
- `compliance/Error Reason - Telemarketing QC_05082025 (1).xlsx`

`requirements.txt` core dihapus; `pyproject.toml` menggantikannya sebagai satu-satunya
tempat dependensi core dideklarasikan.

### Dua trik yang dihapus

Keduanya adalah konsekuensi langsung dari copy-datar dan tidak lagi punya alasan
untuk ada setelah core menjadi paket:

1. `compliance/documents.py` menyisipkan repo root ke `sys.path` secara manual
   (`_REPO_ROOT = dirname(dirname(abspath(__file__)))`, lalu `sys.path.insert`),
   dengan komentar "the celery worker's sys.path does not reliably include the
   repo root". Blok ini dihapus.
2. String di `DOCUMENT_TYPES` (`"prompt.ocr_ktp"`, `"prompt.ocr_kk"`,
   `"prompt.ocr_npwp"`, `"prompt.ocr_cover_buku_tabungan"`) yang di-resolve lewat
   `importlib.import_module()` di `load_prompt_module()` menjadi `qc_core.prompt.*`.
   Ini **tidak akan tertangkap** oleh rewrite impor otomatis karena berupa string —
   harus diubah manual dan diuji secara eksplisit.

`core_config.py` tidak berubah perilakunya: `env_file = ".env"` tetap relatif
terhadap CWD, jadi api dan worker membaca `.env` yang sama seperti sekarang.

### api dan worker

Satu PR atomik per repo:

- `core/` dihapus (`git rm -r core`), termasuk `core/Jenkinsfile` dan
  `core/README.md` yang ikut tersalin dan tidak pernah punya alasan untuk ada di sana.
- `requirements.txt` mendapat satu baris:
  `telemarketing-qc-core @ git+https://github.com/sivi-shahab/telemarketing-qc-core.git@v1.0.0`
- 238 baris impor di 43 file (37 file di api, 6 di worker) di-rewrite ke `qc_core.*`
  lewat skrip mekanis, diverifikasi oleh test.
- Dependensi yang kini datang dari core dihapus dari `requirements.txt` masing-masing
  supaya tidak ada dua sumber kebenaran: `sqlalchemy`, `psycopg2-binary`, `boto3`,
  `openpyxl`, `pdfplumber`, `requests`, `pydantic-settings` (dan `pypdfium2` di worker).

### Dockerfile multi-stage

`pip install git+https://...` **memerlukan binary `git` di dalam image**. Ini
diselesaikan dengan multi-stage, bukan dengan `apt-get install git` di image akhir:

```dockerfile
FROM python:3.11-slim AS builder
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY api/requirements.txt /tmp/requirements.txt
# Satu-satunya langkah yang butuh `git`: mengubah git+https menjadi wheel.
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r /tmp/requirements.txt

FROM python:3.11-slim
WORKDIR /app
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1
# ... sertifikat bankmegalocal.crt + SSL_CERT_FILE/REQUESTS_CA_BUNDLE:
#     tidak berubah sedikit pun dari Dockerfile sekarang.
COPY api/requirements.txt /tmp/requirements.txt
COPY --from=builder /wheels /wheels
# --no-index memastikan build tidak diam-diam menarik apa pun dari jaringan:
# semua yang ter-install berasal dari wheel yang dibangun di stage builder.
RUN pip install --no-cache-dir --no-index --find-links=/wheels \
    -r /tmp/requirements.txt && rm -rf /wheels /tmp/requirements.txt
COPY api /app/api
# ... alembic.ini, db/migrations, scripts: tidak berubah.
```

Enam baris `COPY core/...` yang menyalin datar hilang seluruhnya, dan image akhir
tidak membawa `git` — lebih kecil sekaligus lebih rapat permukaan serangannya.
`PYTHONPATH=/app` tetap ada, tapi kini hanya untuk kode api/worker sendiri.

Yang **tidak** berubah di Dockerfile: sertifikat `bankmegalocal.crt` dan
`update-ca-certificates`, serta `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE`. Keduanya
wajib untuk setiap operasi S3/MinIO dan tidak ada hubungannya dengan vendoring.

## Testing

Repo api punya 17 file test. Tujuh di antaranya murni menguji kode core dan ikut
pindah ke repo core; sepuluh sisanya tetap di api.

**Pindah ke core** (diverifikasi: tidak satu pun memakai fixture `db`/`admin_user`,
jadi tidak butuh koneksi database — pemindahannya bersih):

| File | Menguji |
|---|---|
| `test_campaign_kind.py` | `compliance.campaign_kind` |
| `test_cashline_agent_index.py` | `db` (snapshot cashline) |
| `test_evaluator.py` | `compliance.evaluator` |
| `test_hierarchy_avg_failure_rate.py` | `compliance.stats_aggregate` |
| `test_missing_docs_snapshot_first.py` | `compliance`, `db` |
| `test_pdf_parser.py` | `compliance.pdf_parser` |
| `test_sales_roster_placeholders.py` | `sales_lookup` |

**Tetap di api** karena mengimpor `api.*`: `test_agent_error_snapshot_first`,
`test_audio_recording_dir`, `test_campaign_context_scope`,
`test_migrate_users_from_monolith`, `test_qc_assignment_auto`,
`test_rbac_collection_permissions`, `test_reprocess_active_flag`,
`test_reprocess_filtered`, `test_riplay_config`, `test_tickets_daily_pdf_proxy`.

`test_riplay_config` sempat terlihat seperti test core, tetapi mengimpor
`api.dependencies` dan `api.routers` — jadi tetap di api.

`conftest.py` api tidak berubah selain rewrite impor: ketiga test yang memakai
fixture `db` (`test_reprocess_active_flag`, `test_reprocess_filtered`,
`test_rbac_collection_permissions`) semuanya tetap di api, dan fixture itu memang
bergantung pada `api.dependencies._make_engine`. `conftest.py` core yang baru hanya
perlu menetapkan default environment, tanpa fixture database.

**Test baru untuk worker.** Repo worker kini nol test. Ditambahkan test dasar untuk
task Celery utama, cukup untuk memastikan modul task bisa di-import dan
terdaftar — supaya PR bump core tidak pernah lolos tanpa satu pun pemeriksaan di
sisi worker.

Pemindahan tujuh test itulah yang memberi arti pada gerbang bump otomatis: core
tidak bisa dirilis dalam keadaan rusak, karena test-nya berjalan di CI core sebelum
tag dibuat.

## CI/CD

`Jenkinsfile` dihapus dari core, api, dan worker. Yang di repo api sudah menyesatkan
sejak vendoring (masih mengasumsikan submodule); menyimpannya lebih berbahaya
daripada menghapusnya.

**Repo core**

- `ci.yml` — pada push dan PR: `pip install -e .[test]`, `pytest`. Ditambah cek yang
  dipertahankan dari Jenkinsfile lama: core tidak boleh mengimpor `api` maupun
  `worker` (`grep -rn --include=*.py -E "^\s*(from|import)\s+(api|worker)\b" src/`
  harus kosong).
- `release.yml` — pada tag `v*`: build wheel, lampirkan ke GitHub Release, lalu
  kirim `repository_dispatch` ber-payload versi ke repo api dan worker.

**Repo api dan worker**

- `ci.yml` — pada push dan PR: `pytest`, lalu `docker build`.
- `bump-core.yml` — menerima `repository_dispatch` dari core, mengganti nomor versi
  di `requirements.txt`, dan membuka PR. CI PR itulah yang memutuskan apakah versi
  core baru aman untuk repo ini.

Versi mengikuti SemVer. Deskripsi PR bump mencantumkan changelog core di antara dua
versi, sehingga peninjau tahu apa yang sedang masuk.

## Urutan cutover

Berurutan, tidak paralel, supaya tidak pernah ada jendela waktu di mana api atau
worker rusak.

0. **Prasyarat.** HEAD lokal repo core (`a2dcd15`) belum ter-push; remote masih di
   `e91cace`. Push dulu — rilis `v1.0.0` harus dibuat dari commit yang benar-benar
   ada di remote.
1. **core.** Restrukturisasi ke `src/qc_core/`, `pyproject.toml`, pindahkan tujuh
   test, tulis CI. Rilis tag `v1.0.0`.
2. **api.** Satu PR atomik (hapus `core/`, rewrite impor, requirements, Dockerfile
   multi-stage). Merge setelah CI hijau.
3. **worker.** Sama.
4. **Aktifkan auto-bump** setelah api dan worker dua-duanya hijau.

Sampai langkah 3 selesai, image yang berjalan di produksi tidak tersentuh.

## Risiko

| Risiko | Penanganan |
|---|---|
| String `prompt_module` luput dari rewrite otomatis → gagal saat runtime OCR, bukan saat build | Diubah manual, dengan test eksplisit yang memanggil `load_prompt_module()` untuk keempat tipe dokumen |
| `error_reasons.json` tidak ikut ke wheel → core gagal di-import | Test yang meng-import `qc_core.compliance.error_reasons` dijalankan terhadap paket ter-install (dipaksa oleh layout `src/`), bukan terhadap folder kerja |
| Rewrite impor merusak sesuatu yang tidak ter-cover test | Rewrite mekanis + review diff; suite api yang tersisa (10 file) jadi jaring pengaman |
| Repo core dijadikan private di kemudian hari → `docker build` kehilangan akses | Stage `builder` sudah terpisah; tinggal menambahkan BuildKit secret di sana, tanpa mengubah desain |
| Versi core dan versi dependensi bersama tidak sinkron (mis. `sqlalchemy` di-pin berbeda) | Dependensi bersama dideklarasikan **hanya** di `pyproject.toml` core dan dihapus dari `requirements.txt` api/worker |

## Referensi

- Monolith `telemarketing-qc-system` bersifat baca-saja dan bukan bagian dari
  pekerjaan ini.
- Rute nginx host (`/api-b/` → api :4000) tidak berubah.
