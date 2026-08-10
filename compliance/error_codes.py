"""Single source of truth for QA error codes.

Error codes come from distinct sources; this module groups them so the mapping is
easy to understand and is consumed by BOTH the dashboard (via the ``/result`` API,
which injects ``evaluation.error_code_table``) and the XLSX export.

Sources:
  - Scorecard            : items BELUM_SESUAI (derived B10/B12/B18) + LLM ``error_codes``
  - Card Holder Verif.   : per-field MISMATCH -> B17 (SKIPPED_NULL carries no error)
  - Cashline Data Verif. : per-field MISMATCH -> B02/B03/B05 risk-graded (SKIPPED_NULL none)
  - OCR document         : not yet assigned error codes (reserved for a future source)
"""

import re
from datetime import datetime

# --- Source groups ----------------------------------------------------------
SOURCE_SCORECARD = "scorecard"
SOURCE_CARD_HOLDER = "card_holder"
SOURCE_CASHLINE = "cashline_data"
# "others" is a QC-add-only source (see appeal_kind='add'): an error code that does
# not belong to any of the structured sources. It is display-only — it never has an
# evaluation item/field to attach to, so it does not change the score.
SOURCE_OTHERS = "others"

SOURCE_LABELS = {
    SOURCE_SCORECARD: "Scorecard",
    SOURCE_CARD_HOLDER: "Card Holder Verification",
    SOURCE_CASHLINE: "Cashline Data Verification",
    SOURCE_OTHERS: "Others",
}

# --- Catalog: code -> {desc (Indonesian), source, trigger (one-line note)} ---
# This is the authoritative description/source map. Sourced from the scorecard
# prompt's error-code catalog (example_final/Cashline/prompt_cashline_mus_v21.txt).
ERROR_CODES = {
    "B02": {
        "desc": "Salah input data — risiko rendah",
        "source": SOURCE_CASHLINE,
        "trigger": "Field cashline_data_verification MISMATCH/SKIPPED_NULL — risiko rendah",
        "risk_base": "L",
    },
    "B03": {
        "desc": "Salah input data — risiko menengah (data finansial)",
        "source": SOURCE_CASHLINE,
        "trigger": "Field cashline_data_verification MISMATCH/SKIPPED_NULL — risiko menengah (data finansial)",
        "risk_base": "M",
    },
    "B05": {
        "desc": "Salah input data — risiko tinggi (potensi kerugian finansial)",
        "source": SOURCE_CASHLINE,
        "trigger": "Field cashline_data_verification MISMATCH/SKIPPED_NULL — risiko tinggi",
        "risk_base": "H",
    },
    "B10": {
        "desc": "Fitur/skrip/biaya produk tidak akurat",
        "source": SOURCE_SCORECARD,
        "trigger": "Item BELUM_SESUAI di kategori Penjelasan / Final Konfirmasi Mega Cashline",
        "risk_base": "M",
    },
    "B11": {
        "desc": "Pelanggaran aturan produk",
        "source": SOURCE_SCORECARD,
        "trigger": "Pelanggaran aturan produk pada transkrip",
        "risk_base": "M",
    },
    "B12": {
        "desc": "Pelanggaran skrip standar pembukaan",
        "source": SOURCE_SCORECARD,
        "trigger": "Item BELUM_SESUAI di kategori Greeting (SC_CL_1/2/3)",
        "risk_base": "L",
    },
    "B13": {
        "desc": "Pengungkapan data verifikasi sebelum nasabah",
        "source": SOURCE_SCORECARD,
        "trigger": "Pengungkapan data verifikasi dinamis sebelum nasabah",
        "risk_base": "M",
    },
    "B15": {
        "desc": "Pengungkapan data verifikasi statik sebelum nasabah",
        "source": SOURCE_SCORECARD,
        "trigger": "Agen mengungkap data statik (SC_CL_23_1/23_2) sebelum nasabah",
        "risk_base": "H",
    },
    "B16": {
        "desc": "Verifikasi dinamis tidak memadai",
        "source": SOURCE_SCORECARD,
        "trigger": "SC_CL_23_1 & 23_2 SESUAI tetapi SC_CL_24 BELUM_SESUAI",
        "risk_base": "M",
    },
    "B17": {
        "desc": "Verifikasi statik/dinamis tidak ada atau tidak sesuai",
        "source": SOURCE_CARD_HOLDER,
        "trigger": "Field card_holder_verification MISMATCH/SKIPPED_NULL, atau SC_CL_23 BELUM_SESUAI",
        "risk_base": "H",
    },
    "B18": {
        "desc": "Tidak ada legal statement / pernyataan persetujuan",
        "source": SOURCE_SCORECARD,
        "trigger": "Item BELUM_SESUAI di kategori Legal Statement (SC_CL_37/38)",
        "risk_base": "H",
    },
    "B19": {
        "desc": "Janji di luar kewenangan",
        "source": SOURCE_SCORECARD,
        "trigger": "Janji di luar kewenangan pada transkrip",
        "risk_base": "M",
    },
    "B20": {
        "desc": "Penawaran tidak ditujukan kepada pemegang kartu utama",
        "source": SOURCE_SCORECARD,
        "trigger": "Penawaran tidak ditujukan kepada pemegang kartu utama",
        "risk_base": "H",
    },
    "B24": {
        "desc": "Nasabah membatalkan kartu suplemen namun proses tetap dilanjutkan",
        "source": SOURCE_SCORECARD,
        "trigger": "Pembatalan kartu suplemen tetapi proses tetap dilanjutkan",
        "risk_base": "L",
    },
    "B26": {
        "desc": "Nasabah mengajukan syarat/kondisi untuk menerima penawaran",
        "source": SOURCE_SCORECARD,
        "trigger": "Nasabah mengajukan syarat/kondisi untuk menerima penawaran",
        "risk_base": "M",
    },
}

# Flat code -> Indonesian description (kept for convenience / imports).
ERROR_DESC_ID = {code: meta["desc"] for code, meta in ERROR_CODES.items()}

# New-joiner rule: when a submission's agent joined < 18 days before submit_time,
# each Error Code whose Risk Base is L or M is softened to this value (H is kept).
NEW_JOINER_RISK_BASE = "N"


def override_risk_base_for_new_joiner(rows: list) -> list:
    """Return error-code rows with Risk Base ``L``/``M`` replaced by ``N`` (the
    new-joiner rule); rows with any other Risk Base (e.g. ``H``) are unchanged."""
    return [
        {**r, "risk_base": NEW_JOINER_RISK_BASE} if r.get("risk_base") in ("L", "M") else r
        for r in rows
    ]

# Codes whose authoritative, per-field source is a verification array rather than
# the LLM ``error_codes`` list. The LLM copy of these is skipped in the scorecard
# group (unless it explicitly references an SC_CL item) to avoid double-listing.
_VERIFICATION_CODES = {"B02", "B03", "B05", "B17"}

# Scorecard categories whose unmet (BELUM_SESUAI) items are surfaced as a derived
# error code, keyed to each item's own item_code.
CATEGORY_ERROR_CODES = [
    {"categories": ["Penjelasan Mega Cashline", "Final Konfirmasi Mega Cashline"], "code": "B10"},
    {"categories": ["Greeting"], "code": "B12"},
    {"categories": ["Legal Statement Mega Cashline", "Legal Statement Mega Ultima Shield"], "code": "B18"},
]

