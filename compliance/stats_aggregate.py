"""Statistics dashboard aggregation.

Computes the full Statistics payload consumed by the revamped Stats page:

  - ``overview``        : status counts + system-wide error rate + donut breakdown
  - ``agents``          : per-agent submissions / errors / error rate (sales table)
  - ``campaign_monthly``: per (campaign, month) submissions, Risk Base breakdown
                          (High/Medium/Low/System/New — one highest risk base per
                          ticket) and error rate
  - ``hierarchy``       : Area Manager -> Team Leader -> Agent error rates + total

"Error rate" for a bucket = ``results-with-AI-Status-RETURN / evaluated-results``
(the SAME source as the Approve/Return donut & KPIs), where a result is *evaluated*
when it is ``done`` and has a usable evaluation JSON. A result counts as an "error"
only when its final AI Status is RETURN (FAIL) — NOT merely when it has ≥1 error code,
because a ticket can carry tolerable error codes yet still PASS. The Risk Base
breakdown below tallies ONE risk base per ticket — its single highest-severity
error code — using the priority order ``H > M > L > N > O`` (see ``_RISK_PRIORITY``).
Rows are derived per result via ``build_error_code_table`` (after applying approved
Error Code appeals, mirroring the per-result Error Code table). Each error-code row
carries a ``risk_base`` of ``H``/``M``/``L`` (see ``compliance.error_codes.ERROR_CODES``);
rows for a new-joiner agent's submission get ``L``/``M`` softened to ``N`` (mirrors the
per-result Error Code table — see ``override_risk_base_for_new_joiner``), and any row
whose error code carries no catalogued risk base counts as ``O`` (System). A ticket
with no error-code rows contributes to no bucket, so H+M+L+N+O ≤ submissions.

This scan is expensive (it reads every done result's evaluation JSON), so it is run
at most once per WIB day and cached — see ``crud.get_or_build_stats_snapshot``.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func

from sales_lookup import NEW_JOINER_THRESHOLD_DAYS, active_sales_map
from compliance.error_codes import (
    _appeal_kind,
    added_appeals_only,
    apply_added_score_appeals,
    apply_approved_appeals,
    apply_approved_card_holder_appeals,
    apply_approved_cashline_appeals,
    apply_approved_critical_compliance_appeals,
    appeals_that_flip,
    approved_appeals_only,
    build_error_code_table,
    inject_added_rows,
    override_risk_base_for_new_joiner,
)
from compliance.scoring import base_ai_status, has_blocking_intolerable_item
from db import crud
from db.models import Result, ResultData, User

# tms_cashline.submit_time strings look like "2026-06-17 15:24:53" (mirrors
# sales_lookup._SUBMIT_FORMATS).
_SUBMIT_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d")


_UNKNOWN = "(Tidak diketahui)"
_WIB = ZoneInfo("Asia/Jakarta")

# Per-ticket risk severity order (H highest → O lowest). The Performa Campaign
# tally counts only ONE risk base per ticket: its single highest-severity code.
# ``N`` (new-joiner softened L/M) only appears during an agent's grace period.
_RISK_PRIORITY = {"H": 0, "M": 1, "L": 2, "N": 3, "O": 4}


def _customer_id(source_files) -> "str | None":
    """Customer/session id = prefix before the first ``_`` of the first source file."""
    if not source_files:
        return None
    first = source_files[0]
    if not isinstance(first, str) or not first:
        return None
    return first.split("_", 1)[0]


def _agent_name_fallback(agent_id) -> "str | None":
    """Fallback agent name = the alphabetic chars of the id (``rizqi801`` -> ``rizqi``)."""
    if not agent_id:
        return None
    letters = "".join(c for c in agent_id if c.isalpha())
    return letters or None


def _wib_month(dt) -> "str | None":
    """WIB ``YYYY-MM`` for a naive-UTC ``uploaded_at`` (None if missing)."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone(_WIB).strftime("%Y-%m")


def _rate(errors: int, total: int) -> float:
    """Error rate percentage (1 decimal); 0.0 when there are no submissions."""
    if not total:
        return 0.0
    return round(errors / total * 100, 1)


def _parse_submit_date(value):
    """Coerce a ``tms_cashline.submit_time`` string into a ``date`` (None if
    missing/unparseable). Mirrors ``sales_lookup._to_date``."""
    if not value:
        return None
    s = str(value).strip()
    for fmt in _SUBMIT_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _is_new_joiner(submit_time, agent_id, sales_map) -> bool:
    """Batched equivalent of ``sales_lookup.new_joiner_info(...)["is_new_joiner"]``
    — reuses the already-fetched ``sales_map`` (join dates) instead of re-querying
    the active sales database per result."""
    if not agent_id:
        return False
    submit_date = _parse_submit_date(submit_time)
    entry = sales_map.get(agent_id.casefold())
    join_date = entry.get("join_date") if entry else None
    if not submit_date or not join_date:
        return False
    return (submit_date - join_date).days < NEW_JOINER_THRESHOLD_DAYS


def _adjusted_evaluation(result_json, appeals):
    """The result's ``evaluation`` dict with approved appeals applied, or None when
    the result has no usable evaluation (i.e. it is not evaluable)."""
    if not isinstance(result_json, dict):
        return None
    evaluation = result_json.get("evaluation")
    if not isinstance(evaluation, dict):
        return None
    approved = approved_appeals_only(appeals or [])
    if approved:
        # 'change' bandings to a deduction-bearing code keep their deduction; the
        # rest flip the item/field to lift the score. 'add' bandings lower the score.
        flip = [a for a in appeals_that_flip(approved) if _appeal_kind(a) != "add"]
        evaluation = apply_approved_appeals(evaluation, flip)
        evaluation = apply_approved_card_holder_appeals(evaluation, flip)
        evaluation = apply_approved_cashline_appeals(evaluation, flip)
        evaluation = apply_approved_critical_compliance_appeals(evaluation, flip)
        evaluation = apply_added_score_appeals(evaluation, added_appeals_only(appeals or []))
    return evaluation


def _error_code_rows(result_json, appeals) -> "list | None":
    """The result's error-code rows (after approved appeals), or None when it has
    no usable evaluation."""
    evaluation = _adjusted_evaluation(result_json, appeals)
    if evaluation is None:
        return None
    # Approved adds only — a banding still awaiting review must not inflate the
    # aggregate error counts.
    return inject_added_rows(build_error_code_table(evaluation), added_appeals_only(appeals or []))


