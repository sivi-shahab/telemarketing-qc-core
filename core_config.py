"""Konfigurasi milik core — sengaja minimal.

Sebelum pemisahan repo, `sales_lookup` mengambil MinIO client dan Settings dari
``api.dependencies``. Itu membuat core (dan lewat ``compliance.stats_aggregate``
juga worker) tidak bisa jalan tanpa folder ``api/``. Modul ini menggantikannya
dengan konfigurasi milik core sendiri: HANYA field yang benar-benar dipakai kode
bersama, dibaca dari environment / ``.env`` yang sama persis dengan API dan
worker, sehingga nilainya identik tanpa perlu saling impor.

Nama file sengaja ``core_config`` (bukan ``config``) karena isi core di-copy
datar ke ``/app`` di image API dan worker — ``config.py`` terlalu umum dan
berisiko bentrok dengan modul lain di root.
"""
from functools import lru_cache

from minio import Minio
from pydantic_settings import BaseSettings


class CoreSettings(BaseSettings):
    """Subset Settings yang dipakai kode bersama (default sama dengan API)."""

    minio_endpoint: str = "minio:4003"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "changeme123"
    # API memakai secure=False (MinIO internal via http). Dibuat env-overridable
    # supaya deployment lewat CDN/https tidak perlu ubah kode.
    minio_secure: bool = False
    minio_bucket_sales_database: str = "sales-database"

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"


@lru_cache()
def get_core_settings() -> CoreSettings:
    return CoreSettings()


_minio_client: Minio = None


def get_minio() -> Minio:
    """MinIO client milik core (lazy, satu instance per proses)."""
    global _minio_client
    if _minio_client is None:
        settings = get_core_settings()
        _minio_client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
    return _minio_client