# Error codes currently surfaced in the Error Code table. To keep error_codes.py in
# sync with the KB/prompt, only this set is shown for now; every other code the LLM
# might emit (B11, B13, B15, B19, B20, B24, B26, ...) is HIDDEN, not deleted.
# Reversible: widen this set (or remove the filter in build_error_code_table) to
# restore a hidden code. Hidden codes carry no score deduction, so hiding them does
# not change any score or pass/fail outcome.
ALLOWED_ERROR_CODES = {"B02", "B03", "B05", "B10", "B12", "B16", "B17", "B18"}


def is_allowed_error_code(code: str) -> bool:
    """True if ``code`` should be surfaced in the Error Code table.

    Handles the cashline fallback ``"B02/B03/B05"`` by keeping the row if ANY of its
    slash-joined parts is allowed. Blank codes are kept (they carry no code to hide).
    """
    if not code:
        return True
    parts = [p.strip() for p in code.split("/") if p.strip()]
    return any(p in ALLOWED_ERROR_CODES for p in parts)

ITEM_CODE_RE = re.compile(r"SC_CL_\d+(?:_\d+)?")
_RUJUKAN_RE = re.compile(
    r"\s*Rujukan\s*:\s*SC_CL_\d+(?:_\d+)?(?:\s*,\s*SC_CL_\d+(?:_\d+)?)*\s*\.?",
    re.IGNORECASE,
)
_AGENT_RE = re.compile(r"^(\s*Agent\s+)(.*)$", re.IGNORECASE)


# --- Helpers ----------------------------------------------------------------
def category_error_code(category):
    """Return the derived error code for a scorecard category, or None."""
    for rule in CATEGORY_ERROR_CODES:
        if category in rule["categories"]:
            return rule["code"]
    return None


def clean_reason(reason) -> str:
    """Strip the trailing "Rujukan: SC_CL_XX" clause from a reason string."""
    if not reason:
        return ""
    return _RUJUKAN_RE.sub("", reason).strip()


# Parenthetical SC_CL references, e.g. "(SC_CL_2)" or "(SC_CL_2, SC_CL_3)".
_ITEM_CODE_PAREN_RE = re.compile(
    r"\s*\(\s*SC_CL_\d+(?:_\d+)?(?:\s*,\s*SC_CL_\d+(?:_\d+)?)*\s*\)"
)