def _result_ai_status(result_json, appeals, qc_request, missing_docs=False) -> "str | None":
    """AI status 'PASS' (Approve) / 'FAIL' (Return) for a result — same logic as the
    Results table. Precedence (last wins): deterministic score (with approved
    error-code appeals already applied) -> non-tolerable veto -> missing-documents
    default (FAIL) -> an APPROVED Manual Status override (wins over everything,
    including the non-tolerable veto and appeal-adjusted score). None when not
    determinable. ``missing_docs`` = the customer's TMS data changed but no supporting
    document was uploaded."""
    evaluation = _adjusted_evaluation(result_json, appeals)
    if evaluation is None:
        return None
    status = base_ai_status(evaluation)
    if status is None:
        return None
    from compliance.error_codes import effective_appeal_status
    approved_override = qc_request is not None and effective_appeal_status(qc_request) == "approved"
    # non-tolerable veto
    if status == "PASS" and has_blocking_intolerable_item(evaluation):
        status = "FAIL"
    # missing-documents default — unless an approved Manual Status override will flip it
    if missing_docs and not approved_override:
        status = "FAIL"
    # approved Manual Status override — final authority
    if approved_override:
        status = qc_request.requested_status
    return status


def _missing_docs_map(db, results) -> dict:
    """``str(result_id) -> True`` when supporting documents are required — the
    customer's TMS data changed (Alamat Kantor/Rumah, NPWP, NIK) OR the disbursement
    limit (CUST_CRLIMIT) is >= Rp 50 juta — but none have been uploaded. Batched; the
    credit-limit lookup runs only for tickets without a TMS change flag."""
    from compliance.reference_data import get_credit_limit, npwp_required_by_limit
    ids = [str(r.id) for r in results]
    if not ids:
        return {}
    have = crud.result_ids_with_documents(db, ids)
    cid_by_rid = {}
    for r in results:
        sf = r.source_files or []
        cid_by_rid[str(r.id)] = sf[0].split("_", 1)[0] if sf and isinstance(sf[0], str) else None
    flags = crud.get_tms_cashline_change_flags(db, [c for c in cid_by_rid.values() if c])
    out = {}
    for rid, cid in cid_by_rid.items():
        f = flags.get(cid or "", {})
        needs = any(f.get(k) for k in ("kantor", "rumah", "npwp", "nik"))
        if not needs and cid:
            needs = npwp_required_by_limit(get_credit_limit(cid, db))
        out[rid] = bool(needs and rid not in have)
    return out


def compute_scoped_overview(db, customer_ids) -> dict:
    """Overview KPIs (status counts + error rate + donut breakdown) scoped to a set
    of customer/ticket ids — used by the Sales Agent (Team Leader) Statistics page.

    ``customer_ids`` is the list of ``tms_cashline.result_id`` allowed for the login.
    An empty list yields an all-zero overview. Error rate = done results with ≥1
    error code / done results that are evaluable (mirrors the global aggregation).
    """
    ids = list(customer_ids or [])
    if not ids:
        return _empty_overview()

    prefix = func.split_part(Result.source_files[0].astext, "_", 1)
    results = db.query(Result).filter(prefix.in_(ids)).all()

    counts = {"pending": 0, "processing": 0, "done": 0, "failed": 0}
    for r in results:
        if r.status in counts:
            counts[r.status] += 1
    total = len(results)

    done_ids = [r.id for r in results if r.status == "done"]
    eval_by_id: dict = {}
    if done_ids:
        for rid, rjson in (
            db.query(ResultData.result_id, ResultData.result_json)
            .filter(ResultData.result_id.in_(done_ids))
            .order_by(ResultData.created_at.desc())
            .all()
        ):
            eval_by_id.setdefault(str(rid), rjson)
    appeal_map = crud.error_code_appeals_for_results(db, [str(r) for r in done_ids])
    qc_map = crud.qc_status_requests_for(db, [str(r) for r in done_ids])

    mdocs = _missing_docs_map(db, [r for r in results if r.status == "done"])
    total_eval = total_err = approve = ret = 0
    for rid in done_ids:
        ev = eval_by_id.get(str(rid))
        ap = appeal_map.get(str(rid))
        if _adjusted_evaluation(ev, ap) is None:
            continue  # not evaluable — excluded from every rate
        total_eval += 1
        # Error/failed = AI Status RETURN (FAIL), sama dengan donut & KPI.
        ai = _result_ai_status(ev, ap, qc_map.get(str(rid)), mdocs.get(str(rid), False))
        if ai == "PASS":
            approve += 1
        elif ai == "FAIL":
            ret += 1
        total_err += 1 if ai == "FAIL" else 0

    return {
        "total_submissions": total,
        "done": counts["done"],
        "processing": counts["processing"],
        "pending": counts["pending"],
        "failed": counts["failed"],
        "evaluated": total_eval,
        "error_count": total_err,
        "error_rate": _rate(total_err, total_eval),
        "status_breakdown": {
            "done": counts["done"],
            "in_progress": counts["pending"] + counts["processing"],
            "failed": counts["failed"],
        },
        "ai_status_breakdown": {"approve": approve, "return": ret},
    }


# --- Approve/Return time series (100% stacked column chart) -----------------

_TIMESERIES_GRANULARITIES = ("daily", "weekly", "monthly", "quarterly", "semester", "yearly")
_MONTHS_ABBR = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
# Safety cap so a pathological absolute range (e.g. daily over many years) can't
# emit thousands of columns; keep the most recent buckets.
_MAX_TIMESERIES_BUCKETS = 500


