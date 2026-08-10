"""Shared building blocks for the OCR + verification prompt modules.

The OCR endpoint is Mistral Document AI: it takes the PDF plus a strict JSON
``document_annotation_format`` (schema) and a ``document_annotation_prompt``, and
returns a single JSON object. We standardise every document type on the same
output shape — a ``verifications`` list with one row per field compared against
its reference ("acuan") value — so the dashboard can render a uniform table
(field | acuan | document | similarity | match | reason).
"""

# Per-row schema: one verified field compared against its reference value.
ITEM_PROPS = {
    "field": {"type": "string", "description": "Nama field yang diverifikasi"},
    "acuan": {
        "type": ["string", "null"],
        "description": "Nilai acuan dari data bank (disalin dari instruksi)",
    },
    "document": {
        "type": ["string", "null"],
        "description": "Nilai yang terbaca dari dokumen, apa adanya (null bila tidak terbaca)",
    },
    "similarity": {
        "type": "integer",
        "description": "Tingkat kemiripan acuan vs dokumen, skala 0-100",
    },
    "match": {
        "type": "boolean",
        "description": "true bila nilai dokumen dianggap cocok dengan acuan",
    },
    "reason": {
        "type": "string",
        "description": "Alasan singkat mengapa match bernilai true atau false",
    },
}
ITEM_REQUIRED = ["field", "acuan", "document", "similarity", "match", "reason"]

REQUIRED = ["verifications"]


def make_props() -> dict:
    """Top-level schema properties: a ``verifications`` array of comparison rows."""
    return {
        "verifications": {
            "type": "array",
            "description": "Satu baris per field yang diverifikasi.",
            "items": {
                "type": "object",
                "properties": ITEM_PROPS,
                "required": ITEM_REQUIRED,
                "additionalProperties": False,
            },
        }
    }


def make_schema(name: str) -> dict:
    """Build the Mistral ``document_annotation_format`` (strict JSON schema)."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "schema": {
                "type": "object",
                "properties": make_props(),
                "required": REQUIRED,
                "additionalProperties": False,
            },
            "strict": True,
        },
    }


def fmt_acuan(value) -> str:
    """Render a reference value for inclusion in the prompt text."""
    if value is None or str(value).strip() == "":
        return "(tidak tersedia)"
    return str(value).strip()
