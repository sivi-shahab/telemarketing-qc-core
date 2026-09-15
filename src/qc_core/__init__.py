"""Kode bersama telemarketing QC: db, compliance, prompt, services.

Di-install sebagai distribusi ``telemarketing-qc-core`` dan dipakai oleh repo
``telemarketing-qc-api`` dan ``telemarketing-qc-worker``. Paket ini TIDAK BOLEH
mengimpor apa pun dari ``api`` maupun ``worker`` — CI menegakkannya.
"""

__version__ = "1.0.0"