def _wib_date(dt):
    """WIB calendar date for a naive-UTC ``uploaded_at`` (None if missing)."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone(_WIB).date()


def _wib_today() -> date:
    return datetime.now(timezone.utc).astimezone(_WIB).date()


def _series_date(r):
    """Calendar date used to place a result on the AI-status chart's x-axis.

    Prefers the transcript's wall-clock ``generated_at`` (naive/local — used as-is,
    no UTC→WIB shift, so a 22:58 stamp stays on its own day); falls back to the WIB
    date of ``uploaded_at`` when the ticket has no parsed ``Generated`` timestamp."""
    if getattr(r, "generated_at", None) is not None:
        return r.generated_at.date()
    return _wib_date(r.uploaded_at)


def _parse_ymd(value):
    """Parse a 'YYYY-MM-DD' string into a date (None if missing/invalid)."""
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _sub_months(d: date, n: int) -> date:
    """First day of the month ``n`` months before ``d``."""
    total = d.year * 12 + (d.month - 1) - n
    y, m = divmod(total, 12)
    return date(y, m + 1, 1)


def _add_months(d: date, n: int) -> date:
    """``d`` moved by ``n`` months (n may be negative), keeping the day-of-month but
    clamping to the target month's length (e.g. Jan 31 + 1mo → Feb 28/29)."""
    total = d.year * 12 + (d.month - 1) + n
    y, m = divmod(total, 12)
    m += 1
    first_next = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
    last_day = (first_next - timedelta(days=1)).day
    return date(y, m, min(d.day, last_day))


def _shift_anchor(anchor: date, granularity: str, offset: int) -> date:
    """Move the window ``anchor`` by ``offset`` whole windows, for the chart's
    Prev/Next paging. Window widths mirror ``_default_timeseries_range`` (daily 7d,
    weekly 4wk, monthly 4mo, quarterly 4q, semester 4sem, yearly 4y). ``offset`` < 0
    pages toward older data, > 0 toward newer."""
    if not offset:
        return anchor
    if granularity == "daily":
        return anchor + timedelta(days=7 * offset)
    if granularity == "weekly":
        return anchor + timedelta(weeks=4 * offset)
    if granularity == "quarterly":
        return _add_months(anchor, 12 * offset)
    if granularity == "semester":
        return _add_months(anchor, 24 * offset)
    if granularity == "yearly":
        return _add_months(anchor, 48 * offset)
    # monthly (default)
    return _add_months(anchor, 4 * offset)


def _bucket_of(d: date, granularity: str):
    """(key, label) for the bucket that WIB date ``d`` falls into. ``key`` sorts
    chronologically as a string within a granularity; ``label`` is for the axis."""
    if granularity == "daily":
        return d.isoformat(), f"{d.day} {_MONTHS_ABBR[d.month - 1]}"
    if granularity == "weekly":
        iso = d.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}", f"W{iso[1]} {iso[0]}"
    if granularity == "quarterly":
        q = (d.month - 1) // 3 + 1
        return f"{d.year}-Q{q}", f"Q{q} {d.year}"
    if granularity == "semester":
        s = 1 if d.month <= 6 else 2
        return f"{d.year}-S{s}", f"S{s} {d.year}"
    if granularity == "yearly":
        return str(d.year), str(d.year)
    # monthly (default)
    return f"{d.year}-{d.month:02d}", f"{_MONTHS_ABBR[d.month - 1]} {d.year}"


def _enumerate_buckets(start: date, end: date, granularity: str):
    """Ordered, de-duplicated (key, label) buckets covering [start, end] inclusive.
    Iterates day-by-day so one bucket mapping drives every granularity."""
    out = []
    seen = set()
    d = start
    step = timedelta(days=1)
    while d <= end:
        key, label = _bucket_of(d, granularity)
        if key not in seen:
            seen.add(key)
            out.append((key, label))
        d += step
    return out


