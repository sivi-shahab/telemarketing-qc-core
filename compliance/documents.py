"""Document-type config for the Upload Document / OCR + verification feature.

Shared between the API (form field validation + labels) and the worker (resolving
the per-type prompt module). The API only touches ``DOCUMENT_TYPES`` /
``is_valid_doc_type`` (dependency-free); ``build_ocr_request`` is used by the
worker and lazily imports the prompt module for the given document type.

Each prompt module (``prompt/ocr_<type>.py``) defines ``PROMPT`` / ``PROPS`` /
``REQUIRED`` / ``SCHEMA`` plus ``build_prompt(reference)``, which injects the bank
reference ("acuan") values fetched from the CSVs.
"""
import importlib
import os
import sys

# Repo root: <repo>/compliance/documents.py -> <repo>. The prompt modules live in
# <repo>/prompt and are imported lazily (importlib) at task runtime; the celery
# worker's sys.path does not reliably include the repo root, so ensure it here.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Ordered: defines the order of slots in the upload modal and display.
DOCUMENT_TYPES: dict[str, dict] = {
    "ktp": {"label": "KTP", "prompt_module": "prompt.ocr_ktp"},
    "kk": {"label": "KK", "prompt_module": "prompt.ocr_kk"},
    "npwp": {"label": "NPWP", "prompt_module": "prompt.ocr_npwp"},
    "cover_buku_tabungan": {
        "label": "Cover Buku Tabungan",
        "prompt_module": "prompt.ocr_cover_buku_tabungan",
    },
}


def is_valid_doc_type(doc_type: str) -> bool:
    return doc_type in DOCUMENT_TYPES


def load_prompt_module(doc_type: str):
    """Import and return the prompt module for ``doc_type``."""
    if doc_type not in DOCUMENT_TYPES:
        raise KeyError(f"unknown document type: {doc_type}")
    return importlib.import_module(DOCUMENT_TYPES[doc_type]["prompt_module"])


def build_ocr_request(doc_type: str, reference: dict | None = None) -> tuple[str, dict]:
    """Build the Mistral OCR request for ``doc_type``.

    Returns ``(prompt, schema)`` where ``prompt`` is the per-type prompt with the
    reference ("acuan") values injected and ``schema`` is the strict JSON
    ``document_annotation_format``.
    """
    module = load_prompt_module(doc_type)
    return module.build_prompt(reference or {}), module.SCHEMA
