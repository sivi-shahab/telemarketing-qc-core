"""
services/multi_bucket_minio.py (App B)

Wrapper di sekitar beberapa client `Minio` (1 per bucket, kredensial
berbeda-beda) yang API-nya IDENTIK dengan client Minio biasa -- supaya
SEMUA kode yang sudah ada (mis. `client.put_object(settings.minio_bucket_results,
object_name, ...)`, tersebar di banyak file: upload_transcript, webhook,
dll) TIDAK PERLU DIUBAH SAMA SEKALI.

Cara kerja: tiap method (put_object/get_object/copy_object/list_objects/dst)
menerima `bucket_name` sebagai argumen pertama (persis seperti Minio asli),
lalu wrapper ini "route" ke client Minio yang SESUAI (yang sudah dibuat
dengan access_key/secret_key khusus bucket itu).
"""
import logging
from typing import Dict

from minio import Minio

logger = logging.getLogger(__name__)


class MultiBucketMinioClient:
    """Routing otomatis ke Minio client yang benar berdasarkan nama bucket.

    ``bucket_clients``: dict {nama_bucket: instance Minio sudah terkonfigurasi
    dengan endpoint+access_key+secret_key KHUSUS bucket itu}.
    """

    def __init__(self, bucket_clients: Dict[str, Minio]):
        self._clients = bucket_clients

    def is_configured(self) -> bool:
        """True kalau minimal SATU bucket punya kredensial sendiri.

        Dipakai ``build_minio_client()`` untuk memutuskan mode: kalau belum ada
        satu pun (deployment lokal yang masih pakai admin key global), wrapper
        ini tidak berguna dan client Minio tunggal yang dipakai.
        """
        return bool(self._clients)

    def _client_for(self, bucket_name: str) -> Minio:
        client = self._clients.get(bucket_name)
        if client is None:
            raise ValueError(
                f"[multi-bucket-minio] Tidak ada kredensial terdaftar untuk "
                f"bucket '{bucket_name}' -- cek settings minio_access_key_*/"
                f"minio_secret_key_* dan pastikan bucket ini sudah didaftarkan "
                f"di get_minio()."
            )
        return client

    # --- Method yang API-nya SAMA PERSIS dengan Minio asli ---
    def put_object(self, bucket_name: str, *args, **kwargs):
        return self._client_for(bucket_name).put_object(bucket_name, *args, **kwargs)

    def get_object(self, bucket_name: str, *args, **kwargs):
        return self._client_for(bucket_name).get_object(bucket_name, *args, **kwargs)

    def fget_object(self, bucket_name: str, *args, **kwargs):
        return self._client_for(bucket_name).fget_object(bucket_name, *args, **kwargs)

    def copy_object(self, bucket_name: str, *args, **kwargs):
        # Catatan: CopySource(bucket_asal, key_asal) dianggap bucket_asal SAMA
        # dengan bucket_name (destinasi) -- ini asumsi WAJAR untuk semua
        # pemakaian copy_object di codebase ini (copy dalam bucket yang sama,
        # cuma pindah path/key). Kalau nanti ada copy LINTAS bucket beda
        # kredensial, wrapper ini PERLU disesuaikan (belum didukung).
        return self._client_for(bucket_name).copy_object(bucket_name, *args, **kwargs)

    def list_objects(self, bucket_name: str, *args, **kwargs):
        return self._client_for(bucket_name).list_objects(bucket_name, *args, **kwargs)

    def bucket_exists(self, bucket_name: str) -> bool:
        return self._client_for(bucket_name).bucket_exists(bucket_name)

    def make_bucket(self, bucket_name: str, *args, **kwargs):
        return self._client_for(bucket_name).make_bucket(bucket_name, *args, **kwargs)

    def remove_object(self, bucket_name: str, *args, **kwargs):
        return self._client_for(bucket_name).remove_object(bucket_name, *args, **kwargs)

    def stat_object(self, bucket_name: str, *args, **kwargs):
        return self._client_for(bucket_name).stat_object(bucket_name, *args, **kwargs)


