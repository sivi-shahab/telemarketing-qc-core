import copy
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Lock
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from db.models import (
    Campaign,
    Document,
    ErrorCodeAppeal,
    QcAssignment,
    QcDatabase,
    QcManualCheck,
    QcStatusRequest,
    Result,
    ResultData,
    SalesDatabase,
    StatsSnapshot,
    User,
)
# Reference data (CASHLINE / CARD HOLDER) sekarang dari DWH API (Aplikasi A),
# bukan lagi tabel DB -> lihat services/data_dwh.py.
from services import data_dwh


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
def create_result(
    db: Session,
    campaign: str,
    source_files: list,
    num_calls: int,
    transcript_path: str,
    uploaded_by_username: str = None,
    uploaded_by_role: str = None,
    id: str = None,            # opsional — kalau diisi, pakai ID ini (mis. STT job_id)
    status: str = "pending",   # opsional — default tetap "pending"
) -> Result:
    result = Result(
        campaign=campaign,
        source_files=source_files,
        num_calls=num_calls,
        transcript_path=transcript_path,
        status=status,
        uploaded_by_username=uploaded_by_username,
        uploaded_by_role=uploaded_by_role,
    )
    if id is not None:
        # uuid.UUID(...) memvalidasi formatnya sekaligus; kalau job_id dari STT
        # bukan UUID valid, ini raise ValueError lebih awal (fail cepat & jelas).
        result.id = uuid.UUID(str(id))
    db.add(result)
    db.commit()
    db.refresh(result)
    return result


def get_result(db: Session, result_id: str) -> Optional[Result]:
    return db.query(Result).filter(Result.id == uuid.UUID(str(result_id))).first()


def get_result_by_source_file(db: Session, filename: str) -> Optional[Result]:
    """Cari Result terbaru yang source_files-nya memuat ``filename`` (mis.
    ``"061058ecB3_20260612171830.pdf"``). Memakai JSONB containment (``@>``)."""
    return (
        db.query(Result)
        .filter(Result.source_files.contains([filename]))
        .order_by(desc(Result.uploaded_at))
        .first()
    )


def pick_reusable_done_result(db: Session, customer_id: str) -> Optional[Result]:
    """Pilih Result ``done`` untuk ``customer_id`` (prefix sebelum ``_`` pada
    file pertama) yang boleh di-reuse saat upload duplikat.

    Prioritas: Result yang punya minimal 1 banding (``ErrorCodeAppeal``, status
    apapun); jika tidak ada, Result dengan ``uploaded_at`` terbaru.
    """
    candidates = (
        db.query(Result)
        .filter(
            Result.status == "done",
            func.split_part(Result.source_files[0].astext, "_", 1) == customer_id,
        )
        .order_by(desc(Result.uploaded_at))
        .all()
    )
    if not candidates:
        return None
    # candidates sudah urut uploaded_at desc -> kandidat pertama yang punya
    # banding = Result terbaru yang punya banding.
    for r in candidates:
        has_appeal = (
            db.query(ErrorCodeAppeal.id)
            .filter(ErrorCodeAppeal.result_id == r.id)
            .first()
        )
        if has_appeal:
            return r
    return candidates[0]


def clone_result_from(db: Session, source: Result, target: Result) -> dict:
    """Klon hasil ``source`` (status ``done``) ke row ``target`` yang baru dibuat.

    Menyalin ``result_json`` (evaluasi LLM), seluruh ``ErrorCodeAppeal`` (banding)
    dan ``QcStatusRequest`` (usulan status QC + approval SPQ Head) milik ``source``
    ke ``target``, lalu menandai ``target`` sebagai ``done`` — TANPA memanggil
    LLM. Return ``result_json`` hasil salinan (untuk di-mirror ke object storage).
    """
    src_data = get_result_data(db, source.id)
    result_json = copy.deepcopy(src_data.result_json) if (src_data and src_data.result_json) else {}
    if isinstance(result_json, dict):
        # Sesuaikan identitas ke row baru.
        result_json["result_id"] = str(target.id)
        result_json["source_files"] = target.source_files
    save_result_data(db, target.id, result_json)
    # Klon semua banding (append-only history dipertahankan apa adanya).
    for a in error_code_appeals_for_result(db, source.id):
        db.add(
            ErrorCodeAppeal(
                result_id=target.id,
                error_code=a.error_code,
                item_code=a.item_code,
                ai_sumber=a.ai_sumber,
                ai_risk_base=a.ai_risk_base,
                ai_details_error=a.ai_details_error,
                ai_reason=a.ai_reason,
                ai_evidence=a.ai_evidence,
                ai_ticket_id=a.ai_ticket_id,
                qc_reason=a.qc_reason,
                qc_evidence=a.qc_evidence,
                qc_ticket_id=a.qc_ticket_id,
                approval_status=a.approval_status,
                requested_by_username=a.requested_by_username,
                requested_at=a.requested_at,
                reviewed_by_username=a.reviewed_by_username,
                reviewed_at=a.reviewed_at,
            )
        )
    # Klon usulan status QC (+ approval SPQ Head) bila ada. result_id target unik
    # sehingga constraint UNIQUE(result_id) aman.
    src_req = get_qc_status_request(db, source.id)
    if src_req is not None:
        db.add(
            QcStatusRequest(
                result_id=target.id,
                requested_status=src_req.requested_status,
                reason=src_req.reason,
                requested_by_username=src_req.requested_by_username,
                requested_by_role=src_req.requested_by_role,
                requested_at=src_req.requested_at,
                approval_status=src_req.approval_status,
                reviewed_by_username=src_req.reviewed_by_username,
                reviewed_at=src_req.reviewed_at,
            )
        )
    target.status = "done"
    target.result_path = f"{target.id}.json"
    target.started_at = func.now()
    target.completed_at = func.now()
    target.processing_sec = source.processing_sec
    db.commit()
    db.refresh(target)
    return result_json


def update_result_status(
    db: Session,
    result_id: str,
    status: str,
    error_message: str = None,
    result_path: str = None,
    started_at: datetime = None,
    completed_at: datetime = None,
    processing_sec: float = None,
    generated_at: datetime = None,
) -> Optional[Result]:
    result = get_result(db, result_id)
    if not result:
        return None
    result.status = status
    if error_message is not None:
        result.error_message = error_message
    if result_path is not None:
        result.result_path = result_path
    if generated_at is not None:
        result.generated_at = generated_at
    if started_at is not None:
        result.started_at = started_at
    if completed_at is not None:
        result.completed_at = completed_at
    if processing_sec is not None:
        result.processing_sec = processing_sec
    db.commit()
    db.refresh(result)
    return result

def result_json_map(db: Session, result_ids: list[str]) -> dict:
    """Latest result_json per result_id, in one batched query (no N+1).
    Mirrors the snapshot builder: rows come back newest-first, so the first seen
    per id is the latest. Ids without result data are simply absent from the map.
    """
    if not result_ids:
        return {}
    uuids = [uuid.UUID(str(rid)) for rid in result_ids]
    out: dict = {}
    for rid, rjson in (
        db.query(ResultData.result_id, ResultData.result_json)
        .filter(ResultData.result_id.in_(uuids))
        .order_by(desc(ResultData.created_at))
        .all()
    ):
        out.setdefault(str(rid), rjson)
    return out