def strip_item_codes(reason) -> str:
    """Remove SC_CL_XX references from a reason string for display in the Error
    Code table (the item code already has its own column). Strips parenthetical
    "(SC_CL_2)" groups and any bare SC_CL_X tokens, then tidies leftover
    separators/whitespace."""
    if not reason:
        return ""
    text = _ITEM_CODE_PAREN_RE.sub("", reason)
    text = ITEM_CODE_RE.sub("", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+([.,;:])", r"\1", text)
    return text.strip(" -\u2013\u2014,;:").strip()


def not_fulfilled_reason(item: dict) -> str:
    """Negate the "Agent ..." requirement and tag the item code, e.g.
    "Agent menyebutkan nama agent" (SC_CL_2) -> "Agent tidak menyebutkan nama agent (SC_CL_2)"."""
    item = item or {}
    req = item.get("requirement") or ""
    item_code = item.get("item_code")
    suffix = f" ({item_code})" if item_code else ""
    if not req:
        return f"Item scorecard belum terpenuhi{suffix}."
    m = _AGENT_RE.match(req)
    neg = f"{m.group(1)}tidak {m.group(2)}" if m else f"Belum terpenuhi: {req}"
    return f"{neg}{suffix}"


def error_code_sort_key(code) -> tuple:
    """Natural sort key for an error code like "B10" -> ("B", 10), so codes order
    ascending numerically (B02 < B05 < B10 < B12) regardless of digit width."""
    m = re.match(r"([A-Za-z]*)(\d*)", code or "")
    letters = m.group(1)
    num = int(m.group(2)) if m.group(2) else 0
    return (letters, num, code or "")


def code_for_cashline_field(v: dict, codes: list, used: set) -> str:
    """Resolve the data-input error code (B02/B03/B05) for a cashline field by
    matching its field name / reference / extracted value inside a code's reason.
    Each code is consumed once; falls back to a generic label."""
    needles = []
    for key in ("field", "reference_value", "extracted_value"):
        val = v.get(key)
        if val is not None and str(val).strip():
            needles.append(str(val).strip().lower())
    field = v.get("field")
    if field:
        needles.append(str(field).replace("_", " ").strip().lower())
    for i, c in enumerate(codes):
        if i in used:
            continue
        reason = ((c.get("trigger_source") or {}).get("reason") or "").lower()
        if any(n in reason for n in needles):
            used.add(i)
            return c.get("error_code") or "B02/B03/B05"
    return "B02/B03/B05"


def titleize_field(field) -> str:
    """Format a snake_case field name into Title Case, e.g.
    "nominal_pencairan" -> "Nominal Pencairan"."""
    if not field:
        return ""
    return str(field).replace("_", " ").strip().title()


def _verification_reason(v: dict) -> str:
    """Reason text for a verification-derived row: prefer the verification reason,
    otherwise build a short "<Field>: <MATCH>" note."""
    v = v or {}
    reason = v.get("reason")
    if reason:
        return str(reason)
    field = titleize_field(v.get("field"))
    match = v.get("match") or ""
    return f"{field}: {match}".strip(": ").strip()


def _evidence_text(evidence: dict) -> str:
    evidence = evidence or {}
    return f'{evidence.get("timestamp") or ""} {evidence.get("quote") or ""}'.strip()


def _evidence_timestamp(evidence: dict) -> str:
    """Extract just the timestamp portion of an evidence object (empty if none)."""
    return str((evidence or {}).get("timestamp") or "").strip()


def _evidence_quote(evidence: dict) -> str:
    """Extract just the quote (text) portion of an evidence object (empty if none)."""
    return str((evidence or {}).get("quote") or "").strip()


# QC submits evidence as ONE "<timestamp> <quote>" string (the Manual Check / Add
# modals concatenate the two inputs). The dashboard renders timestamp and quote as
# separate parts, so split it back. Like splitEvidence() in
# dashboard/src/components/ErrorCodeManualCheckModal.vue, but also accepting the
# formats this app actually emits: fractional seconds ("00:02.30") and "->" ranges
# ("00:00.00 -> 00:02.06"), optionally wrapped in [ ].
_TS = r"\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?"
_QC_EVIDENCE_TS_RE = re.compile(
    rf"^\[?\s*{_TS}(?:\s*(?:->|[-–])\s*{_TS})?\s*\]?"
)


def _split_qc_evidence(text) -> tuple:
    """Split a combined QC evidence string into ``(timestamp, quote)``.

    Returns ``("", text)`` when the string does not start with a timestamp."""
    s = str(text or "").strip()
    if not s:
        return "", ""
    m = _QC_EVIDENCE_TS_RE.match(s)
    if not m:
        return "", s
    ts = m.group(0).strip().strip("[]").strip()
    return ts, s[m.end():].strip()


def build_error_code_table(evaluation: dict) -> list:
    """Build the grouped Error Code table rows from an LLM ``evaluation`` object.

    Returns a list of dicts, ordered by source group, each shaped as:
    {sumber, error_code, item_code, details_error, reason, evidence, ticket_id}

    - Scorecard            : derived B10/B12/B18 + LLM error_codes (split per SC_CL)
    - Card Holder Verif.   : B17 per mismatched/skipped field
    - Cashline Data Verif. : B02/B03/B05 per mismatched/skipped field
    """
    evaluation = evaluation or {}
    rows = []
    seen = set()  # f"{code}::{item_code}" — prevents the same code+item appearing twice

    def add(source, code, item_code, reason, evidence, ticket_id, details=None,
            extra=None, timestamp="", evidence_quote=""):
        key = f"{code}::{item_code or ''}"
        if item_code and key in seen:
            return
        if item_code:
            seen.add(key)
        row = {
            "sumber": SOURCE_LABELS.get(source, source),
            "error_code": code or "",
            "risk_base": (ERROR_CODES.get(code) or {}).get("risk_base") or "",
            "item_code": item_code or "",
            "details_error": ERROR_DESC_ID.get(code) or details or "",
            "reason": strip_item_codes(reason),
            "evidence": evidence or "",
            # Split evidence so the QC "Manual Check" modal can prefill the
            # Timestamp and Evidence-text fields separately (see _evidence_*).
            "timestamp": timestamp or "",
            "evidence_quote": evidence_quote or "",
            "ticket_id": ticket_id or "",
        }
        if extra:
            row.update(extra)
        rows.append(row)

    # --- 1) Scorecard: LLM error_codes (non-verification) split per SC_CL ---
    for entry in evaluation.get("error_codes") or []:
        code = entry.get("error_code") or ""
        trigger = entry.get("trigger_source") or {}
        reason_raw = trigger.get("reason") or ""
        item_codes = list(dict.fromkeys(ITEM_CODE_RE.findall(reason_raw)))
        # Verification-sourced codes are represented per-field below; skip the LLM
        # copy unless it explicitly references a scorecard item (SC_CL_*).
        if code in _VERIFICATION_CODES and not item_codes:
            continue
        evidence = trigger.get("evidence") or {}
        ev_text = _evidence_text(evidence)
        ev_ts = _evidence_timestamp(evidence)
        ev_quote = _evidence_quote(evidence)
        ticket_id = evidence.get("ticket_id") or ""
        reason = clean_reason(reason_raw)
        details = entry.get("details_error")
        if item_codes:
            for ic in item_codes:
                add(SOURCE_SCORECARD, code, ic, reason, ev_text, ticket_id, details,
                    timestamp=ev_ts, evidence_quote=ev_quote)
        else:
            add(SOURCE_SCORECARD, code, None, reason, ev_text, ticket_id, details,
                timestamp=ev_ts, evidence_quote=ev_quote)

    # --- 1b) Scorecard: derived B10/B12/B18 from BELUM_SESUAI items ---
    for item in evaluation.get("scorecard_result") or []:
        if (item or {}).get("status") != "BELUM_SESUAI":
            continue
        code = category_error_code((item or {}).get("category"))
        if not code:
            continue
        evidence = item.get("evidence") or {}
        add(
            SOURCE_SCORECARD,
            code,
            item.get("item_code"),
            not_fulfilled_reason(item),
            _evidence_text(evidence),
            evidence.get("ticket_id") or "",
            timestamp=_evidence_timestamp(evidence),
            evidence_quote=_evidence_quote(evidence),
        )

    # --- 2) Card Holder Verification: B17 per mismatched/skipped field ---
    # Once the dynamic 2-match rule is met (>= 2 dynamic fields MATCH) the leftover
    # MISMATCH dynamic fields carry no penalty, so they are not surfaced as B17 errors.
    ch_two_match = card_holder_two_match_satisfied(evaluation.get("card_holder_verification"))
    for v in evaluation.get("card_holder_verification") or []:
        # SKIPPED_NULL fields carry no penalty and are no longer surfaced as errors —
        # only true MISMATCH rows become B17.
        if (v or {}).get("match") != "MISMATCH":
            continue
        if (
            ch_two_match
            and (v or {}).get("field") in CARD_HOLDER_DYNAMIC_FIELDS
            and (v or {}).get("match") == "MISMATCH"
        ):
            continue
        # Carry the reference/extracted/match so the QC "Manual Check" (banding)
        # modal can prefill them and snapshot the full AI row.
        add(
            SOURCE_CARD_HOLDER,
            "B17",
            titleize_field(v.get("field")),
            _verification_reason(v),
            "",
            "",
            extra={
                "reference_value": v.get("reference_value"),
                "extracted_value": v.get("extracted_value"),
                "match": v.get("match"),
            },
        )

    # --- 3) Cashline Data Verification: B02/B03/B05 per mismatched/skipped field ---
    cashline_codes = [
        c for c in (evaluation.get("error_codes") or []) if c.get("error_code") in ("B02", "B03", "B05")
    ]
    used: set = set()
    for v in evaluation.get("cashline_data_verification") or []:
        match = (v or {}).get("match")
        # SKIPPED_NULL fields carry no penalty and are no longer surfaced as errors —
        # only true MISMATCH rows become B02/B03/B05.
        if match != "MISMATCH":
            continue
        code = code_for_cashline_field(v, cashline_codes, used)
        # Carry reference/extracted/match so the QC "Manual Check" (banding) modal
        # can prefill them and snapshot the full AI row (same as B17 above).
        add(
            SOURCE_CASHLINE,
            code,
            titleize_field(v.get("field")),
            _verification_reason(v),
            "",
            "",
            extra={
                "reference_value": v.get("reference_value"),
                "extracted_value": v.get("extracted_value"),
                "match": v.get("match"),
            },
        )

    # Hide error codes outside ALLOWED_ERROR_CODES (kept in sync with KB/prompt).
    # Reversible: this only drops rows from the surfaced table; nothing is deleted.
    rows = [r for r in rows if is_allowed_error_code(r.get("error_code"))]

    # Sort error codes ascending within each source group (B10, B12, ...),
    # preserving the group order in which sources first appear.
    group_order = {}
    for r in rows:
        group_order.setdefault(r["sumber"], len(group_order))
    rows.sort(key=lambda r: (group_order[r["sumber"]], error_code_sort_key(r["error_code"])))

    return rows


def _appeal_attr(appeal, name):
    """Read a field from an appeal that may be an ORM object or a plain dict."""
    if isinstance(appeal, dict):
        return appeal.get(name)
    return getattr(appeal, name, None)


def effective_appeal_status(appeal) -> str:
    """The FINAL status of a banding/AI-status request under the tiered flow
    (QC -> Team Leader QC -> [SPQ Head]). Returns 'approved' | 'rejected' | 'pending'.

    Team Leader QC may FINALIZE a request directly (approve/reject, no SPQ Head), or
    ESCALATE it to SPQ Head who then decides:
      - TL QC approved (final)                    -> 'approved'
      - TL QC rejected (final)                    -> 'rejected'
      - TL QC escalated + SPQ Head approved       -> 'approved'
      - TL QC escalated + SPQ Head rejected       -> 'rejected'
      - awaiting TL QC, or escalated awaiting SPQ -> 'pending'
    """
    tl = _appeal_attr(appeal, "tl_qc_status") or "pending"
    if tl == "approved":
        return "approved"
    if tl == "rejected":
        return "rejected"
    if tl == "escalated":
        appr = _appeal_attr(appeal, "approval_status") or "pending"
        return appr if appr in ("approved", "rejected") else "pending"
    return "pending"


# --- Banding kind (remove vs change) ---------------------------------------
# Error codes whose deduction is real (comes from the scorecard item weight /
# verification field penalty). A 'change' banding that relabels a row TO one of
# these keeps the row's existing deduction; relabelling to any other code zeroes it.
DEDUCTION_BEARING_CODES = {"B02", "B03", "B05", "B10", "B16", "B17"}

_ERROR_REASON_BY_CODE = None


def _reason_meta(code):
    """Catalog entry (risk_base/details/…) for an error code, or None."""
    global _ERROR_REASON_BY_CODE
    if _ERROR_REASON_BY_CODE is None:
        try:
            from compliance.error_reasons import ERROR_REASONS
            _ERROR_REASON_BY_CODE = {e.get("code"): e for e in ERROR_REASONS}
        except Exception:
            _ERROR_REASON_BY_CODE = {}
    return _ERROR_REASON_BY_CODE.get((code or "").strip().upper())


def _appeal_kind(appeal) -> str:
    return (_appeal_attr(appeal, "appeal_kind") or "remove")


def _appeal_new_code(appeal) -> str:
    return (_appeal_attr(appeal, "qc_new_error_code") or "").strip().upper()


def is_deduction_bearing(code) -> bool:
    return (code or "").strip().upper() in DEDUCTION_BEARING_CODES


def appeals_that_flip(approved_appeals: list) -> list:
    """Subset of approved appeals whose SCORE effect is to REMOVE the deduction
    (flip the scorecard item / verification field): every 'remove' banding, plus
    'change' bandings whose NEW code is NOT deduction-bearing. A 'change' to a
    deduction-bearing code keeps its deduction (relabel only), so it is excluded."""
    out = []
    for a in approved_appeals or []:
        if _appeal_kind(a) == "change" and is_deduction_bearing(_appeal_new_code(a)):
            continue  # relabel only — keep the deduction, do not flip
        out.append(a)
    return out


def _qc_overwrite(appeal) -> dict:
    """QC-submitted values that overwrite the AI row when a 'change' banding is
    approved: evidence / reason / ticket id, plus verification reference & extracted
    values. Empty submissions are skipped so the AI value is kept."""
    out = {}
    for src, dst in (
        ("qc_reason", "reason"),
        ("qc_evidence", "evidence"),
        ("qc_ticket_id", "ticket_id"),
        ("qc_reference_value", "reference_value"),
        ("qc_extracted_value", "extracted_value"),
    ):
        v = _appeal_attr(appeal, src)
        if v is not None and str(v).strip() != "":
            out[dst] = v
    return out


def relabel_error_table(table: list, approved_appeals: list) -> list:
    """Post-process the built + annotated Error Code table for approved bandings.

    - 'remove' banding  -> drop the matching row (scorecard/verification rows are
      already gone via the flip; this also hides free-floating codes with no hook).
    - 'change' banding   -> relabel the row's error_code (+ risk_base/details from
      the master catalog). If the row was flipped away ('change' -> non-deduction
      code), inject a relabeled row from the appeal's AI snapshot so the error still
      shows with the new code.

    Keyed by ``(error_code, item_code)``. MUST run AFTER ``_annotate_appeals`` so
    each row keeps the appeal metadata attached under its ORIGINAL code."""
    if not approved_appeals:
        return table
    changes, removes = {}, set()
    for a in approved_appeals:
        key = (_appeal_attr(a, "error_code"), _appeal_attr(a, "item_code") or "")
        if _appeal_kind(a) == "change":
            changes[key] = a
        else:
            removes.add(key)

    out, handled = [], set()
    for row in table:
        key = (row.get("error_code"), row.get("item_code") or "")
        if key in removes:
            continue
        a = changes.get(key)
        if a is not None:
            new_code = _appeal_new_code(a)
            meta = _reason_meta(new_code) or {}
            row = {
                **row,
                "error_code": new_code,
                # QC-edited override wins over the master-catalog default.
                "risk_base": _appeal_attr(a, "qc_risk_base") or meta.get("risk_base") or row.get("risk_base") or "",
                "details_error": meta.get("details") or row.get("details_error") or "",
                # Approved QC evidence/reason/ticket overwrite the AI values.
                **_qc_overwrite(a),
            }
            handled.add(key)
        out.append(row)

    # 'change' -> non-deduction code: the original row was flipped away, so inject
    # a relabeled row from the appeal snapshot to keep the error visible.
    for key, a in changes.items():
        if key in handled:
            continue
        new_code = _appeal_new_code(a)
        meta = _reason_meta(new_code) or {}
        base = {
            "sumber": _appeal_attr(a, "ai_sumber") or "",
            "error_code": new_code,
            "risk_base": _appeal_attr(a, "qc_risk_base") or meta.get("risk_base") or _appeal_attr(a, "ai_risk_base") or "",
            "item_code": _appeal_attr(a, "item_code") or "",
            "details_error": meta.get("details") or _appeal_attr(a, "ai_details_error") or "",
            "reason": _appeal_attr(a, "ai_reason") or "",
            "evidence": _appeal_attr(a, "ai_evidence") or "",
            "timestamp": "",
            "evidence_quote": "",
            "ticket_id": _appeal_attr(a, "ai_ticket_id") or "",
            "appealable": True,
            "appeal": None,
        }
        # Approved QC evidence/reason/ticket overwrite the AI snapshot values.
        out.append({**base, **_qc_overwrite(a)})
    return out


def apply_approved_appeals(evaluation: dict, approved_appeals: list) -> dict:
    """Return a copy of ``evaluation`` with approved Error Code appeals applied.

    For each approved appeal (keyed by scorecard ``item_code``), the matching
    ``scorecard_result`` item is flipped ``BELUM_SESUAI`` -> ``SESUAI`` and its
    evidence/ticket_id replaced with the values submitted by QC. Because the
    Error Code table, AI score and scorecard/ringkasan are all derived from
    ``scorecard_result``, this single change removes the appealed error row and
    lifts the score consistently everywhere. Non-destructive: the input
    ``evaluation`` is not mutated (approvals stay reversible)."""
    if not evaluation or not approved_appeals:
        return evaluation
    # item_code -> latest approved appeal for it
    by_item = {}
    for a in approved_appeals:
        item_code = _appeal_attr(a, "item_code")
        if item_code:
            by_item[item_code] = a
    if not by_item:
        return evaluation

    new_items = []
    changed = False
    for item in evaluation.get("scorecard_result") or []:
        appeal = by_item.get((item or {}).get("item_code"))
        if appeal is None or (item or {}).get("status") != "BELUM_SESUAI":
            new_items.append(item)
            continue
        updated = {**item, "status": "SESUAI"}
        # An approved item earns its full weight — the Scorecard "Skor" column must
        # reflect the weight, not stay at 0 (the failed score).
        if item.get("weight") is not None:
            updated["item_score"] = item.get("weight")
        evidence = dict(item.get("evidence") or {})
        qc_evidence = _appeal_attr(appeal, "qc_evidence")
        qc_ticket_id = _appeal_attr(appeal, "qc_ticket_id")
        if qc_evidence is not None:
            evidence["quote"] = qc_evidence
        if qc_ticket_id is not None:
            evidence["ticket_id"] = qc_ticket_id
        updated["evidence"] = evidence
        new_items.append(updated)
        changed = True

    if not changed:
        return evaluation
    return {**evaluation, "scorecard_result": new_items}


def _latest_per_key(appeals: list) -> list:
    """Latest appeal per ``(error_code, item_code)`` — later submissions supersede."""
    latest = {}
    for a in appeals or []:
        key = (_appeal_attr(a, "error_code"), _appeal_attr(a, "item_code"))
        latest[key] = a
    return list(latest.values())


def approved_appeals_only(appeals: list) -> list:
    """Filter a list of appeals down to those whose current status is approved.

    An error code may be appealed repeatedly; only the latest appeal per
    ``(error_code, item_code)`` is authoritative, so an older approved row that
    was superseded by a newer pending/rejected one is ignored."""
    return [a for a in _latest_per_key(appeals) if effective_appeal_status(a) == "approved"]


def added_appeals_only(appeals: list) -> list:
    """Approved ``add`` bandings (latest per key). These attach a NEW error to an
    evaluation item/field and lower the score (except source ``others``)."""
    return [
        a for a in _latest_per_key(appeals)
        if _appeal_kind(a) == "add" and effective_appeal_status(a) == "approved"
    ]


def added_appeals_visible(appeals: list) -> list:
    """``add`` bandings that should render a row: pending (awaiting review), approved
    (applied), OR rejected. A rejected add stays visible (shown as ``rejected``)
    instead of vanishing — the QC keeps a record of the denied proposal and removes it
    later via a separate deletion request (a ``remove`` banding). It is display-only:
    the score uses ``added_appeals_only`` (approved), so a rejected add never deducts."""
    return [
        a for a in _latest_per_key(appeals)
        if _appeal_kind(a) == "add" and effective_appeal_status(a) in ("pending", "approved", "rejected")
    ]


# Card Holder DYNAMIC verification (alamat kantor/rumah, telepon, email). Per KB_CL_24
# only 2 matches are required (min_verification_required = 2); each shortfall from the
# required 2 costs 7.5 (max deduction 15). Once >= 2 dynamic fields MATCH, the remaining
# MISMATCH dynamic fields add no further deduction.
#
# This MUST stay identical to the "address_group_score" rule in the campaign prompt
# (prompt_cashline_mus_v30.txt onwards) — the appeals recompute below works on the
# *delta* of this function, so any divergence produces a wrong appeal adjustment.
# SKIPPED_NULL (empty reference data) is NOT a violation and is never penalised: a
# group with zero MISMATCH scores 0 regardless of how few fields matched.
# The 9 DYNAMIC card-holder verification fields, aligned to KB_CL_24 VD_1..VD_9.
# A param counts toward the min-2 rule via a value MATCH (fields with reference data)
# OR a valid ask+answer event (event_verified, for reference-less params) — see
# card_holder_two_match_satisfied.
CARD_HOLDER_DYNAMIC_FIELDS = (
    "alamat_pengiriman_tagihan", "alamat_rumah", "no_telpon_terdaftar",
    "alamat_kantor", "no_telpon_kantor", "alamat_email_terdaftar",
    "nama_kartu_suplement", "jumlah_kartu_suplement", "nama_keluarga_relasi",
)
CARD_HOLDER_DYNAMIC_REQUIRED = 2
CARD_HOLDER_DYNAMIC_PENALTY = 7.5  # per shortfall from the required 2

# Per-field MISMATCH penalties, mirroring the campaign prompt
# (campaign_cashline/prompt_cashline_mus_v30.txt:1398-1421). Used ONLY by the QC
# "add error code" flow to deduct the right amount when flipping a currently-MATCH
# verification field to MISMATCH. The LLM otherwise sets these item_scores itself.
CASHLINE_FIELD_PENALTY = {
    "nominal_pencairan": 1, "tenor_dalam_bulan": 1, "nominal_cicilan_per_bulan": 1, "bunga": 1,
    "nama_bank": 2, "penalti_pelunasan_dipercepat": 2, "nomor_rekening": 2,
    "provisi": 4, "biaya_admin": 5,
}
# Card-holder verification no longer deducts from ai_score_verification. A static
# MISMATCH is expressed via the scorecard item (SC_CL_23_1/SC_CL_23_2) and a dynamic
# <2-match via SC_CL_24 — see _propagate_verification_to_scorecard. Penalties are 0 to
# avoid double-counting the same failure (v33 onwards).
CARD_HOLDER_STATIC_PENALTY = {
    "tanggal_lahir": 0, "nama_ibu_kandung": 0,
}
# Card Holder STATIC field -> the scorecard item it forces to BELUM_SESUAI on MISMATCH
# (VERIFICATION -> SCORECARD PROPAGATION in the campaign prompt). SC_CL_23_1 = tanggal
# lahir, SC_CL_23_2 = nama ibu kandung. The dynamic group maps to SC_CL_24 (2-match rule).
CARD_HOLDER_STATIC_SCORECARD = {
    "tanggal_lahir": "SC_CL_23_1",
    "nama_ibu_kandung": "SC_CL_23_2",
}
CARD_HOLDER_DYNAMIC_SCORECARD = "SC_CL_24"


def _card_holder_address_group_score(items) -> float:
    """Dynamic card-holder fields no longer deduct from ai_score_verification (v33).

    A shortfall of the KB_CL_24 2-match rule is now expressed as SC_CL_24 BELUM_SESUAI
    in the scorecard (see _propagate_verification_to_scorecard), which lowers
    ai_score_phase_2 instead. Always returns 0.0 so the same failure is not counted
    twice. Kept as a function so the appeal appliers' group_score_fn hook still works."""
    return 0.0


def _propagate_verification_to_scorecard(evaluation: dict) -> dict:
    """Force the scorecard verification items to BELUM_SESUAI based on the (possibly
    appeal-adjusted) card_holder_verification match state — the Python mirror of the
    prompt's VERIFICATION -> SCORECARD PROPAGATION rule:

    - static field ``tanggal_lahir``/``nama_ibu_kandung`` MISMATCH -> SC_CL_23_1/SC_CL_23_2.
    - fewer than 2 of the 9 dynamic params VERIFIED (value MATCH or event_verified) ->
      SC_CL_24 (hybrid KB_CL_24 2-match rule, see card_holder_two_match_satisfied).

    Only ever forces BELUM_SESUAI (item_score 0); a MATCH / >=2-match never restores a
    SESUAI (to re-pass, QC appeals the scorecard item directly). Non-destructive; does not
    itself recompute ai_score_phase_2 (callers re-derive the score from scorecard_result)."""
    if not evaluation:
        return evaluation
    ch = evaluation.get("card_holder_verification") or []
    if not ch:
        return evaluation
    ch_match = {(v or {}).get("field"): (v or {}).get("match") for v in ch}
    force_belum = set()
    for field, code in CARD_HOLDER_STATIC_SCORECARD.items():
        if ch_match.get(field) == "MISMATCH":
            force_belum.add(code)
    if not card_holder_two_match_satisfied(ch):
        force_belum.add(CARD_HOLDER_DYNAMIC_SCORECARD)
    if not force_belum:
        return evaluation
    new_items = []
    changed = False
    for it in evaluation.get("scorecard_result") or []:
        if (it or {}).get("item_code") in force_belum and (it or {}).get("status") != "BELUM_SESUAI":
            new_items.append({**it, "status": "BELUM_SESUAI", "item_score": 0})
            changed = True
        else:
            new_items.append(it)
    return {**evaluation, "scorecard_result": new_items} if changed else evaluation


def card_holder_two_match_satisfied(items) -> bool:
    """HYBRID KB_CL_24 min_verification_required=2 gate over the 9 dynamic card-holder
    fields (VD_1..VD_9). A param counts as VERIFIED when EITHER its value matches the
    reference (``match == "MATCH"``) OR — for reference-less params (no ascend column
    yet) — a valid ask+answer event occurred (``event_verified is True``). True when
    >= 2 params are verified. Callers use this to (a) hide penalty-free leftover
    MISMATCH rows once the rule is met and (b) drive SC_CL_24 status via
    ``_propagate_verification_to_scorecard``."""
    dyn = [
        v or {} for v in (items or [])
        if (v or {}).get("field") in CARD_HOLDER_DYNAMIC_FIELDS
    ]
    verified = sum(
        1 for v in dyn
        if v.get("match") == "MATCH" or v.get("event_verified") is True
    )
    return verified >= CARD_HOLDER_DYNAMIC_REQUIRED


def _apply_verification_appeals(
    evaluation: dict,
    approved_appeals: list,
    eval_key: str,
    code_match,
    group_fields: tuple = (),
    group_score_fn=None,
) -> dict:
    """Shared applier for data-verification banding (Card Holder / Cashline).

    For each approved appeal whose ``error_code`` satisfies ``code_match`` (keyed by
    the titleized field == ``item_code``), the matching ``evaluation[eval_key]`` item
    whose ``match`` is ``MISMATCH``/``SKIPPED_NULL`` is flipped to ``MATCH`` with
    ``item_score`` reset to 0 and its ``reference_value``/``extracted_value``
    replaced by the QC-submitted ones. The removed per-field deduction is added
    back to ``ai_score_verification`` (the single frozen verification-score field
    shared by both sources) so the score lifts consistently across the detail
    view, the Results list and the XLSX export. Non-destructive.

    Fields named in ``group_fields`` are excluded from the per-field delta; instead
    ``group_score_fn(items)`` is evaluated on the pre- and post-flip item lists and
    their difference is applied (used for dynamic card-holder verification, which is
    scored as a group of 4 with a min-2-match rule rather than field-by-field)."""
    if not evaluation or not approved_appeals:
        return evaluation
    # titleized field (item_code) -> latest approved appeal for it (this source only)
    by_field = {}
    for a in approved_appeals:
        if not code_match((_appeal_attr(a, "error_code") or "").strip().upper()):
            continue
        item_code = _appeal_attr(a, "item_code")
        if item_code:
            by_field[item_code] = a
    if not by_field:
        return evaluation

    old_items = evaluation.get(eval_key) or []
    new_items = []
    delta = 0.0
    changed = False
    for v in old_items:
        appeal = by_field.get(titleize_field((v or {}).get("field")))
        if appeal is None or (v or {}).get("match") not in ("MISMATCH", "SKIPPED_NULL"):
            new_items.append(v)
            continue
        try:
            old_score = float(v.get("item_score"))
        except (TypeError, ValueError):
            old_score = 0.0
        # Fields scored as a group (e.g. dynamic card-holder verification) are settled
        # by ``group_score_fn`` below, NOT by their per-field item_score — skip them here.
        if old_score < 0 and (v or {}).get("field") not in group_fields:
            delta += -old_score  # add the removed deduction back to the score
        updated = {**v, "match": "MATCH", "item_score": 0, "similarity_percent": 100}
        ref = _appeal_attr(appeal, "qc_reference_value")
        ext = _appeal_attr(appeal, "qc_extracted_value")
        qc_reason = _appeal_attr(appeal, "qc_reason")
        if ref is not None:
            updated["reference_value"] = ref
        if ext is not None:
            updated["extracted_value"] = ext
        if qc_reason:
            updated["reason"] = qc_reason
        new_items.append(updated)
        changed = True

    if not changed:
        return evaluation
    # Group-scored fields: recompute the group total before vs after the flips and add
    # the difference (a flip only lifts the score when it raises matched_count to the
    # required minimum; extra matches beyond the minimum add nothing).
    if group_score_fn is not None:
        delta += group_score_fn(new_items) - group_score_fn(old_items)
    result = {**evaluation, eval_key: new_items}
    verif = evaluation.get("ai_score_verification")
    if delta and verif is not None:
        try:
            val = float(verif) + delta
            result["ai_score_verification"] = int(val) if val == int(val) else val
        except (TypeError, ValueError):
            pass
    return result


def is_cashline_code(error_code: str) -> bool:
    """A row/appeal belongs to Cashline Data Verification if its error code is
    B02/B03/B05 — or the generic ``"B02/B03/B05"`` fallback emitted when a field
    can't be matched to a specific code (``code_for_cashline_field``)."""
    ec = (error_code or "").strip().upper()
    return any(x in ec for x in ("B02", "B03", "B05"))


def apply_approved_card_holder_appeals(evaluation: dict, approved_appeals: list) -> dict:
    """Apply approved Card Holder Verification (B17) banding to ``evaluation``."""
    return _apply_verification_appeals(
        evaluation, approved_appeals, "card_holder_verification", lambda ec: ec == "B17",
        group_fields=CARD_HOLDER_DYNAMIC_FIELDS,
        group_score_fn=_card_holder_address_group_score,
    )


def apply_approved_cashline_appeals(evaluation: dict, approved_appeals: list) -> dict:
    """Apply approved Cashline Data Verification (B02/B03/B05) banding to ``evaluation``."""
    return _apply_verification_appeals(
        evaluation, approved_appeals, "cashline_data_verification", is_cashline_code
    )


def apply_approved_critical_compliance_appeals(evaluation: dict, approved_appeals: list) -> dict:
    """Return a copy of ``evaluation`` with approved appeals applied to the
    Critical Compliance Check.

    All four critical items (``SC_CL_4``/``SC_CL_23_1``/``SC_CL_23_2``/``SC_CL_37``) are
    ordinary scorecard rows, so the SAME approved scorecard appeal that flips a scorecard
    item to SESUAI also resolves its critical check (matched by ``item_code``). Card-holder
    static failures now live on ``SC_CL_23_1``/``SC_CL_23_2`` (via VERIFICATION -> SCORECARD
    PROPAGATION); to re-pass one, QC appeals that scorecard item directly (an approved B17
    does not auto-restore it). A still-``FAIL`` resolved entry becomes ``PASS``; overall
    ``status`` is ``PASS`` only when all pass.

    ``ai_score_critical_compliance_check`` is a frozen additive penalty
    (``-(maximum_score/4)`` per FAILing item). Each flipped item returns exactly
    one slice, computed from the frozen value to avoid ``maximum_score`` ambiguity:
    ``new = frozen * remaining_fail / orig_fail``. Non-destructive."""
    if not evaluation or not approved_appeals:
        return evaluation
    ccc = evaluation.get("critical_compliance_check")
    if not isinstance(ccc, dict):
        return evaluation
    items = ccc.get("checked_items")
    if not items:
        return evaluation

    approved_codes = {
        _appeal_attr(a, "item_code")
        for a in approved_appeals
        if _appeal_attr(a, "item_code")
    }
    # All four critical items are ordinary scorecard rows (SC_CL_4/23_1/23_2/37), so an
    # approved scorecard appeal on that item_code resolves its critical slice. (Card-holder
    # static failures now live on SC_CL_23_1/23_2 via propagation; to re-pass one, QC appeals
    # that scorecard item directly — an approved B17 does NOT auto-restore it.)
    orig_fail = sum(1 for it in items if (it or {}).get("status") == "FAIL")
    if orig_fail == 0:
        return evaluation

    new_items = []
    flipped = 0
    for it in items:
        code = (it or {}).get("item_code")
        resolved = code in approved_codes
        if (it or {}).get("status") == "FAIL" and resolved:
            new_items.append({**it, "status": "PASS"})
            flipped += 1
        else:
            new_items.append(it)
    if flipped == 0:
        return evaluation

    new_status = "PASS" if all((it or {}).get("status") == "PASS" for it in new_items) else "FAIL"
    result = {
        **evaluation,
        "critical_compliance_check": {**ccc, "status": new_status, "checked_items": new_items},
    }
    frozen = evaluation.get("ai_score_critical_compliance_check")
    if frozen is not None:
        try:
            val = float(frozen) * (orig_fail - flipped) / orig_fail
            result["ai_score_critical_compliance_check"] = int(val) if val == int(val) else val
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    return result

# ---------------------------------------------------------------------------
# QC "add error code" bandings — the INVERSE of the remove/verification appliers
# above. An approved add attaches a NEW error to an existing evaluation item/field
# and LOWERS the score. Source 'others' has no hook and is display-only (handled by
# inject_added_rows, not here). Applied non-destructively at read time.
# ---------------------------------------------------------------------------
def _newest_appeal(appeals: list):
    """The most recently submitted appeal (by ``requested_at``, then ``id``)."""
    def key(a):
        return (_appeal_attr(a, "requested_at") or datetime.min, _appeal_attr(a, "id") or 0)
    return max(appeals, key=key)


def apply_added_scorecard_appeals(evaluation: dict, added_appeals: list) -> dict:
    """Flip the targeted scorecard item ``SESUAI`` -> ``BELUM_SESUAI`` for each
    approved scorecard ``add`` banding (keyed by ``item_code``), so its weight is
    deducted from the scorecard score.

    The item's ``reason`` / ``evidence`` / ticket are replaced with what the QC
    submitted on the NEWEST approved add for that item — the AI values describe why
    the item PASSED, which is misleading once the row is an error. Non-destructive."""
    if not evaluation or not added_appeals:
        return evaluation
    # item_code -> every approved scorecard add targeting it (an item may be added
    # more than once with different codes); the newest submission wins.
    by_item: dict = {}
    for a in added_appeals:
        if _appeal_attr(a, "add_source") != SOURCE_SCORECARD:
            continue
        item_code = _appeal_attr(a, "item_code")
        if item_code:
            by_item.setdefault(item_code, []).append(a)
    if not by_item:
        return evaluation

    new_items = []
    changed = False
    for item in evaluation.get("scorecard_result") or []:
        candidates = by_item.get((item or {}).get("item_code"))
        if not candidates or (item or {}).get("status") != "SESUAI":
            new_items.append(item)
            continue
        appeal = _newest_appeal(candidates)
        updated = {**item, "status": "BELUM_SESUAI", "item_score": 0}
        qc_reason = _appeal_attr(appeal, "qc_reason")
        if qc_reason:
            updated["reason"] = qc_reason
        ts, quote = _split_qc_evidence(_appeal_attr(appeal, "qc_evidence"))
        updated["evidence"] = {
            "timestamp": ts,
            "quote": quote,
            "ticket_id": _appeal_attr(appeal, "qc_ticket_id") or "",
        }
        new_items.append(updated)
        changed = True
    if not changed:
        return evaluation
    return {**evaluation, "scorecard_result": new_items}


def _apply_added_verification_appeals(
    evaluation: dict,
    added_appeals: list,
    source: str,
    eval_key: str,
    penalty_map: dict,
    group_fields: tuple = (),
    group_score_fn=None,
) -> dict:
    """Flip a currently-``MATCH`` verification field to ``MISMATCH`` for each approved
    ``add`` banding of ``source`` (keyed by titleized field == ``item_code``), applying
    the per-field penalty (``penalty_map``) to ``ai_score_verification`` and filling
    reference/extracted from the QC submission. Group-scored fields (dynamic card
    holder) settle via ``group_score_fn`` delta instead of a fixed per-field penalty.
    The mirror image of ``_apply_verification_appeals``. Non-destructive."""
    if not evaluation or not added_appeals:
        return evaluation
    by_field = {}
    for a in added_appeals:
        if _appeal_attr(a, "add_source") != source:
            continue
        item_code = _appeal_attr(a, "item_code")
        if item_code:
            by_field[item_code] = a
    if not by_field:
        return evaluation

    old_items = evaluation.get(eval_key) or []
    new_items = []
    delta = 0.0
    changed = False
    for v in old_items:
        appeal = by_field.get(titleize_field((v or {}).get("field")))
        if appeal is None or (v or {}).get("match") != "MATCH":
            new_items.append(v)
            continue
        field = (v or {}).get("field")
        if field in group_fields:
            # Dynamic card-holder fields no longer carry a per-field deduction; the
            # failure is expressed via SC_CL_24 BELUM_SESUAI in the scorecard.
            item_score = 0
        else:
            penalty = penalty_map.get(field, 0)
            item_score = -penalty
            delta += -penalty
        updated = {**v, "match": "MISMATCH", "item_score": item_score, "similarity_percent": 0}
        ref = _appeal_attr(appeal, "qc_reference_value")
        ext = _appeal_attr(appeal, "qc_extracted_value")
        qc_reason = _appeal_attr(appeal, "qc_reason")
        if ref is not None:
            updated["reference_value"] = ref
        if ext is not None:
            updated["extracted_value"] = ext
        if qc_reason:
            updated["reason"] = qc_reason
        new_items.append(updated)
        changed = True

    if not changed:
        return evaluation
    if group_score_fn is not None:
        delta += group_score_fn(new_items) - group_score_fn(old_items)
    result = {**evaluation, eval_key: new_items}
    verif = evaluation.get("ai_score_verification")
    if delta and verif is not None:
        try:
            val = float(verif) + delta  # delta is negative — the score drops
            result["ai_score_verification"] = int(val) if val == int(val) else val
        except (TypeError, ValueError):
            pass
    return result


def apply_added_score_appeals(evaluation: dict, added_appeals: list) -> dict:
    """Apply ALL score-affecting ``add`` bandings (scorecard + both verifications +
    critical) in one call. ``others`` adds carry no score effect (display only). Use
    this in every read-time assembly path (detail view, Results list, XLSX, aggregates)
    so the score/AI-status stays consistent everywhere."""
    if not evaluation or not added_appeals:
        return evaluation
    evaluation = apply_added_scorecard_appeals(evaluation, added_appeals)
    evaluation = apply_added_card_holder_appeals(evaluation, added_appeals)
    evaluation = apply_added_cashline_appeals(evaluation, added_appeals)
    # A card-holder add flips a static/dynamic field to MISMATCH; propagate that into the
    # scorecard (SC_CL_23_1/23_2/SC_CL_24) BEFORE the critical applier so the critical
    # entry for a now-BELUM_SESUAI SC_CL_23_x flips to FAIL consistently.
    evaluation = _propagate_verification_to_scorecard(evaluation)
    evaluation = apply_added_critical_compliance_appeals(evaluation, added_appeals)
    return evaluation


def apply_added_cashline_appeals(evaluation: dict, added_appeals: list) -> dict:
    """Apply approved Cashline Data Verification ``add`` bandings."""
    return _apply_added_verification_appeals(
        evaluation, added_appeals, SOURCE_CASHLINE, "cashline_data_verification",
        CASHLINE_FIELD_PENALTY,
    )


def apply_added_card_holder_appeals(evaluation: dict, added_appeals: list) -> dict:
    """Apply approved Card Holder Verification ``add`` bandings (dynamic fields tunduk
    the 2-match group rule)."""
    return _apply_added_verification_appeals(
        evaluation, added_appeals, SOURCE_CARD_HOLDER, "card_holder_verification",
        CARD_HOLDER_STATIC_PENALTY,
        group_fields=CARD_HOLDER_DYNAMIC_FIELDS,
        group_score_fn=_card_holder_address_group_score,
    )


CRITICAL_ITEM_CODES = ("SC_CL_4", "SC_CL_23_1", "SC_CL_23_2", "SC_CL_37")


def apply_added_critical_compliance_appeals(evaluation: dict, added_appeals: list) -> dict:
    """When a scorecard ``add`` targets a critical item, flip its
    ``critical_compliance_check`` entry ``PASS`` -> ``FAIL`` and add one frozen slice
    (``-(maximum_score/4)``) back to ``ai_score_critical_compliance_check`` — the
    inverse of ``apply_added_scorecard_appeals``'s counterpart. Non-destructive.

    Also handles card-holder adds: an added card-holder banding flips a static field
    ``MATCH`` -> ``MISMATCH`` (via ``apply_added_card_holder_appeals``), then
    ``_propagate_verification_to_scorecard`` forces the matching ``SC_CL_23_1``/``SC_CL_23_2``
    to ``BELUM_SESUAI`` (both run before this in ``apply_added_score_appeals``). That critical
    scorecard item is picked up here via ``belum_critical`` and flips ``PASS`` -> ``FAIL``,
    gaining a frozen slice — so a QC-added static mismatch triggers the score bomb just like
    an LLM-detected one."""
    if not evaluation or not added_appeals:
        return evaluation
    ccc = evaluation.get("critical_compliance_check")
    if not isinstance(ccc, dict):
        return evaluation
    items = ccc.get("checked_items")
    if not items:
        return evaluation
    added_codes = {
        _appeal_attr(a, "item_code")
        for a in added_appeals
        if _appeal_attr(a, "add_source") == SOURCE_SCORECARD and _appeal_attr(a, "item_code")
    }
    # Critical scorecard items (SC_CL_23_1/23_2) forced BELUM_SESUAI by an added card-holder
    # static banding — via _propagate_verification_to_scorecard, which runs before this in
    # apply_added_score_appeals. Their critical entry must flip PASS -> FAIL too.
    belum_critical = {
        (it or {}).get("item_code")
        for it in (evaluation.get("scorecard_result") or [])
        if (it or {}).get("status") == "BELUM_SESUAI"
        and (it or {}).get("item_code") in CRITICAL_ITEM_CODES
    }
    if not added_codes and not belum_critical:
        return evaluation

    orig_fail = sum(1 for it in items if (it or {}).get("status") == "FAIL")
    new_items = []
    flipped = 0
    for it in items:
        code = (it or {}).get("item_code")
        should_fail = code in added_codes or code in belum_critical
        if (it or {}).get("status") == "PASS" and should_fail:
            new_items.append({**it, "status": "FAIL"})
            flipped += 1
        else:
            new_items.append(it)
    if flipped == 0:
        return evaluation

    new_status = "PASS" if all((it or {}).get("status") == "PASS" for it in new_items) else "FAIL"
    result = {
        **evaluation,
        "critical_compliance_check": {**ccc, "status": new_status, "checked_items": new_items},
    }
    frozen = evaluation.get("ai_score_critical_compliance_check")
    # Per-item slice = frozen/orig_fail when some already fail; otherwise derive from
    # maximum_score/4 (the definition of the frozen penalty).
    try:
        if orig_fail > 0 and frozen is not None:
            per_item = float(frozen) / orig_fail
        else:
            ms = _to_maximum_score(evaluation)
            per_item = -(ms / 4) if ms is not None else None
        if per_item is not None:
            val = per_item * (orig_fail + flipped)
            result["ai_score_critical_compliance_check"] = int(val) if val == int(val) else val
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    return result


def _to_maximum_score(evaluation: dict):
    """maximum_score for the critical slice, from the evaluation field (numeric)."""
    try:
        return float(evaluation.get("maximum_score"))
    except (TypeError, ValueError):
        return None


def inject_added_rows(table: list, visible_add_appeals: list) -> list:
    """Add display rows for ``add`` bandings (pending + approved) into the Error Code
    table, keyed by the master ``error_code`` so ``_annotate_appeals`` can attach their
    review state. For approved SCORECARD adds the structural flip also produces a
    derived B10/B12/B18 row for the same ``item_code`` — drop it so the master code is
    shown once. ``others`` adds are pure display (no structural effect)."""
    if not visible_add_appeals:
        return table
    # An APPROVED add on a structured source flips the item/field, so the builder
    # already emits a derived row for it (B10/B12/B18 scorecard, B17 card holder,
    # B02/B03/B05 cashline). Drop that row so the QC's master code shows once, not
    # twice. Only approved adds are de-duplicated: a pending add has not flipped
    # anything, so any row with the same key is a genuine AI error and must stay.
    # 'others' never collides (it has no structural row at all).
    _STRUCTURED = (SOURCE_SCORECARD, SOURCE_CASHLINE, SOURCE_CARD_HOLDER)
    replaced = {
        (SOURCE_LABELS.get(_appeal_attr(a, "add_source")), _appeal_attr(a, "item_code") or "")
        for a in visible_add_appeals
        if _appeal_attr(a, "add_source") in _STRUCTURED
        and (_appeal_attr(a, "item_code") or "")
        and effective_appeal_status(a) == "approved"
    }
    out = []
    for row in table:
        if replaced and (row.get("sumber"), row.get("item_code") or "") in replaced:
            continue  # replaced by the master-coded added row below
        out.append(row)

    for a in visible_add_appeals:
        code = _appeal_attr(a, "error_code") or ""
        source = _appeal_attr(a, "add_source") or SOURCE_OTHERS
        meta = _reason_meta(code) or {}
        ev_ts, ev_quote = _split_qc_evidence(_appeal_attr(a, "qc_evidence"))
        out.append({
            "sumber": SOURCE_LABELS.get(source, SOURCE_LABELS[SOURCE_OTHERS]),
            "error_code": code,
            # QC-edited override wins over the master-catalog default.
            "risk_base": _appeal_attr(a, "qc_risk_base") or meta.get("risk_base") or "",
            "item_code": _appeal_attr(a, "item_code") or "",
            "details_error": meta.get("details") or "",
            "reason": _appeal_attr(a, "qc_reason") or "",
            "evidence": _appeal_attr(a, "qc_evidence") or "",
            # Split so the QC Manual Check modal can prefill the two inputs separately.
            "timestamp": ev_ts,
            "evidence_quote": ev_quote,
            "ticket_id": _appeal_attr(a, "qc_ticket_id") or "",
            "reference_value": _appeal_attr(a, "qc_reference_value"),
            "extracted_value": _appeal_attr(a, "qc_extracted_value"),
        })
    return out