# Urutan field di Settings: (nama bucket, access key, secret key). Bucket yang
# field-nya tidak ada di Settings aplikasi ybs dilewati (lihat getattr di bawah).
_BUCKET_CREDENTIAL_FIELDS = (
    ("minio_bucket_transcripts", "minio_access_key_transcripts", "minio_secret_key_transcripts"),
    ("minio_bucket_results", "minio_access_key_results", "minio_secret_key_results"),
    ("minio_bucket_campaigns", "minio_access_key_campaigns", "minio_secret_key_campaigns"),
    ("minio_bucket_documents", "minio_access_key_documents", "minio_secret_key_documents"),
    ("minio_bucket_audio", "minio_access_key_audio", "minio_secret_key_audio"),
    ("minio_bucket_sales_database", "minio_access_key_sales_database", "minio_secret_key_sales_database"),
    # qc-database dinonaktifkan: setting minio_bucket_qc_database di-comment,
    # jadi bucket ini tidak ikut dipetakan sama sekali.
    # ("minio_bucket_qc_database", "minio_access_key_qc_database", "minio_secret_key_qc_database"),
)


def _has_per_bucket_credentials(settings) -> bool:
    """True kalau ada MINIO_ACCESS_KEY_<BUCKET> + secret-nya yang terisi."""
    return any(
        getattr(settings, access_key_field, "") and getattr(settings, secret_key_field, "")
        for _, access_key_field, secret_key_field in _BUCKET_CREDENTIAL_FIELDS
    )


def build_multi_bucket_client(settings) -> MultiBucketMinioClient:
    """[NEW] Bangun MultiBucketMinioClient dari Settings -- 1 client Minio
    per bucket, masing-masing pakai access_key/secret_key sendiri, semua
    connect ke settings.minio_endpoint (cdn.bankmega.local) yang SAMA.

    Bucket yang credential-nya KOSONG (access_key/secret_key belum diisi
    di .env) DILEWATI dengan warning -- supaya startup TIDAK GAGAL TOTAL
    kalau baru sebagian bucket yang sudah di-setup kredensialnya (migrasi
    bertahap), tapi pemakaian bucket itu nanti akan error jelas (lewat
    _client_for() di atas), bukan diam-diam pakai kredensial salah.
    """
    bucket_credential_map: Dict[str, tuple] = {}
    for bucket_field, access_key_field, secret_key_field in _BUCKET_CREDENTIAL_FIELDS:
        # getattr, BUKAN akses langsung: tiap aplikasi punya Settings sendiri
        # (API lengkap, worker lebih sedikit, core cuma sales-database) dan
        # bucket yang tidak dikenal Settings itu memang tidak dipakai di sana.
        bucket_name = getattr(settings, bucket_field, "")
        if not bucket_name:
            continue
        bucket_credential_map[bucket_name] = (
            getattr(settings, access_key_field, ""),
            getattr(settings, secret_key_field, ""),
        )

    bucket_clients: Dict[str, Minio] = {}
    for bucket_name, (access_key, secret_key) in bucket_credential_map.items():
        if not access_key or not secret_key:
            logger.warning(
                "[multi-bucket-minio] Kredensial kosong untuk bucket '%s' -- "
                "dilewati (akan error kalau dipakai nanti, bukan salah diam-diam).",
                bucket_name,
            )
            continue
        bucket_clients[bucket_name] = Minio(
            settings.minio_endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=getattr(settings, "minio_secure", False),
        )
        logger.info(
            "[multi-bucket-minio] Bucket '%s' -> access_key='%s' @ %s (secure=%s)",
            bucket_name, access_key, settings.minio_endpoint,
            getattr(settings, "minio_secure", False),
        )

    return MultiBucketMinioClient(bucket_clients)


def build_minio_client(settings):
    """[NEW] Satu-satunya cara API/worker/core bikin client MinIO.

    Mengembalikan ``MultiBucketMinioClient`` kalau .env sudah mengisi kredensial
    per-bucket (deployment CDN), dan client ``Minio`` tunggal pakai
    ``minio_access_key``/``minio_secret_key`` kalau belum (deployment docker
    lokal). Keduanya punya API yang sama, jadi pemanggilnya tidak perlu tahu
    sedang di mode yang mana.
    """
    secure = getattr(settings, "minio_secure", False)

    # Cek dulu SEBELUM build: kalau memang belum ada kredensial per-bucket sama
    # sekali (deployment lokal), build_multi_bucket_client() cuma akan mencetak
    # satu warning per bucket yang tidak relevan di mode itu.
    if _has_per_bucket_credentials(settings):
        multi = build_multi_bucket_client(settings)
        if multi.is_configured():
            return multi

    logger.info(
        "[minio] Belum ada kredensial per-bucket -- pakai satu client global "
        "@ %s (secure=%s).", settings.minio_endpoint, secure,
    )
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=secure,
    )