def save_result_data(db: Session, result_id: str, result_json: dict) -> ResultData:
    data = ResultData(result_id=uuid.UUID(str(result_id)), result_json=result_json)
    db.add(data)
    db.commit()
    db.refresh(data)
    return data


def get_result_data(db: Session, result_id: str) -> Optional[ResultData]:
    return (
        db.query(ResultData)
        .filter(ResultData.result_id == uuid.UUID(str(result_id)))
        .order_by(desc(ResultData.created_at))
        .first()
    )


def list_results(
    db: Session,
    status: Optional[str] = None,
    campaign: Optional[str] = None,
    ticket_id: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
    customer_ids: Optional[list[str]] = None,
    uploaded_by_role: Optional[str] = None,
    exclude_uploaded_by_role: Optional[str] = None,
    uploaded_by_username: Optional[str] = None,
    date_start=None,
    date_end=None,
) -> tuple[list[Result], int]:
    # ``customer_ids`` (when not None) scopes results to those customer/ticket ids —
    # used to restrict a sales_agent (Team Leader) to their agents' tickets. An
    # empty list means "no allowed ids" => no results (short-circuit).
    # ``uploaded_by_role`` / ``exclude_uploaded_by_role`` isolate QC Support's
    # complaint results: QC Support sees only its own uploads; every other role
    # excludes them (a standalone, isolated result set). ``uploaded_by_username``
    # narrows to a single uploader (Team Leader QC's "Semua QC Support" filter).
    if customer_ids is not None and len(customer_ids) == 0:
        return [], 0
    q = db.query(Result)
    if uploaded_by_username is not None:
        q = q.filter(
            func.lower(func.trim(Result.uploaded_by_username))
            == (uploaded_by_username or "").strip().casefold()
        )
    if uploaded_by_role is not None:
        q = q.filter(Result.uploaded_by_role == uploaded_by_role)
    if exclude_uploaded_by_role is not None:
        q = q.filter(
            (Result.uploaded_by_role.is_(None))
            | (Result.uploaded_by_role != exclude_uploaded_by_role)
        )
    if status:
        q = q.filter(Result.status == status)
    if campaign:
        q = q.filter(Result.campaign == campaign)
    if ticket_id:
        # The displayed "ID" is the prefix before the first "_" of the first
        # source filename (see stats._customer_id_from_files), so match that
        # first filename by prefix — a full or partial ticket id both work.
        q = q.filter(Result.source_files[0].astext.ilike(f"{ticket_id}%"))
    if customer_ids is not None:
        # customer_id = prefix before the first "_" of the first source filename.
        q = q.filter(
            func.split_part(Result.source_files[0].astext, "_", 1).in_(customer_ids)
        )
    if date_start is not None or date_end is not None:
        # Filter by the transcript's chart date: the wall-clock ``generated_at`` when
        # present (naive/local, used as-is), else the WIB calendar date of
        # ``uploaded_at`` — same basis as the Statistics chart (_series_date).
        series_date = func.coalesce(
            func.date(Result.generated_at),
            func.date(func.timezone("Asia/Jakarta", func.timezone("UTC", Result.uploaded_at))),
        )
        if date_start is not None:
            q = q.filter(series_date >= date_start)
        if date_end is not None:
            q = q.filter(series_date <= date_end)
    total = q.count()
    items = (
        q.order_by(desc(Result.uploaded_at))
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    return items, total


def list_transcripts(
    db: Session,
    status: Optional[str] = None,
    campaign: Optional[str] = None,
    ticket_id: Optional[str] = None,
    ai_status: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
    uploaded_by_role: Optional[str] = None,
    exclude_uploaded_by_role: Optional[str] = None,
) -> tuple[list[dict], int]:
    """Flatten every Result's ``source_files`` into one row per transcript PDF —
    a single ticket/Result can bundle several call transcripts (``num_calls``).
    Filtering/pagination happens at the flattened-row level, not the Result level.

    ``ai_status`` ("PASS"=Approve / "FAIL"=Reject) mirrors the Results table filter:
    AI Status is derived per Result (not stored), so it is only meaningful for
    completed results — passing it forces ``status="done"`` and filters the results
    in Python before flattening.
    """
    ai_filter = ai_status.strip().upper() if isinstance(ai_status, str) else None
    # AI Status is only determinable for done results — override the processing status.
    effective_status = "done" if ai_filter in ("PASS", "FAIL") else status

    q = db.query(Result)
    if uploaded_by_role is not None:
        q = q.filter(Result.uploaded_by_role == uploaded_by_role)
    if exclude_uploaded_by_role is not None:
        q = q.filter(
            (Result.uploaded_by_role.is_(None))
            | (Result.uploaded_by_role != exclude_uploaded_by_role)
        )
    if effective_status:
        q = q.filter(Result.status == effective_status)
    if campaign:
        q = q.filter(Result.campaign == campaign)
    if ticket_id:
        # Coarse SQL pre-filter on the first file's prefix (mirrors list_results);
        # the exact per-file check below covers bundles with mixed prefixes.
        q = q.filter(Result.source_files[0].astext.ilike(f"{ticket_id}%"))
    results = q.order_by(desc(Result.uploaded_at)).all()

    if ai_filter in ("PASS", "FAIL"):
        # Compute each result's AI Status with the same canonical helper the Results
        # table uses, then keep only the matching Approve/Reject subset.
        from compliance.stats_aggregate import _result_ai_status

        rids = [str(r.id) for r in results]
        appeals = error_code_appeals_for_results(db, rids)
        qc_reqs = qc_status_requests_for(db, rids)
        rjson = result_json_map(db, rids)
        results = [
            r for r in results
            if _result_ai_status(rjson.get(str(r.id)), appeals.get(str(r.id)), qc_reqs.get(str(r.id))) == ai_filter
        ]

    rows = []
    for r in results:
        for fn in (r.source_files or []):
            if not isinstance(fn, str) or not fn:
                continue
            tid = fn.split("_", 1)[0]
            if ticket_id and not tid.lower().startswith(ticket_id.lower()):
                continue
            rows.append({
                "result_id": str(r.id),
                "filename": fn,
                "ticket_id": tid,
                "campaign": r.campaign,
                "status": r.status,
                "uploaded_at": r.uploaded_at,
                "uploaded_by_username": r.uploaded_by_username,
                "uploaded_by_role": r.uploaded_by_role,
            })

    total = len(rows)
    start = (page - 1) * limit
    return rows[start : start + limit], total


def list_results_by_date_range(
    db: Session,
    start_date,
    end_date,
    status: str = "done",
) -> list[Result]:
    """Return results whose ``uploaded_at`` date falls within ``[start_date,
    end_date]`` (both inclusive), filtered by ``status`` (default ``done``).

    ``start_date``/``end_date`` are ``date`` objects compared against the
    Asia/Jakarta (WIB) calendar date of ``uploaded_at`` (stored as naive UTC),
    inclusive on both ends. Ordered ascending by ``uploaded_at`` for stable CSV.
    """
    # naive UTC -> timestamptz (UTC) -> naive WIB -> date
    wib_date = func.date(
        func.timezone("Asia/Jakarta", func.timezone("UTC", Result.uploaded_at))
    )
    q = db.query(Result)
    if status:
        q = q.filter(Result.status == status)
    q = q.filter(wib_date >= start_date)
    q = q.filter(wib_date <= end_date)
    return q.order_by(Result.uploaded_at).all()


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
def get_stats(db: Session) -> dict:
    counts = (
        db.query(Result.status, func.count(Result.id))
        .group_by(Result.status)
        .all()
    )
    status_map = {row[0]: row[1] for row in counts}
    total = sum(status_map.values())
    avg_row = (
        db.query(func.avg(Result.processing_sec))
        .filter(Result.status == "done")
        .scalar()
    )
    active_campaigns = [c.name for c in list_campaigns(db) if c.is_active]
    return {
        "total_uploaded": total,
        "pending": status_map.get("pending", 0),
        "processing": status_map.get("processing", 0),
        "done": status_map.get("done", 0),
        "failed": status_map.get("failed", 0),
        "avg_processing_sec": round(avg_row, 2) if avg_row else None,
        "active_campaigns": active_campaigns,
    }


def get_daily_stats(db: Session) -> list[dict]:
    from sqlalchemy import text
    # uploaded_at is naive UTC; bucket by Asia/Jakarta (WIB) calendar date.
    rows = db.execute(
        text("""
            SELECT
                ((uploaded_at AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Jakarta')::date AS day,
                COUNT(*) AS uploaded,
                SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done,
                SUM(CASE WHEN status = 'processing' THEN 1 ELSE 0 END) AS processing,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed
            FROM results
            WHERE uploaded_at >= NOW() - INTERVAL '30 days'
            GROUP BY ((uploaded_at AT TIME ZONE 'UTC') AT TIME ZONE 'Asia/Jakarta')::date
            ORDER BY day DESC
        """)
    ).fetchall()
    return [
        {
            "date": str(row.day),
            "uploaded": int(row.uploaded),
            "done": int(row.done),
            "processing": int(row.processing),
            "pending": int(row.pending),
            "failed": int(row.failed),
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Statistics snapshot (daily cache of the Statistics dashboard payload)
# ---------------------------------------------------------------------------

def _wib_today_str() -> str:
    """Today's Asia/Jakarta (WIB) calendar date as ``"YYYY-MM-DD"``."""
    from datetime import timezone
    from zoneinfo import ZoneInfo

    return (
        datetime.now(timezone.utc)
        .astimezone(ZoneInfo("Asia/Jakarta"))
        .date()
        .isoformat()
    )


# ---------------------------------------------------------------------------
# Index cid -> (agent_id, submit_time)
# ---------------------------------------------------------------------------
# Tabel lokal ``tms_cashline`` sudah TIDAK diisi lagi sejak reference data pindah
# ke DWH API (services/data_dwh.py) -- isinya sisa era CSV. Semua pemetaan
# cid <-> agent_id sekarang lewat index di bawah ini.
#
# Sumber utama: ``reference_data.cashline`` yang SUDAH tersimpan di
# result_data.result_json (disisipkan worker saat evaluasi, lihat
# worker/tasks/process_transcript.py). Itu berarti SATU query SQL, tanpa
# panggilan HTTP sama sekali -- penting karena index ini dipakai agregasi
# Statistics yang menyentuh SELURUH result sekaligus.
#
# Fallback DWH API hanya untuk cid yang snapshot-nya belum punya kedua field
# (hasil evaluasi SEBELUM App A menyimpan agent_id/submit_time di cache-nya).
# Dipanggil paralel & di-memo permanen per proses: untuk tiket yang sudah
# selesai, agent_id/submit_time tidak akan berubah lagi.
_CASHLINE_ID_MEMO: dict = {}
_CASHLINE_ID_MEMO_LOCK = Lock()
_CASHLINE_FALLBACK_WORKERS = 8


def _cashline_ids_from_dwh(cids: list) -> dict:
    """``{cid: {"agent_id", "submit_time"}}`` dari DWH untuk cid yang belum ter-memo.

    Paralel (thread pool kecil) supaya latensi total ~= panggilan paling lambat,
    bukan jumlah semuanya. Kegagalan satu cid tidak menggagalkan yang lain --
    hasilnya cuma dianggap tidak diketahui, sama seperti sebelum ada index ini.
    """
    with _CASHLINE_ID_MEMO_LOCK:
        out = {c: _CASHLINE_ID_MEMO[c] for c in cids if c in _CASHLINE_ID_MEMO}
        todo = [c for c in cids if c not in _CASHLINE_ID_MEMO]
    if not todo:
        return out

    def _one(cid):
        try:
            row = data_dwh.fetch_bundle(cid).get("cashline") or {}
        except Exception:  # noqa: BLE001 — DWH down must not break Statistics
            return cid, None
        return cid, {
            "agent_id": (row.get("agent_id") or "").strip() or None,
            "submit_time": (row.get("submit_time") or "").strip() or None,
        }

    with ThreadPoolExecutor(max_workers=_CASHLINE_FALLBACK_WORKERS) as pool:
        for cid, entry in pool.map(_one, todo):
            if entry is None:
                continue
            out[cid] = entry
            # HANYA hasil positif yang di-memo. agent_id untuk tiket yang sudah
            # selesai tidak akan berubah, jadi aman disimpan selamanya. Sebaliknya
            # hasil KOSONG tidak boleh di-memo: itu bisa berarti DWH sedang error
            # atau barisnya belum masuk, dan kalau dikunci di sini tiket tersebut
            # akan macet "(Tidak diketahui)" sampai proses di-restart.
            if entry["agent_id"]:
                with _CASHLINE_ID_MEMO_LOCK:
                    _CASHLINE_ID_MEMO[cid] = entry
    return out


def cashline_agent_index(db: Session) -> dict:
    """``{cid: {"agent_id": str|None, "submit_time": str|None}}`` untuk SEMUA result.

    ``cid`` = prefix sebelum ``_`` pada source file pertama (sama dengan
    ``_customer_id()`` di compliance/stats_aggregate.py). Satu query SQL untuk
    seluruh dataset; DWH hanya disentuh untuk sisa cid yang snapshot-nya belum
    memuat agent_id (lihat catatan di atas).
    """
    latest = (
        db.query(
            func.split_part(Result.source_files[0].astext, "_", 1).label("cid"),
            ResultData.result_json["reference_data"]["cashline"]["agent_id"]
            .astext.label("agent_id"),
            ResultData.result_json["reference_data"]["cashline"]["submit_time"]
            .astext.label("submit_time"),
        )
        .join(ResultData, ResultData.result_id == Result.id)
        .distinct(Result.id)
        .order_by(Result.id, desc(ResultData.created_at))
        .all()
    )

    index: dict = {}
    for cid, agent_id, submit_time in latest:
        key = (cid or "").strip()
        if not key:
            continue
        index[key] = {
            "agent_id": (agent_id or "").strip() or None,
            "submit_time": (submit_time or "").strip() or None,
        }

    missing = [c for c, v in index.items() if not v["agent_id"]]
    if missing:
        for cid, entry in _cashline_ids_from_dwh(missing).items():
            index[cid] = entry
    return index


def customer_ids_for_agent_ids(db: Session, agent_ids) -> list[str]:
    """Return the customer/ticket ids (cid) handled by the given agent ids
    (matched case-insensitively, trimmed). Empty input => empty list.

    ``cid`` equals the customer-id prefix of a result's source filenames, so the
    returned ids can scope ``list_results(customer_ids=...)``. Dulu dibaca dari
    ``tms_cashline``; sekarang dari ``cashline_agent_index()`` -- tabel itu sudah
    tidak terisi lagi, jadi query lama selalu mengembalikan list kosong dan bikin
    Team Leader / Area Manager tidak melihat tiket apa pun.
    """
    ids = {str(a).strip().casefold() for a in (agent_ids or []) if str(a).strip()}
    if not ids:
        return []
    return [
        cid
        for cid, entry in cashline_agent_index(db).items()
        if (entry["agent_id"] or "").casefold() in ids
    ]


def _stats_signature(db: Session) -> str:
    """A cheap fingerprint of everything the Statistics aggregation depends on.

    Captures result count + latest upload/completion time, evaluation (result_data)
    count + latest time, appeal count + latest review time (approved appeals change
    error counts), and the active sales-database file (drives agent name / TL / AM).
    When this string is unchanged, the cached snapshot is still valid — so the
    expensive full scan only re-runs when the underlying data actually changed.
    """
    res_count, res_up, res_done = db.query(
        func.count(Result.id), func.max(Result.uploaded_at), func.max(Result.completed_at)
    ).one()
    rd_count, rd_max = db.query(
        func.count(ResultData.id), func.max(ResultData.created_at)
    ).one()
    ap_count, ap_rev = db.query(
        func.count(ErrorCodeAppeal.id), func.max(ErrorCodeAppeal.reviewed_at)
    ).one()
    sales = get_active_sales_database(db)
    sales_key = sales.object_path if sales else ""
    # Bump when the snapshot PAYLOAD SHAPE or COMPUTED VALUES change so old cached
    # rows auto-invalidate even if the underlying data is unchanged.
    # v2: added ai_status_breakdown.
    # v3: campaign_monthly reshaped to a flat per-campaign Risk Base breakdown.
    # v4: campaign_monthly restored the per-month breakdown (Risk Base kept).
    # v5: Risk Base tally counts one highest risk base per ticket (H>M>L>N>O).
    # v6: added overview_by_campaign / agents_by_campaign for the Overview campaign filter.
    # v7: agents[] carry team_leader / area_manager (Performa Sales mapping columns).
    # v8: campaign_monthly.error_rate = Total Risk (H+M+L) / submissions, not the
    #     AI-Status FAIL count; hierarchy nodes (agent/TL/AM/all_telesales) gained
    #     approve + risk_high/medium/low + total_risk.
    # v9: hierarchy error_rate reverted to reject-based (FAIL / submissions) —
    #     Total Risk / Submission is the Performa Campaign definition ONLY. The
    #     Risk Base columns stay as context.
    # v10: hierarchy nodes also carry risk_system (O) + risk_new (N).
    version = "v10"
    return (
        f"{version}|{res_count}|{res_up}|{res_done}|{rd_count}|{rd_max}"
        f"|{ap_count}|{ap_rev}|{sales_key}"
    )


def get_or_build_stats_snapshot(db: Session, force: bool = False) -> dict:
    """Return the Statistics dashboard payload, recomputing it only when the
    underlying data changes (auto-invalidating cache).

    Each call computes a cheap ``_stats_signature``; if it matches the signature
    stored in the latest cached snapshot, that snapshot is returned as-is.
    Otherwise the payload is recomputed via
    ``compliance.stats_aggregate.compute_stats_snapshot`` (imported lazily to avoid
    an import cycle) and cached. ``force=True`` always recomputes.
    """
    sig = _stats_signature(db)
    latest = db.query(StatsSnapshot).order_by(desc(StatsSnapshot.id)).first()
    if (
        latest is not None
        and not force
        and isinstance(latest.payload, dict)
        and latest.payload.get("_signature") == sig
    ):
        return latest.payload

    from compliance.stats_aggregate import compute_stats_snapshot

    payload = compute_stats_snapshot(db)
    payload["_signature"] = sig

    # Keep one row per WIB day (overwrite today's on change; new day => new row).
    today = _wib_today_str()
    row = db.query(StatsSnapshot).filter(StatsSnapshot.snapshot_date == today).first()
    if row is None:
        row = StatsSnapshot(snapshot_date=today, payload=payload)
        db.add(row)
    else:
        row.payload = payload
        row.computed_at = datetime.utcnow()
    try:
        db.commit()
    except Exception:
        # A concurrent request may have inserted today's row; fall back to what is
        # now stored rather than failing the request.
        db.rollback()
        row = db.query(StatsSnapshot).filter(StatsSnapshot.snapshot_date == today).first()
        if row is not None and isinstance(row.payload, dict):
            return row.payload
    return payload


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------

def upsert_campaign(
    db: Session,
    name: str,
    prompt_text: str,
    scorecard_text: str,
    kb_text: str,
    prompt_filename: str = None,
    scorecard_filename: str = None,
    kb_filename: str = None,
) -> Campaign:
    campaign = db.query(Campaign).filter(Campaign.name == name).first()
    if campaign:
        campaign.prompt_text = prompt_text
        campaign.scorecard_text = scorecard_text
        campaign.kb_text = kb_text
        campaign.prompt_filename = prompt_filename
        campaign.scorecard_filename = scorecard_filename
        campaign.kb_filename = kb_filename
        campaign.is_active = True
    else:
        campaign = Campaign(
            name=name,
            prompt_text=prompt_text,
            scorecard_text=scorecard_text,
            kb_text=kb_text,
            prompt_filename=prompt_filename,
            scorecard_filename=scorecard_filename,
            kb_filename=kb_filename,
            is_active=True,
        )
        db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


def get_campaign_by_name(db: Session, name: str) -> Optional[Campaign]:
    return db.query(Campaign).filter(Campaign.name == name).first()


def delete_campaign(db: Session, name: str) -> bool:
    """Delete a campaign by name. Returns True if a row was removed, else False.

    ``results`` store ``campaign`` as a plain string (no FK), so deleting a
    campaign does not affect existing results.
    """
    campaign = db.query(Campaign).filter(Campaign.name == name).first()
    if not campaign:
        return False
    db.delete(campaign)
    db.commit()
    return True


def delete_results_by_ticket_id(db: Session, ticket_id: str) -> int:
    """Delete ALL Result rows for a ticket and return how many were removed.

    The ticket id is the prefix before the first ``_`` of the first source
    filename (see stats._customer_id_from_files). Dependent rows in
    ``result_data``, ``documents``, ``qc_status_requests`` and
    ``error_code_appeals`` are removed automatically via ON DELETE CASCADE.
    Returns 0 when no matching Result exists.
    """
    rows = (
        db.query(Result)
        .filter(func.split_part(Result.source_files[0].astext, "_", 1) == ticket_id)
        .all()
    )
    count = len(rows)
    for row in rows:
        db.delete(row)
    if count:
        db.commit()
    return count


def get_active_campaign(db: Session, name: str) -> Optional[Campaign]:
    return (
        db.query(Campaign)
        .filter(Campaign.name == name, Campaign.is_active == True)
        .first()
    )


def get_active_campaign_ci(db: Session, name: str) -> Optional[Campaign]:
    """Active campaign matched **case-insensitively** by name (trimmed both sides).

    Used by the webhook to map an external ``product`` (e.g. ``"cashline"``) to its
    campaign config (e.g. ``"Cashline"``). Returns ``None`` if no active campaign
    matches.
    """
    key = str(name or "").strip().lower()
    if not key:
        return None
    return (
        db.query(Campaign)
        .filter(func.lower(func.trim(Campaign.name)) == key, Campaign.is_active == True)
        .first()
    )


def list_campaigns(db: Session) -> list[Campaign]:
    return db.query(Campaign).order_by(desc(Campaign.updated_at)).all()


# ---------------------------------------------------------------------------
# Sales database (Upload Database Sales)
# ---------------------------------------------------------------------------
def create_sales_database(
    db: Session,
    filename: str,
    object_path: str,
    mime_type: str = None,
    uploaded_by_username: str = None,
    uploaded_by_role: str = None,
) -> SalesDatabase:
    """Record a newly-uploaded sales database and make it the only active one.

    Every previously-active row is flipped to inactive first, so exactly one
    sales database (the newest) is active at any time.
    """
    db.query(SalesDatabase).filter(SalesDatabase.is_active == True).update(
        {SalesDatabase.is_active: False}
    )
    row = SalesDatabase(
        filename=filename,
        object_path=object_path,
        mime_type=mime_type,
        is_active=True,
        uploaded_by_username=uploaded_by_username,
        uploaded_by_role=uploaded_by_role,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_active_sales_database(db: Session) -> Optional[SalesDatabase]:
    """The single active sales database (newest active upload), or None."""
    return (
        db.query(SalesDatabase)
        .filter(SalesDatabase.is_active == True)
        .order_by(desc(SalesDatabase.created_at))
        .first()
    )


def list_sales_databases(db: Session) -> list[SalesDatabase]:
    return db.query(SalesDatabase).order_by(desc(SalesDatabase.created_at)).all()


def create_qc_database(
    db: Session,
    filename: str,
    object_path: str,
    mime_type: str = None,
    uploaded_by_username: str = None,
    uploaded_by_role: str = None,
) -> QcDatabase:
    """Record a newly-uploaded QC database and make it the only active one (mirrors
    ``create_sales_database``)."""
    db.query(QcDatabase).filter(QcDatabase.is_active == True).update(  # noqa: E712
        {QcDatabase.is_active: False}
    )
    row = QcDatabase(
        filename=filename,
        object_path=object_path,
        mime_type=mime_type,
        is_active=True,
        uploaded_by_username=uploaded_by_username,
        uploaded_by_role=uploaded_by_role,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_active_qc_database(db: Session) -> Optional[QcDatabase]:
    """The single active QC database (newest active upload), or None."""
    return (
        db.query(QcDatabase)
        .filter(QcDatabase.is_active == True)  # noqa: E712
        .order_by(desc(QcDatabase.created_at))
        .first()
    )


def list_qc_databases(db: Session) -> list[QcDatabase]:
    return db.query(QcDatabase).order_by(desc(QcDatabase.created_at)).all()


# ---------------------------------------------------------------------------
# Documents (Upload Document + OCR)
# ---------------------------------------------------------------------------
def create_document(
    db: Session,
    result_id: str,
    doc_type: str,
    filename: str,
    object_path: str,
    mime_type: str,
) -> Document:
    doc = Document(
        result_id=uuid.UUID(str(result_id)),
        doc_type=doc_type,
        filename=filename,
        object_path=object_path,
        mime_type=mime_type,
        status="pending",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def list_documents(db: Session, result_id: str) -> list[Document]:
    return (
        db.query(Document)
        .filter(Document.result_id == uuid.UUID(str(result_id)))
        .order_by(Document.id)
        .all()
    )


def get_document(db: Session, document_id: int) -> Optional[Document]:
    return db.query(Document).filter(Document.id == int(document_id)).first()


def result_has_documents(db: Session, result_id: str) -> bool:
    return (
        db.query(Document.id)
        .filter(Document.result_id == uuid.UUID(str(result_id)))
        .first()
        is not None
    )


def result_ids_with_documents(db: Session, result_ids: list[str]) -> set[str]:
    """Return the subset of ``result_ids`` that have at least one document.

    Single query (one IN clause) to avoid N+1 when listing the results page.
    """
    if not result_ids:
        return set()
    uuids = [uuid.UUID(str(r)) for r in result_ids]
    rows = (
        db.query(Document.result_id)
        .filter(Document.result_id.in_(uuids))
        .distinct()
        .all()
    )
    return {str(row[0]) for row in rows}


def document_upload_times(db: Session, result_ids: list[str]) -> dict[str, datetime]:
    """Return ``{result_id: latest document created_at}`` for the given results.

    Single grouped query to avoid N+1 when listing the results page.
    """
    if not result_ids:
        return {}
    uuids = [uuid.UUID(str(r)) for r in result_ids]
    rows = (
        db.query(Document.result_id, func.max(Document.created_at))
        .filter(Document.result_id.in_(uuids))
        .group_by(Document.result_id)
        .all()
    )
    return {str(row[0]): row[1] for row in rows}


def update_document_status(db: Session, document_id: int, status: str) -> Optional[Document]:
    doc = get_document(db, document_id)
    if not doc:
        return None
    doc.status = status
    db.commit()
    db.refresh(doc)
    return doc


def set_document_result(db: Session, document_id: int, ocr_json: dict) -> Optional[Document]:
    doc = get_document(db, document_id)
    if not doc:
        return None
    doc.ocr_json = ocr_json
    doc.status = "done"
    doc.error_message = None
    doc.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(doc)
    return doc


def set_document_failed(db: Session, document_id: int, error_message: str) -> Optional[Document]:
    doc = get_document(db, document_id)
    if not doc:
        return None
    doc.status = "failed"
    doc.error_message = error_message
    doc.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(doc)
    return doc


# ---------------------------------------------------------------------------
# Reference data (CASHLINE / CARD HOLDER) — sumber: DWH API (Aplikasi A) via
# services/data_dwh.py (API/V1 :8000), bukan lagi DB/CSV.
#
# CATATAN: `db: Session` sengaja dipertahankan di semua fungsi walau tak dipakai,
# supaya pemanggil (reference_data.py, routes) tidak perlu diubah. Nilai balik
# tetap dict ber-key nama header/kolom asli (mis. "nominal-transfer",
# "CUST_MOM_NAME"), identik dengan bentuk lama dari CSV/DB.
# ---------------------------------------------------------------------------
def get_campaign_bundle(db: Session, result_id: str) -> dict:
    """``{"cashline", "customer"}`` untuk ``result_id`` dari DWH API (di-cache).

    Satu call memuat cashline + customer sekaligus; customer sudah dicocokkan
    oleh Aplikasi A via ``no-ktpkitas`` dari cashline (bukan lagi by
    CUST_LOCAL_NAME / cust_name). ``db`` diabaikan.
    """
    return data_dwh.fetch_bundle(result_id)


def get_tms_cashline_by_result_id(db: Session, result_id: str) -> Optional[dict]:
    """Baris CASHLINE (dict ber-key header) untuk ``result_id``, atau ``None``.

    Sumber: DWH API (dashboard.campaign_cashline_ntb). ``db`` diabaikan.
    """
    return get_campaign_bundle(db, result_id).get("cashline")


def get_ascend_custp_by_result_id(db: Session, result_id: str) -> Optional[dict]:
    """Baris CARD HOLDER (dict ber-key header) untuk ``result_id``, atau ``None``.

    Sumber: DWH API (dashboard.current_cc_scmcustp), dicocokkan oleh Aplikasi A by
    ``no-ktpkitas``. MENGGANTIKAN ``get_ascend_custp_by_local_name`` lama yang
    mencari by cust_name. ``db`` diabaikan.
    """
    return get_campaign_bundle(db, result_id).get("customer")


# Change flag -> document types allowed for upload. KK / cover_buku_tabungan are
# intentionally unmapped (KK/nama-ibu-kandung deferred: no source column yet; cover
# buku tabungan has no triggering change), so they are never uploadable.
CHANGE_DOC_TYPES = {
    "kantor": ["ktp"],
    "rumah": ["ktp"],
    "nik": ["ktp"],
    "npwp": ["npwp"],
}

# Sub-kolom grup "*-new" (kunci = nama HEADER asli seperti dibalas API,
# bukan atribut ORM yang ter-sanitasi).
_KANTOR_NEW_COLS = [
    "alamat-kantor-1-new", "alamat-kantor-2-new", "kantor-rt-new", "kantor-rw-new",
    "kantor-kelurahan-new", "kantor-kecamatan-new", "kantor-kabupatenkota-new",
    "kantor-provinsi-new", "kantor-kode-pos-new",
]
_RUMAH_NEW_COLS = [
    "alamat-rumah-1-new", "alamat-rumah-2-new", "rumah-rt-new", "rumah-rw-new",
    "rumah-kelurahan-new", "rumah-kecamatan-new", "rumah-kabupatenkota-new",
    "rumah-provinsi-new", "rumah-kode-pos-new",
]


def allowed_doc_types_from_flags(flags: dict) -> list[str]:
    """Ordered list of document types allowed to upload, given the active change
    flags (see ``get_tms_cashline_change_flags``). Union across all active changes."""
    order = ["ktp", "npwp", "kk", "cover_buku_tabungan"]
    allowed = set()
    for k, doctypes in CHANGE_DOC_TYPES.items():
        if flags.get(k):
            allowed.update(doctypes)
    return [d for d in order if d in allowed]


def compute_tms_change_flags(cashline_row: Optional[dict]) -> dict:
    """[NEW] Hitung change flags (kantor/rumah/npwp/nik) dari 1 dict cashline
    yang SUDAH ADA (mis. result_json["reference_data"]["cashline"], sudah
    di-embed di final_json sejak evaluasi LLM -- lihat
    worker/tasks/process_transcript.py) -- MURNI LOKAL, TANPA HTTP ke App A
    sama sekali.

    Dipakai _build_items() (api/routers/stats.py) untuk result yang SUDAH
    punya reference_data tersimpan di result_json, supaya tidak perlu
    panggil get_tms_cashline_change_flags() (HTTP) lagi tiap ResultsView
    dibuka. get_tms_cashline_change_flags() (di atas, HTTP per-id) TETAP
    dipakai sebagai FALLBACK untuk result LAMA yang diproses SEBELUM
    reference_data mulai disisipkan ke result_json.

    Logic PERSIS SAMA dengan yang dipakai get_tms_cashline_change_flags()
    di atas (kolom _KANTOR_NEW_COLS/_RUMAH_NEW_COLS/no-npwp-new/nik-new
    yang sama) -- cuma menerima dict yang SUDAH ADA, bukan fetch sendiri.
    """
    if not cashline_row:
        return {}

    def _filled(row: dict, cols: list[str]) -> bool:
        return any(str(row.get(c) or "").strip() for c in cols)

    return {
        "kantor": _filled(cashline_row, _KANTOR_NEW_COLS),
        "rumah": _filled(cashline_row, _RUMAH_NEW_COLS),
        "npwp": bool(str(cashline_row.get("no-npwp-new") or "").strip()),
        "nik": bool(str(cashline_row.get("nik-new") or "").strip()),
    }


def get_tms_cashline_change_flags(db: Session, result_ids: list[str]) -> dict[str, dict]:
    """Map ``cid -> {"kantor","rumah","npwp","nik": bool}`` dari kolom ``*-new``
    cashline yang TERISI (ada nilai baru = ada perubahan data), untuk gating tombol
    Upload Document. Sumber: DWH API per ``result_id`` (tidak ada endpoint batch,
    jadi fetch per id; hasil di-cache singkat oleh data_dwh). ``db`` diabaikan.
    """
    ids = [str(x).strip() for x in result_ids if x]
    if not ids:
        return {}

    def _filled(row: dict, cols: list[str]) -> bool:
        return any(str(row.get(c) or "").strip() for c in cols)

    out: dict[str, dict] = {}
    for cid in ids:
        if cid in out:  # dedup, mirroring get_tms_cashline_by_result_id (first wins)
            continue
        cashline = get_tms_cashline_by_result_id(db, cid)
        if not cashline:
            continue
        out[cid] = {
            "kantor": _filled(cashline, _KANTOR_NEW_COLS),
            "rumah": _filled(cashline, _RUMAH_NEW_COLS),
            "npwp": bool(str(cashline.get("no-npwp-new") or "").strip()),
            "nik": bool(str(cashline.get("nik-new") or "").strip()),
        }
    return out


# ---------------------------------------------------------------------------
# QC status-change requests (QC proposes, SPQ Head approves/rejects)
# ---------------------------------------------------------------------------
def get_qc_status_request(db: Session, result_id: str) -> Optional[QcStatusRequest]:
    return (
        db.query(QcStatusRequest)
        .filter(QcStatusRequest.result_id == uuid.UUID(str(result_id)))
        .first()
    )


def upsert_qc_status_request(
    db: Session,
    result_id: str,
    requested_status: str,
    reason: str,
    username: str = None,
    role: str = None,
) -> QcStatusRequest:
    """Create or replace the QC request for a result, resetting it to pending."""
    req = get_qc_status_request(db, result_id)
    if req is None:
        req = QcStatusRequest(result_id=uuid.UUID(str(result_id)))
        db.add(req)
    req.requested_status = requested_status
    req.reason = reason
    req.requested_by_username = username
    req.requested_by_role = role
    req.requested_at = datetime.utcnow()
    req.approval_status = "pending"
    req.reviewed_by_username = None
    req.reviewed_at = None
    db.commit()
    db.refresh(req)
    return req


def review_qc_status_request(
    db: Session,
    result_id: str,
    decision: str,
    reviewer_username: str = None,
    comment: str = None,
) -> Optional[QcStatusRequest]:
    """Set the request's approval to ``approved``/``rejected`` (decision is reversible).
    ``comment`` is the reviewer's note (this tier); mandatory on reject, else optional."""
    req = get_qc_status_request(db, result_id)
    if req is None:
        return None
    req.approval_status = "approved" if decision == "approve" else "rejected"
    req.reviewed_by_username = reviewer_username
    req.reviewed_at = datetime.utcnow()
    req.review_comment = comment
    db.commit()
    db.refresh(req)
    return req


def qc_status_requests_for(db: Session, result_ids: list[str]) -> dict[str, QcStatusRequest]:
    """Return ``{result_id: QcStatusRequest}`` for the given results.

    Single ``IN`` query to avoid N+1 when listing the results page.
    """
    if not result_ids:
        return {}
    uuids = [uuid.UUID(str(r)) for r in result_ids]
    rows = (
        db.query(QcStatusRequest)
        .filter(QcStatusRequest.result_id.in_(uuids))
        .all()
    )
    return {str(r.result_id): r for r in rows}


# Team Leader QC decision -> stored tl_qc_status. 'approve'/'reject' are FINAL (no
# SPQ Head); 'escalate' forwards to SPQ Head for the final call.
_TL_DECISION = {"approve": "approved", "reject": "rejected", "escalate": "escalated"}


def tl_review_qc_status_request(
    db: Session,
    result_id: str,
    decision: str,
    reviewer_username: str = None,
    comment: str = None,
) -> Optional[QcStatusRequest]:
    """Team Leader QC check of a QC AI-status request: finalize (approve/reject) or
    escalate to SPQ Head (reversible). ``comment`` is TL QC's note (any decision)."""
    req = get_qc_status_request(db, result_id)
    if req is None:
        return None
    req.tl_qc_status = _TL_DECISION.get(decision, "rejected")
    req.tl_qc_username = reviewer_username
    req.tl_qc_reviewed_at = datetime.utcnow()
    req.tl_qc_comment = comment
    db.commit()
    db.refresh(req)
    return req


# ---------------------------------------------------------------------------
# Error Code appeals ("banding": QC appeals a single error code, SPQ Head reviews)
# ---------------------------------------------------------------------------
def create_error_code_appeal(
    db: Session,
    result_id: str,
    error_code: str,
    item_code: str,
    ai_sumber: str = None,
    ai_risk_base: str = None,
    ai_details_error: str = None,
    ai_reason: str = None,
    ai_evidence: str = None,
    ai_ticket_id: str = None,
    qc_reason: str = "",
    qc_evidence: str = None,
    qc_ticket_id: str = None,
    qc_reference_value: str = None,
    qc_extracted_value: str = None,
    qc_new_error_code: str = None,
    qc_risk_base: str = None,
    appeal_kind: str = "remove",
    add_source: str = None,
    username: str = None,
) -> ErrorCodeAppeal:
    """Insert a new (pending) appeal row. Append-only, so repeated appeals on the
    same error code accumulate as history."""
    appeal = ErrorCodeAppeal(
        result_id=uuid.UUID(str(result_id)),
        error_code=error_code,
        item_code=item_code,
        ai_sumber=ai_sumber,
        ai_risk_base=ai_risk_base,
        ai_details_error=ai_details_error,
        ai_reason=ai_reason,
        ai_evidence=ai_evidence,
        ai_ticket_id=ai_ticket_id,
        qc_reason=qc_reason,
        qc_evidence=qc_evidence,
        qc_ticket_id=qc_ticket_id,
        qc_reference_value=qc_reference_value,
        qc_extracted_value=qc_extracted_value,
        qc_new_error_code=qc_new_error_code,
        qc_risk_base=qc_risk_base,
        appeal_kind=(appeal_kind or "remove"),
        add_source=add_source,
        requested_by_username=username,
        requested_at=datetime.utcnow(),
        approval_status="pending",
    )
    db.add(appeal)
    db.commit()
    db.refresh(appeal)
    return appeal


def get_error_code_appeal(db: Session, appeal_id: int) -> Optional[ErrorCodeAppeal]:
    return (
        db.query(ErrorCodeAppeal)
        .filter(ErrorCodeAppeal.id == int(appeal_id))
        .first()
    )


def error_code_appeals_for_result(db: Session, result_id: str) -> list[ErrorCodeAppeal]:
    """All appeals for a result, oldest first (history order)."""
    return (
        db.query(ErrorCodeAppeal)
        .filter(ErrorCodeAppeal.result_id == uuid.UUID(str(result_id)))
        .order_by(ErrorCodeAppeal.requested_at.asc(), ErrorCodeAppeal.id.asc())
        .all()
    )


def error_code_appeals_for_results(
    db: Session, result_ids: list[str]
) -> dict[str, list[ErrorCodeAppeal]]:
    """Return ``{result_id: [appeals oldest-first]}`` for the given results.

    Single ``IN`` query to avoid N+1 when listing the results page / export.
    """
    if not result_ids:
        return {}
    uuids = [uuid.UUID(str(r)) for r in result_ids]
    rows = (
        db.query(ErrorCodeAppeal)
        .filter(ErrorCodeAppeal.result_id.in_(uuids))
        .order_by(ErrorCodeAppeal.requested_at.asc(), ErrorCodeAppeal.id.asc())
        .all()
    )
    out: dict[str, list[ErrorCodeAppeal]] = {}
    for r in rows:
        out.setdefault(str(r.result_id), []).append(r)
    return out


def review_error_code_appeal(
    db: Session,
    appeal_id: int,
    decision: str,
    reviewer_username: str = None,
    comment: str = None,
) -> Optional[ErrorCodeAppeal]:
    """Set an appeal's SPQ-Head approval to ``approved``/``rejected`` (reversible).
    ``comment`` is the reviewer's note (this tier); mandatory on reject, else optional."""
    appeal = get_error_code_appeal(db, appeal_id)
    if appeal is None:
        return None
    appeal.approval_status = "approved" if decision == "approve" else "rejected"
    appeal.reviewed_by_username = reviewer_username
    appeal.reviewed_at = datetime.utcnow()
    appeal.review_comment = comment
    db.commit()
    db.refresh(appeal)
    return appeal


def tl_review_error_code_appeal(
    db: Session,
    appeal_id: int,
    decision: str,
    reviewer_username: str = None,
    comment: str = None,
) -> Optional[ErrorCodeAppeal]:
    """Team Leader QC check of a banding appeal: finalize (approve/reject) or escalate
    to SPQ Head (reversible). 'approve'/'reject' are final; 'escalate' -> SPQ Head.
    ``comment`` is TL QC's note (any decision)."""
    appeal = get_error_code_appeal(db, appeal_id)
    if appeal is None:
        return None
    appeal.tl_qc_status = _TL_DECISION.get(decision, "rejected")
    appeal.tl_qc_username = reviewer_username
    appeal.tl_qc_reviewed_at = datetime.utcnow()
    appeal.tl_qc_comment = comment
    db.commit()
    db.refresh(appeal)
    return appeal


# ---------------------------------------------------------------------------
# QC ticket assignments (Team Leader QC assigns a ticket to a QC; 1 ticket -> 1 QC)
# ---------------------------------------------------------------------------

def assign_ticket_to_qc(
    db: Session, ticket_id: str, qc_username: str, assigned_by_username: str = None
) -> QcAssignment:
    """Assign ``ticket_id`` to ``qc_username`` (upsert — reassigns if it exists)."""
    tid = (ticket_id or "").strip()
    row = db.query(QcAssignment).filter(QcAssignment.ticket_id == tid).first()
    if row is None:
        row = QcAssignment(ticket_id=tid)
        db.add(row)
    row.qc_username = (qc_username or "").strip()
    row.assigned_by_username = assigned_by_username
    row.assigned_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def unassign_ticket(db: Session, ticket_id: str) -> bool:
    """Remove any QC assignment for ``ticket_id``. Returns True if one was removed."""
    tid = (ticket_id or "").strip()
    row = db.query(QcAssignment).filter(QcAssignment.ticket_id == tid).first()
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def list_qc_assignments(db: Session) -> list[QcAssignment]:
    """All QC ticket assignments, newest first."""
    return db.query(QcAssignment).order_by(QcAssignment.assigned_at.desc()).all()


def assigned_ticket_ids_for_qc(db: Session, qc_username: str) -> list[str]:
    """Ticket ids assigned to ``qc_username`` (case-insensitive, trimmed)."""
    key = (qc_username or "").strip().casefold()
    if not key:
        return []
    rows = (
        db.query(QcAssignment.ticket_id)
        .filter(func.lower(func.trim(QcAssignment.qc_username)) == key)
        .all()
    )
    return [r[0] for r in rows if r[0]]


def qc_side_filter_options(db: Session) -> dict:
    """Dropdown options for the Team Leader QC Results filter: every QC and every
    QC Support account. Returns ``{"qc_users": [...], "qc_support_users": [...]}``
    where each entry is ``{"username", "name"}`` (username is the NIP the list
    endpoint filters on; name is display-only), sorted by name."""
    def _rows(role):
        users = db.query(User).filter(User.role == role, User.is_active.is_(True)).all()
        rows = [
            {"username": (u.username or "").strip(), "name": (u.name or u.username or "").strip()}
            for u in users
            if (u.username or "").strip()
        ]
        return sorted(rows, key=lambda x: x["name"].casefold())
    return {"qc_users": _rows("qc"), "qc_support_users": _rows("qc_support")}


def assignment_map_for_tickets(db: Session, ticket_ids: list[str]) -> dict:
    """Return ``{ticket_id: (qc_username, assigned_at)}`` for the given ticket ids."""
    ids = [str(t).strip() for t in (ticket_ids or []) if str(t).strip()]
    if not ids:
        return {}
    rows = db.query(QcAssignment).filter(QcAssignment.ticket_id.in_(ids)).all()
    return {r.ticket_id: (r.qc_username, r.assigned_at) for r in rows}


# ---------------------------------------------------------------------------
# QC manual checks (per-ticket "sudah dicek manual oleh QC"; append-only trail)
# ---------------------------------------------------------------------------

def create_qc_manual_check(
    db: Session, result_id: str, username: str, role: str = None, note: str = None
) -> QcManualCheck:
    """Append a manual-check approval event for ``result_id``.

    Never updates in place — re-approving inserts another row so the audit trail
    keeps every check. The newest row is the authoritative state.
    """
    row = QcManualCheck(
        result_id=result_id,
        checked_by_username=(username or "").strip(),
        checked_by_role=role,
        note=(note or "").strip() or None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def qc_manual_checks_for_results(db: Session, result_ids: list[str]) -> dict:
    """Return ``{result_id: latest QcManualCheck}`` for the given result ids.

    Batched to avoid an N+1 in the Results list. Ordered oldest-first so the last
    write per key wins, matching "latest row is authoritative".
    """
    ids = [str(r).strip() for r in (result_ids or []) if str(r).strip()]
    if not ids:
        return {}
    rows = (
        db.query(QcManualCheck)
        .filter(QcManualCheck.result_id.in_(ids))
        .order_by(QcManualCheck.id.asc())
        .all()
    )
    return {str(r.result_id): r for r in rows}


def qc_manual_check_history(db: Session, result_id: str) -> list[QcManualCheck]:
    """Full audit trail for one ticket, oldest first."""
    return (
        db.query(QcManualCheck)
        .filter(QcManualCheck.result_id == result_id)
        .order_by(QcManualCheck.id.asc())
        .all()
    )


def qc_performance_rows(db: Session) -> list[dict]:
    """Per-QC assignment/approval tally for the QC table in Hierarki Error Rate.

    Returns ``[{qc_username, name, assigned, approved, approve_rate}]``.
    ``approved`` counts a QC's manual checks that land on a ticket CURRENTLY
    assigned to them, so a reassigned ticket cannot inflate the old owner's
    count. ``approve_rate`` = approved / assigned (%).

    Computed live rather than from the stats snapshot: the snapshot signature
    tracks results/appeals only, so it would not invalidate when a QC approves
    a ticket and this table would read stale.
    """
    # qc_username (casefold) -> {ticket_id}
    assigned: dict = defaultdict(set)
    for row in db.query(QcAssignment).all():
        u = (row.qc_username or "").strip()
        if u and row.ticket_id:
            assigned[u.casefold()].add(row.ticket_id.strip())

    checks = db.query(QcManualCheck).all()
    # Map only the results that actually carry a check -> their ticket id.
    checked_result_ids = {str(c.result_id) for c in checks}
    ticket_by_result: dict = {}
    if checked_result_ids:
        for r in db.query(Result.id, Result.source_files).filter(
            Result.id.in_(list(checked_result_ids))
        ).all():
            sf = r.source_files or []
            if sf and isinstance(sf[0], str) and sf[0]:
                ticket_by_result[str(r.id)] = sf[0].split("_", 1)[0]

    approved: dict = defaultdict(set)
    for c in checks:
        u = (c.checked_by_username or "").strip().casefold()
        tid = ticket_by_result.get(str(c.result_id))
        if u and tid and tid in assigned.get(u, ()):
            approved[u].add(tid)

    # Every QC account appears, including ones with nothing assigned yet.
    names = {
        (u.username or "").strip().casefold(): (u.name or u.username)
        for u in db.query(User).filter(User.role == "qc").all()
    }
    rows = []
    for key in set(names) | set(assigned):
        n_assigned = len(assigned.get(key, ()))
        n_approved = len(approved.get(key, ()))
        rows.append({
            "qc_username": key,
            "name": names.get(key) or key,
            "assigned": n_assigned,
            "approved": n_approved,
            "approve_rate": round(n_approved / n_assigned * 100, 1) if n_assigned else 0.0,
        })
    rows.sort(key=lambda x: (-x["assigned"], x["name"].casefold()))
    return rows


def qc_username_for_ticket(db: Session, ticket_id: str) -> Optional[str]:
    """The QC assigned to ``ticket_id``, or None."""
    tid = (ticket_id or "").strip()
    if not tid:
        return None
    row = db.query(QcAssignment).filter(QcAssignment.ticket_id == tid).first()
    return row.qc_username if row else None


def latest_appeal_for_row(
    appeals: list[ErrorCodeAppeal], error_code: str, item_code: str
) -> Optional[ErrorCodeAppeal]:
    """Latest appeal matching an error-code row, or None. ``appeals`` is assumed
    to be ordered oldest-first (as returned by the fetch helpers above)."""
    match = [
        a for a in appeals
        if a.error_code == error_code and a.item_code == item_code
    ]
    return match[-1] if match else None