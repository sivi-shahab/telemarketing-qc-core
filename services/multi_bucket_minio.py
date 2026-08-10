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
    bucket_credential_map = {
        settings.minio_bucket_transcripts: (
            settings.minio_access_key_transcripts, settings.minio_secret_key_transcripts,
        ),
        settings.minio_bucket_results: (
            settings.minio_access_key_results, settings.minio_secret_key_results,
        ),
        settings.minio_bucket_campaigns: (
            settings.minio_access_key_campaigns, settings.minio_secret_key_campaigns,
        ),
        settings.minio_bucket_documents: (
            settings.minio_access_key_documents, settings.minio_secret_key_documents,
        ),
        settings.minio_bucket_audio: (
            settings.minio_access_key_audio, settings.minio_secret_key_audio,
        ),
        settings.minio_bucket_sales_database: (
            settings.minio_access_key_sales_database, settings.minio_secret_key_sales_database,
        ),
    }

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
            secure=settings.minio_secure,
        )
        logger.info(
            "[multi-bucket-minio] Bucket '%s' -> access_key='%s' @ %s (secure=%s)",
            bucket_name, access_key, settings.minio_endpoint, settings.minio_secure,
        )

    return MultiBucketMinioClient(bucket_clients)