def _default_timeseries_range(granularity: str, anchor: date):
    """Default [start, end] window when no explicit dates are given, all ending at
    ``anchor`` (the latest transcript/upload date in scope): daily→7 days,
    weekly→4 weeks, monthly→4 months, quarterly→4 quarters, semester→4 semesters,
    yearly→4 years. Each window starts at the beginning of the period containing
    ``anchor`` and steps back to give the requested number of buckets."""
    if granularity == "daily":
        return anchor - timedelta(days=6), anchor
    if granularity == "weekly":
        monday = anchor - timedelta(days=anchor.weekday())
        return monday - timedelta(weeks=3), anchor
    if granularity == "quarterly":
        q_start_month = ((anchor.month - 1) // 3) * 3 + 1
        return _sub_months(date(anchor.year, q_start_month, 1), 9), anchor
    if granularity == "semester":
        s_start_month = 1 if anchor.month <= 6 else 7
        return _sub_months(date(anchor.year, s_start_month, 1), 18), anchor
    if granularity == "yearly":
        return date(anchor.year - 3, 1, 1), anchor
    # monthly (default): last 4 months
    return _sub_months(anchor, 3), anchor


def compute_ai_status_timeseries(db, customer_ids, campaign, granularity, start, end, offset=0) -> dict:
    """Approve/Return counts bucketed over time (WIB ``uploaded_at``) for the 100%
    stacked column chart on the Statistics page.

    ``customer_ids`` = None -> global (every result); a list -> scoped to those
    ticket ids (Sales Agent / Team Leader / Area Manager). ``campaign`` optionally
    restricts to one campaign. ``granularity`` is one of daily/weekly/monthly/
    quarterly/semester/yearly. ``start``/``end`` are 'YYYY-MM-DD' strings (WIB); when
    absent a per-granularity default window is used, anchored to the latest transcript
    date in scope. ``offset`` pages that default window by whole windows (0 = latest,
    -1 = one window older, +1 = newer); ignored when ``start``/``end`` are given.
    Empty buckets are kept
    (approve=return=0) so the time axis stays continuous. AI status is computed per
    result (``_result_ai_status``), identical to the KPIs/donut it replaces."""
    g = granularity if granularity in _TIMESERIES_GRANULARITIES else "monthly"

    # --- select the results in scope (all statuses — Total Submissions counts every
    # ticket in the window, not just the evaluated ones) ---
    if customer_ids is None:
        results = db.query(Result).all()
    elif not customer_ids:
        results = []
    else:
        prefix = func.split_part(Result.source_files[0].astext, "_", 1)
        results = (
            db.query(Result)
            .filter(prefix.in_(list(customer_ids)))
            .all()
        )
    if campaign:
        want = str(campaign).strip().lower()
        results = [r for r in results if str(r.campaign or "").strip().lower() == want]

    # Anchor the default window to the latest transcript date in scope (the newest
    # _series_date across the selected results), so the last bucket always carries
    # data; fall back to WIB today when the scope is empty.
    series_dates = [d for r in results if (d := _series_date(r)) is not None]
    anchor = max(series_dates) if series_dates else _wib_today()

    start_d = _parse_ymd(start)
    end_d = _parse_ymd(end)
    if start_d is None or end_d is None:
        # Prev/Next paging shifts the default window by whole windows — only in pure
        # default mode (no manual date bound); an explicit start/end takes precedence.
        anchor_eff = anchor
        if start_d is None and end_d is None:
            try:
                off = int(offset)
            except (TypeError, ValueError):
                off = 0
            anchor_eff = _shift_anchor(anchor, g, off)
        d_start, d_end = _default_timeseries_range(g, anchor_eff)
        start_d = start_d or d_start
        end_d = end_d or d_end
    if start_d > end_d:
        start_d, end_d = end_d, start_d

    # keep only results whose chart date (transcript "Generated", else uploaded_at)
    # is inside the window
    in_range = []
    for r in results:
        d = _series_date(r)
        if d is not None and start_d <= d <= end_d:
            in_range.append((r, d))

    # only "done" tickets carry an evaluation → feed approve/return
    done_ids = [r.id for r, _ in in_range if r.status == "done"]
    eval_by_id: dict = {}
    if done_ids:
        for rid, rjson in (
            db.query(ResultData.result_id, ResultData.result_json)
            .filter(ResultData.result_id.in_(done_ids))
            .order_by(ResultData.created_at.desc())
            .all()
        ):
            eval_by_id.setdefault(str(rid), rjson)
    appeal_map = crud.error_code_appeals_for_results(db, [str(r) for r in done_ids])
    qc_map = crud.qc_status_requests_for(db, [str(r) for r in done_ids])
    mdocs = _missing_docs_map(db, [r for r, _ in in_range if r.status == "done"])

    # bucket key -> [approve, return, submissions, done, in_progress]
    counts: dict = {}
    for r, d in in_range:
        key, _ = _bucket_of(d, g)
        c = counts.setdefault(key, [0, 0, 0, 0, 0])
        c[2] += 1  # submissions — every ticket dated into this bucket
        if r.status == "done":
            c[3] += 1
        elif r.status in ("pending", "processing"):
            c[4] += 1  # in_progress
        if r.status != "done":
            continue
        ev = eval_by_id.get(str(r.id))
        ap = appeal_map.get(str(r.id))
        if _adjusted_evaluation(ev, ap) is None:
            continue  # not evaluable — excluded from approve/return, same as the donut/KPIs
        ai = _result_ai_status(ev, ap, qc_map.get(str(r.id)), mdocs.get(str(r.id), False))
        if ai == "PASS":
            c[0] += 1
        elif ai == "FAIL":
            c[1] += 1

    _z = [0, 0, 0, 0, 0]
    buckets = [
        {
            "key": key,
            "label": label,
            "approve": counts.get(key, _z)[0],
            "return": counts.get(key, _z)[1],
            "submissions": counts.get(key, _z)[2],
            "done": counts.get(key, _z)[3],
            "in_progress": counts.get(key, _z)[4],
        }
        for key, label in _enumerate_buckets(start_d, end_d, g)
    ]
    if len(buckets) > _MAX_TIMESERIES_BUCKETS:
        buckets = buckets[-_MAX_TIMESERIES_BUCKETS:]

    return {"granularity": g, "start": start_d.isoformat(), "end": end_d.isoformat(), "buckets": buckets}


def compute_team_agents(db, agent_ids) -> list:
    """Per-agent roster + stats for a Team Leader's (or Area Manager's) Statistics table.

    ``agent_ids`` = the USER IDs (casefold) of the agents in scope — under this TL
    (``cashline_agent_ids_for_tl``) or, for an Area Manager, every agent across all
    their team leaders (``cashline_agent_ids_for_am``). Returns one row per agent —
    INCLUDING agents with no tickets yet — each with {agent_id, name, nip_baru,
    team_leader, submissions, errors, error_rate}; ``team_leader`` lets the Area
    Manager roster group/label by TL. ``submissions`` counts EVALUATED tickets (done + usable evaluation);
    ``errors`` = tickets with AI Status RETURN (FAIL) — the same Return-based
    definition as the donut & KPIs (mirrors the global Performa Sales table).
    """
    ids = [str(a).strip().casefold() for a in (agent_ids or []) if str(a).strip()]
    if not ids:
        return []
    sales_map = active_sales_map(db)

    # customer_id -> agent_id, dibatasi ke agen dalam scope. Sumbernya
    # crud.cashline_agent_index() (snapshot reference_data di result_json),
    # BUKAN lagi tabel tms_cashline yang sudah tidak terisi.
    id_set = set(ids)
    cid_to_agent: dict = {}
    for cid, entry in crud.cashline_agent_index(db).items():
        aid = (entry["agent_id"] or "").casefold()
        if cid and aid in id_set:
            cid_to_agent[cid] = aid

    per_agent = defaultdict(lambda: {"submissions": 0, "errors": 0})
    if cid_to_agent:
        prefix = func.split_part(Result.source_files[0].astext, "_", 1)
        results = db.query(Result).filter(prefix.in_(list(cid_to_agent.keys()))).all()
        done_ids, result_agent = [], {}
        for r in results:
            sf = r.source_files or []
            cid = sf[0].split("_", 1)[0] if sf and isinstance(sf[0], str) else None
            aid = cid_to_agent.get((cid or "").strip())
            if not aid:
                continue
            result_agent[str(r.id)] = aid
            if r.status == "done":
                done_ids.append(r.id)

        eval_by_id: dict = {}
        if done_ids:
            for rid, rjson in (
                db.query(ResultData.result_id, ResultData.result_json)
                .filter(ResultData.result_id.in_(done_ids))
                .order_by(ResultData.created_at.desc())
                .all()
            ):
                eval_by_id.setdefault(str(rid), rjson)
        appeal_map = crud.error_code_appeals_for_results(db, [str(r) for r in done_ids])
        qc_map = crud.qc_status_requests_for(db, [str(r) for r in done_ids])
        mdocs = _missing_docs_map(db, [r for r in results if r.status == "done"])
        # submissions = evaluated (evaluable done) tickets; errors = AI Status RETURN.
        for rid in done_ids:
            ev = eval_by_id.get(str(rid))
            ap = appeal_map.get(str(rid))
            if _adjusted_evaluation(ev, ap) is None:
                continue  # not evaluable
            aid = result_agent.get(str(rid))
            if not aid:
                continue
            per_agent[aid]["submissions"] += 1
            if _result_ai_status(ev, ap, qc_map.get(str(rid)), mdocs.get(str(rid), False)) == "FAIL":
                per_agent[aid]["errors"] += 1

    out = []
    for aid in ids:
        entry = sales_map.get(aid) or {}
        acc = per_agent.get(aid, {"submissions": 0, "errors": 0})
        out.append({
            "agent_id": aid,
            "name": entry.get("name") or aid,
            "nip_baru": entry.get("nip_baru"),
            "team_leader": entry.get("team_leader"),
            "submissions": acc["submissions"],
            "errors": acc["errors"],
            "error_rate": _rate(acc["errors"], acc["submissions"]),
        })
    # Active agents first (by error rate, then volume), then 0-ticket agents by name.
    out.sort(key=lambda a: (a["submissions"] > 0, a["error_rate"], a["submissions"]), reverse=True)
    return out


def compute_scoped_hierarchy(roster) -> dict:
    """Nest a Team-Leader roster (rows from ``compute_team_agents``) into
    Team Leader -> Agent for an **Area Manager**'s scoped "Hierarki Error Rate".

    Starts at the Team Leader level: there is NO Area Manager node and NO
    "AM (unknown)" bucket (the AM only ever sees the TLs & agents beneath them).
    Each level carries submissions / errors / error_rate, plus an ``all_telesales``
    total over the AM's area. Reuses the roster's per-agent numbers so the tree and
    the "Daftar Sales Agent" table stay consistent.
    """
    tls: dict = defaultdict(list)
    for a in roster or []:
        tls[(a.get("team_leader") or "Tanpa Team Leader")].append(a)

    team_leaders = []
    tot_sub = tot_err = 0
    for tl_name, members in tls.items():
        tl_sub = sum(a["submissions"] for a in members)
        tl_err = sum(a["errors"] for a in members)
        tot_sub += tl_sub
        tot_err += tl_err
        agents = [
            {
                "agent_id": a["agent_id"],
                "name": a["name"],
                "submissions": a["submissions"],
                "errors": a["errors"],
                "error_rate": a["error_rate"],
            }
            for a in sorted(members, key=lambda a: (a["error_rate"], a["submissions"]), reverse=True)
        ]
        team_leaders.append({
            "name": tl_name,
            "submissions": tl_sub,
            "errors": tl_err,
            "error_rate": _rate(tl_err, tl_sub),
            "agents": agents,
        })
    team_leaders.sort(key=lambda t: (t["error_rate"], t["submissions"]), reverse=True)

    return {
        "all_telesales": {
            "submissions": tot_sub,
            "errors": tot_err,
            "error_rate": _rate(tot_err, tot_sub),
        },
        "team_leaders": team_leaders,
    }


def compute_qc_performance(db) -> list:
    """Per-QC performance table ("Performa QC") from ticket ASSIGNMENTS: for each QC
    (and QC Support) user, the tickets a Team Leader QC assigned to them, how many are
    EVALUATED, how many are AI Status FAIL, and the error rate. Mirrors
    ``compute_team_agents`` but scoped by QC assignment instead of sales hierarchy.
    QCs with no assignment appear with zeros."""
    assignments = crud.list_qc_assignments(db)
    qc_users = {
        u.username: (u.name or u.username)
        for u in db.query(User).filter(User.role.in_(["qc", "qc_support"]), User.is_active == True).all()  # noqa: E712
    }
    # TEMPORARY supervisor mapping (no stored TL QC -> QC linkage yet): Team Leader QC
    # "Dhea" (NIP 21060814) supervises all real QC/QC Support; test accounts sit under
    # the test Team Leader QC "behati".
    _tlqc_names = {u.username: (u.name or u.username) for u in db.query(User).filter(User.role == "team_leader_qc").all()}
    _TEST_QC, _REAL_TLQC, _TEST_TLQC = {"bella", "doutzen"}, "21060814", "behati"

    def _tlqc_for(qc_username):
        who = _TEST_TLQC if qc_username in _TEST_QC else _REAL_TLQC
        name = _tlqc_names.get(who) or ("Behati Prinsloo" if who == _TEST_TLQC else "DHEA KUMARING TYAS")
        return who, name
    by_qc: dict = defaultdict(list)  # qc_username -> [ticket_id]
    for a in assignments:
        by_qc[a.qc_username].append(a.ticket_id)

    per_ticket: dict = defaultdict(lambda: {"submissions": 0, "errors": 0})
    all_tickets = [a.ticket_id for a in assignments]
    if all_tickets:
        prefix = func.split_part(Result.source_files[0].astext, "_", 1)
        results = db.query(Result).filter(prefix.in_(all_tickets)).all()
        ticket_of, done_ids = {}, []
        for r in results:
            sf = r.source_files or []
            cid = sf[0].split("_", 1)[0] if sf and isinstance(sf[0], str) else None
            if cid:
                ticket_of[str(r.id)] = cid
            if r.status == "done":
                done_ids.append(r.id)
        eval_by_id: dict = {}
        if done_ids:
            for rid, rjson in (
                db.query(ResultData.result_id, ResultData.result_json)
                .filter(ResultData.result_id.in_(done_ids))
                .order_by(ResultData.created_at.desc())
                .all()
            ):
                eval_by_id.setdefault(str(rid), rjson)
        appeal_map = crud.error_code_appeals_for_results(db, [str(r) for r in done_ids])
        qc_map = crud.qc_status_requests_for(db, [str(r) for r in done_ids])
        mdocs = _missing_docs_map(db, [r for r in results if r.status == "done"])
        for rid in done_ids:
            ev = eval_by_id.get(str(rid))
            ap = appeal_map.get(str(rid))
            if _adjusted_evaluation(ev, ap) is None:
                continue
            t = ticket_of.get(str(rid))
            if not t:
                continue
            per_ticket[t]["submissions"] += 1
            if _result_ai_status(ev, ap, qc_map.get(str(rid)), mdocs.get(str(rid), False)) == "FAIL":
                per_ticket[t]["errors"] += 1

    out = []
    seen = set()
    for qc_username, tickets in by_qc.items():
        seen.add(qc_username)
        sub = sum(per_ticket[t]["submissions"] for t in tickets)
        err = sum(per_ticket[t]["errors"] for t in tickets)
        tlqc_u, tlqc_n = _tlqc_for(qc_username)
        out.append({
            "qc_username": qc_username,
            "name": qc_users.get(qc_username, qc_username),
            "tl_qc_username": tlqc_u,
            "tl_qc_name": tlqc_n,
            "assigned": len(set(tickets)),
            "submissions": sub,
            "errors": err,
            "error_rate": _rate(err, sub),
        })
    for u, n in qc_users.items():  # QCs with no assignment yet
        if u not in seen:
            tlqc_u, tlqc_n = _tlqc_for(u)
            out.append({"qc_username": u, "name": n, "tl_qc_username": tlqc_u,
                        "tl_qc_name": tlqc_n, "assigned": 0,
                        "submissions": 0, "errors": 0, "error_rate": 0.0})
    out.sort(key=lambda a: (a["submissions"] > 0, a["error_rate"], a["submissions"]), reverse=True)
    return out


def _empty_overview() -> dict:
    return {
        "total_submissions": 0, "done": 0, "processing": 0, "pending": 0, "failed": 0,
        "evaluated": 0, "error_count": 0, "error_rate": 0.0,
        "status_breakdown": {"done": 0, "in_progress": 0, "failed": 0},
        "ai_status_breakdown": {"approve": 0, "return": 0},
    }


def compute_stats_snapshot(db, customer_ids=None) -> dict:
    """Scan ``done`` results and build the full Statistics payload (see module
    docstring). Safe on empty data (returns zeroed sections).

    ``customer_ids`` (opsional) membatasi scan ke ticket/customer id tertentu —
    dipakai Area Manager supaya seluruh halaman Statistics (KPI, donut, Performa
    Sales, Performa Campaign, hierarki) dihitung dari area-nya sendiri lewat satu
    jalur kode yang sama dengan agregasi global. ``None`` = semua data (default,
    inilah yang di-cache harian). Daftar kosong menghasilkan payload nol.
    """
    base = crud.get_stats(db)  # total_uploaded / pending / processing / done / failed / active_campaigns

    q = db.query(Result).filter(Result.status == "done")
    if customer_ids is None:
        done_results = q.all()
    else:
        ids = list(customer_ids)
        # Ticket id = prefix sebelum "_" pada source file pertama, sama dengan
        # _customer_id() di bawah dan compute_scoped_overview().
        prefix = func.split_part(Result.source_files[0].astext, "_", 1)
        done_results = q.filter(prefix.in_(ids)).all() if ids else []

        # crud.get_stats() menghitung SELURUH organisasi. Dalam mode scoped angka
        # itu akan bocor ke KPI card, jadi status count dihitung ulang dari tiket
        # dalam scope saja (semua status, bukan cuma done). active_campaigns tetap
        # global — itu jumlah campaign aktif, bukan angka milik satu area.
        statuses = (
            [s for (s,) in db.query(Result.status).filter(prefix.in_(ids)).all()]
            if ids else []
        )
        counts = {"pending": 0, "processing": 0, "done": 0, "failed": 0}
        for st in statuses:
            if st in counts:
                counts[st] += 1
        base = {**base, **counts, "total_uploaded": len(statuses)}

    result_ids = [r.id for r in done_results]

    # --- Batch lookups (avoid N+1) ---------------------------------------
    # Latest result_json per result_id.
    eval_by_id: dict = {}
    if result_ids:
        for rid, rjson in (
            db.query(ResultData.result_id, ResultData.result_json)
            .filter(ResultData.result_id.in_(result_ids))
            .order_by(ResultData.created_at.desc())
            .all()
        ):
            eval_by_id.setdefault(str(rid), rjson)  # desc order => first seen is latest

    # customer_id -> agent_id / submit_time (trimmed) untuk setiap cid kita.
    # submit_time dipakai cek new-joiner di bawah. Sumbernya
    # crud.cashline_agent_index() -- satu query SQL atas snapshot reference_data
    # yang sudah tersimpan di result_json, BUKAN tabel tms_cashline yang sudah
    # tidak terisi sejak reference data pindah ke DWH API (dulu: 0 dari 34 tiket
    # ketemu, sehingga seluruh hierarki jatuh ke "(Tidak diketahui)").
    cids = {(c or "").strip() for c in (_customer_id(r.source_files) for r in done_results) if c}
    agent_by_cid: dict = {}
    submit_by_cid: dict = {}
    if cids:
        index = crud.cashline_agent_index(db)
        for key in cids:
            entry = index.get(key)
            if entry is None:
                continue
            agent_by_cid[key] = entry["agent_id"]
            submit_by_cid[key] = entry["submit_time"]

    appeal_map = crud.error_code_appeals_for_results(db, [str(r) for r in result_ids])
    qc_map = crud.qc_status_requests_for(db, [str(r) for r in result_ids])
    mdocs = _missing_docs_map(db, done_results)
    sales_map = active_sales_map(db)

    # --- Per-result reduction --------------------------------------------
    # Accumulators keyed by agent_id.
    # ``approve`` + H/M/L/N/O feed the per-agent Risk Base columns in the
    # "Hierarki Error Rate" tree (same one-top-risk-per-ticket rule as
    # campaign_risk_acc below).
    agent_acc: dict = defaultdict(lambda: {
        "submissions": 0, "errors": 0, "approve": 0,
        "H": 0, "M": 0, "L": 0, "N": 0, "O": 0,
        "campaigns": defaultdict(int),
    })
    agent_meta: dict = {}  # agent_id -> {name, team_leader, area_manager}
    # Per (campaign, month) Risk Base breakdown (H/M/L/N/O) + submissions/errors,
    # for the "Performa Campaign" table (QC / SPQ Head).
    campaign_risk_acc: dict = defaultdict(
        lambda: {"submissions": 0, "errors": 0, "H": 0, "M": 0, "L": 0, "N": 0, "O": 0}
    )
    # Per-campaign overview breakdown (Overview tab campaign filter): the same
    # donut/KPI figures the global overview carries, but keyed by campaign.
    camp_overview_acc: dict = defaultdict(
        lambda: {"approve": 0, "return": 0, "evaluated": 0, "errors": 0}
    )
    # Per (campaign, agent) submissions/errors for the campaign-filtered sales table.
    camp_agent_acc: dict = defaultdict(lambda: defaultdict(lambda: {"submissions": 0, "errors": 0}))
    total_eval = 0
    total_err = 0
    approve = ret = 0

    # All-status counts per campaign (pending/processing/done/failed) so the
    # campaign-filtered Overview KPIs cover non-done tickets too, mirroring get_stats.
    camp_status_counts: dict = defaultdict(
        lambda: {"pending": 0, "processing": 0, "done": 0, "failed": 0}
    )
    for camp, st, cnt in (
        db.query(Result.campaign, Result.status, func.count(Result.id))
        .group_by(Result.campaign, Result.status)
        .all()
    ):
        c = (camp or "").strip() or _UNKNOWN
        if st in camp_status_counts[c]:
            camp_status_counts[c][st] += cnt

    for r in done_results:
        rows = _error_code_rows(eval_by_id.get(str(r.id)), appeal_map.get(str(r.id)))
        if rows is None:
            continue  # not evaluable — excluded from every rate
        total_eval += 1
        # "Error"/"failed" untuk SEMUA error rate (agents, campaign, hierarchy) =
        # AI Status RETURN (FAIL) — sumber yang sama dengan donut & KPI. Bukan lagi
        # "punya ≥1 error code": sebuah tiket bisa punya error code tapi tetap PASS
        # bila semua pelanggarannya tolerable.
        ai = _result_ai_status(eval_by_id.get(str(r.id)), appeal_map.get(str(r.id)), qc_map.get(str(r.id)), mdocs.get(str(r.id), False))
        if ai == "PASS":
            approve += 1
        elif ai == "FAIL":
            ret += 1
        err = 1 if ai == "FAIL" else 0
        total_err += err

        cid = _customer_id(r.source_files)
        cid_key = (cid or "").strip()
        agent_id = agent_by_cid.get(cid_key) if cid else None
        akey = agent_id or _UNKNOWN
        if akey not in agent_meta:
            entry = sales_map.get(agent_id.casefold()) if agent_id else None
            agent_meta[akey] = {
                "agent_id": agent_id,
                "name": (entry.get("name") if entry else None) or _agent_name_fallback(agent_id) or _UNKNOWN,
                "team_leader": (entry.get("team_leader") if entry else None) or _UNKNOWN,
                "area_manager": (entry.get("area_manager") if entry else None) or _UNKNOWN,
            }
        acc = agent_acc[akey]
        acc["submissions"] += 1
        acc["errors"] += err
        campaign = (r.campaign or "").strip() or _UNKNOWN
        acc["campaigns"][campaign] += 1

        # Per-campaign donut/KPI + sales-table accumulation (Overview campaign filter).
        co = camp_overview_acc[campaign]
        co["evaluated"] += 1
        co["errors"] += err
        if ai == "PASS":
            co["approve"] += 1
        elif ai == "FAIL":
            co["return"] += 1
        ca = camp_agent_acc[campaign][akey]
        ca["submissions"] += 1
        ca["errors"] += err

        # Risk Base tally: a new-joiner's L/M rows soften to N (mirrors the
        # per-result Error Code table); any row without a catalogued risk
        # base (blank/unmatched error code) counts as O (System).
        # Computed once per ticket and shared by the per-agent (hierarchy) and
        # per-(campaign, month) accumulators — the latter is month-gated, the
        # former is not, so this must sit OUTSIDE the `if month:` block.
        is_new_joiner = _is_new_joiner(submit_by_cid.get(cid_key), agent_id, sales_map)
        risk_rows = override_risk_base_for_new_joiner(rows) if is_new_joiner else rows
        # Count only the SINGLE highest-severity risk base for this ticket
        # (H > M > L > N > O). A ticket with no error-code rows contributes to
        # no bucket; each ticket adds at most 1 across H/M/L/N/O.
        top = None
        for row in risk_rows:
            rb = row.get("risk_base") or "O"
            if rb not in ("H", "M", "L", "N"):
                rb = "O"
            if top is None or _RISK_PRIORITY[rb] < _RISK_PRIORITY[top]:
                top = rb

        # Per-agent Risk Base + approve tally (Hierarki Error Rate columns).
        if ai == "PASS":
            acc["approve"] += 1
        if top is not None:
            acc[top] += 1

        month = _wib_month(r.uploaded_at)
        if month:
            rc = campaign_risk_acc[(campaign, month)]
            rc["submissions"] += 1
            rc["errors"] += err
            if top is not None:
                rc[top] += 1

    # --- agents[] (sales performance table) ------------------------------
    agents = []
    for akey, acc in agent_acc.items():
        meta = agent_meta[akey]
        top_campaign = max(acc["campaigns"].items(), key=lambda kv: kv[1])[0] if acc["campaigns"] else _UNKNOWN
        agents.append({
            "agent_id": meta["agent_id"],
            "name": meta["name"],
            "team_leader": meta["team_leader"],
            "area_manager": meta["area_manager"],
            "campaign": top_campaign,
            "submissions": acc["submissions"],
            "errors": acc["errors"],
            "error_rate": _rate(acc["errors"], acc["submissions"]),
        })
    agents.sort(key=lambda a: (a["error_rate"], a["submissions"]), reverse=True)

    # --- campaign_monthly[] (Performa Campaign, month-to-month) --------------
    campaign_monthly = [
        {
            "campaign": campaign,
            "month": month,
            "submissions": v["submissions"],
            "high": v["H"],
            "medium": v["M"],
            "low": v["L"],
            "system": v["O"],
            "new": v["N"],
            "total_risk": v["H"] + v["M"] + v["L"],
            # Error Rate = Total Risk (H+M+L) / Submission — NOT the AI-Status
            # FAIL count. A ticket contributes at most 1 to H/M/L, so the ratio
            # stays <= 100%.
            "error_rate": _rate(v["H"] + v["M"] + v["L"], v["submissions"]),
        }
        for (campaign, month), v in campaign_risk_acc.items()
    ]
    campaign_monthly.sort(key=lambda x: (x["campaign"], x["month"]))
    months = sorted({x["month"] for x in campaign_monthly})

    # --- hierarchy: Area Manager -> Team Leader -> Agent -----------------
    hierarchy = _build_hierarchy(agent_acc, agent_meta, total_eval, total_err)

    error_rate = _rate(total_err, total_eval)
    overview = {
        "total_submissions": base["total_uploaded"],
        "done": base["done"],
        "processing": base["processing"],
        "pending": base["pending"],
        "failed": base["failed"],
        "evaluated": total_eval,
        "error_count": total_err,
        "error_rate": error_rate,
        "status_breakdown": {
            "done": base["done"],
            "in_progress": base["pending"] + base["processing"],
            "failed": base["failed"],
        },
        "ai_status_breakdown": {"approve": approve, "return": ret},
        "active_campaigns": base["active_campaigns"],
    }

    # --- per-campaign Overview (KPIs + donut + sales table), for the filter ------
    campaigns = sorted(set(camp_status_counts) | set(camp_overview_acc))
    overview_by_campaign: dict = {}
    agents_by_campaign: dict = {}
    for c in campaigns:
        sc = camp_status_counts.get(c, {"pending": 0, "processing": 0, "done": 0, "failed": 0})
        co = camp_overview_acc.get(c, {"approve": 0, "return": 0, "evaluated": 0, "errors": 0})
        total_sub = sc["pending"] + sc["processing"] + sc["done"] + sc["failed"]
        overview_by_campaign[c] = {
            "total_submissions": total_sub,
            "done": sc["done"],
            "processing": sc["processing"],
            "pending": sc["pending"],
            "failed": sc["failed"],
            "evaluated": co["evaluated"],
            "error_count": co["errors"],
            "error_rate": _rate(co["errors"], co["evaluated"]),
            "status_breakdown": {
                "done": sc["done"],
                "in_progress": sc["pending"] + sc["processing"],
                "failed": sc["failed"],
            },
            "ai_status_breakdown": {"approve": co["approve"], "return": co["return"]},
        }
        camp_agents = []
        for akey, cacc in camp_agent_acc.get(c, {}).items():
            meta = agent_meta[akey]
            camp_agents.append({
                "agent_id": meta["agent_id"],
                "name": meta["name"],
                "team_leader": meta["team_leader"],
                "area_manager": meta["area_manager"],
                "campaign": c,
                "submissions": cacc["submissions"],
                "errors": cacc["errors"],
                "error_rate": _rate(cacc["errors"], cacc["submissions"]),
            })
        camp_agents.sort(key=lambda a: (a["error_rate"], a["submissions"]), reverse=True)
        agents_by_campaign[c] = camp_agents

    return {
        "overview": overview,
        "agents": agents,
        "campaign_monthly": {"rows": campaign_monthly, "months": months},
        "hierarchy": hierarchy,
        "campaigns": campaigns,
        "overview_by_campaign": overview_by_campaign,
        "agents_by_campaign": agents_by_campaign,
    }


def _risk_node(v: dict) -> dict:
    """Shared field block for every level of the hierarchy tree (agent / TL / AM).

    ``error_rate`` here is REJECT-based: AI Status FAIL / submissions. That is
    deliberately NOT the Performa Campaign definition (Total Risk / Submission) —
    the two tables answer different questions, and the 3%/6% colour thresholds are
    calibrated for this reject-based rate. The Risk Base counts below are shown as
    context columns only; they do not feed the rate.
    """
    return {
        "submissions": v["submissions"],
        "errors": v["errors"],
        "approve": v["approve"],
        "risk_high": v["H"],
        "risk_medium": v["M"],
        "risk_low": v["L"],
        "risk_system": v["O"],
        "risk_new": v["N"],
        # Total Risk deliberately excludes System (O) and New (N) — same rule as
        # the Performa Campaign table.
        "total_risk": v["H"] + v["M"] + v["L"],
        "error_rate": _rate(v["errors"], v["submissions"]),
    }


def _build_hierarchy(agent_acc, agent_meta, total_eval, total_err) -> dict:
    """Nest per-agent accumulators into Area Manager -> Team Leader -> Agent, each
    level carrying submissions / errors / error_rate, plus an ``all_telesales`` total."""
    # am -> tl -> agent_key -> {submissions, errors, approve, H, M, L, N, O}
    _AGENT_KEYS = ("submissions", "errors", "approve", "H", "M", "L", "N", "O")
    tree: dict = defaultdict(
        lambda: defaultdict(lambda: defaultdict(lambda: {k: 0 for k in _AGENT_KEYS}))
    )
    for akey, acc in agent_acc.items():
        meta = agent_meta[akey]
        node = tree[meta["area_manager"]][meta["team_leader"]][akey]
        for k in _AGENT_KEYS:
            node[k] += acc.get(k, 0)

    area_managers = []
    for am_name, tls in tree.items():
        am = {k: 0 for k in _AGENT_KEYS}
        tl_list = []
        for tl_name, agents_map in tls.items():
            tl = {k: 0 for k in _AGENT_KEYS}
            agent_list = []
            for akey, v in agents_map.items():
                meta = agent_meta[akey]
                for k in _AGENT_KEYS:
                    tl[k] += v[k]
                agent_list.append({
                    "agent_id": meta["agent_id"],
                    "name": meta["name"],
                    **_risk_node(v),
                })
            agent_list.sort(key=lambda a: (a["error_rate"], a["submissions"]), reverse=True)
            for k in _AGENT_KEYS:
                am[k] += tl[k]
            tl_list.append({"name": tl_name, **_risk_node(tl), "agents": agent_list})
        tl_list.sort(key=lambda t: (t["error_rate"], t["submissions"]), reverse=True)
        area_managers.append({"name": am_name, **_risk_node(am), "team_leaders": tl_list})
    area_managers.sort(key=lambda a: (a["error_rate"], a["submissions"]), reverse=True)

    # Grand total for the Risk Base context columns. ``submissions``/``errors``
    # come from the caller's totals (they also count agents that fall outside the
    # AM/TL mapping, which the tree cannot represent), and the rate stays
    # reject-based like every node beneath it.
    grand = {k: 0 for k in _AGENT_KEYS}
    for acc in agent_acc.values():
        for k in _AGENT_KEYS:
            grand[k] += acc.get(k, 0)
    all_telesales = _risk_node(grand)
    all_telesales["submissions"] = total_eval
    all_telesales["errors"] = total_err
    all_telesales["error_rate"] = _rate(total_err, total_eval)

    return {
        "all_telesales": all_telesales,
        "area_managers": area_managers,
    }
