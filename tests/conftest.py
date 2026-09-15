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
