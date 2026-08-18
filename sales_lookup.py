"""Active sales-database (xlsx) lookups: agent name, join date, new-joiner flag,
and org hierarchy (Team Leader / Area Manager).

The active sales database (uploaded via "Upload Database Sales") is read from
MinIO once and parsed into a ``{USER ID -> {name, join_date, team_leader,
area_manager}}`` map, cached by the database's ``object_path`` (a new upload has a
new path, so the cache self-invalidates).

The org hierarchy is read from the sales-marketing sheet's ``NAMA TL`` (column I)
and ``NAMA AM`` (column K) columns — matched by header, falling back to the fixed
column positions I (index 8) and K (index 10) when the headers are absent. The
scoping NIPs come from ``NIP TL`` (column H), ``NIP AM`` (column J) and ``NIP BARU``
(column C).

"New joiner" = the gap between the cashline ``submit_time`` and the agent's
``JOIN POSISI (DD/MM/YYYY)`` (matched by ``agent_id`` == ``USER ID``) is
< ``NEW_JOINER_THRESHOLD_DAYS`` days.
"""
import io
from datetime import date, datetime
from typing import Optional

from openpyxl import load_workbook

from core_config import get_core_settings, get_minio
from db import crud

NEW_JOINER_THRESHOLD_DAYS = 18

# Cached {USER ID (casefold) -> {"name", "join_date"}}, keyed by the active
# database's MinIO object_path.
_cache = {"key": None, "map": {}}

# tms_cashline.submit_time strings look like "2026-06-17 15:24:53".
_SUBMIT_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d")
# JOIN POSISI cells are usually datetimes; when a string, they look like "31/10/2017".
_JOIN_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d")


def _norm(value) -> str:
    """Trimmed string for header/cell matching; an integer-valued float loses its
    ``.0`` so a numeric USER ID like ``801.0`` matches ``"801"`` ('' for None)."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


# Kolom roster jarang dikosongkan — yang tidak ada isinya diberi PLACEHOLDER:
# 12 baris padding di akhir sheet memakai USER ID "0" / NIP "00000000" / nama "-",
# dan agen berstatus MUTASI kehilangan atasannya dengan cara yang sama (NIP TL &
# NIP TLM "0", NAMA TL & NAMA AM "-"). Placeholder BUKAN identitas orang: dibiarkan
# apa adanya, NIP AM "0" + NAMA AM "-" menjadi satu opsi "-" di dropdown Semua AM
# (idem Semua TL) dan baris padding menjadi satu "agent" hantu.
_PLACEHOLDERS = {"-", "--", "n/a", "na", "none", "null", "#n/a", "#ref!"}


def _person(value) -> str:
    """``_norm``, tapi placeholder roster ("-", "0", "00000000", …) jadi ''."""
    s = _norm(value)
    if not s or s.casefold() in _PLACEHOLDERS:
        return ""
    return "" if set(s) == {"0"} else s


def _to_date(value, formats) -> "date | None":
    """Coerce a datetime/date/string cell into a ``date`` (None if unparseable)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# Sales-marketing hierarchy columns: matched by header first, else fixed position.
# Column I = "NAMA TL" (index 8, Team Leader), column K = "NAMA AM" (index 10, Area
# Manager). See the "Update Sales Telemarketing …xlsx" layout.
_TL_HEADER = "nama tl"
_AM_HEADER = "nama am"
_TL_FALLBACK_IDX = 8   # column I
_AM_FALLBACK_IDX = 10  # column K
# Sales-agent (Team Leader) login scoping: NIP TL = column H (idx 7), the NIP of the
# agent's team leader; DEDICATED = column F (idx 5), the campaign the agent handles.
_NIP_TL_HEADER = "nip tl"
_DEDICATED_HEADER = "dedicated"
_NIP_TL_FALLBACK_IDX = 7  # column H
_DEDICATED_FALLBACK_IDX = 5  # column F
# Area Manager login scoping: NIP AM = column J (idx 9), the NIP of the agent's area
# manager (one level above the Team Leader), paired with column K = NAMA AM. In the
# "Update Sales Telemarketing …" sheet column J is labelled "NIP TLM", so accept both
# that header and "NIP AM"; fall back to the fixed column J when neither is present.
_NIP_AM_HEADERS = ("nip am", "nip tlm")
_NIP_AM_FALLBACK_IDX = 9  # column J
# QC (agent) login scoping: NIP BARU = column C (idx 2), the agent's own NIP.
_NIP_BARU_HEADER = "nip baru"
_NIP_BARU_FALLBACK_IDX = 2  # column C


def active_sales_map(db) -> dict:
    """Return ``{USER ID (casefold) -> {"name", "join_date", "team_leader",
    "area_manager", "nip_tl", "nip_am", "dedicated", "nip_baru"}}`` from the active
    sales-database xlsx, or ``{}`` when there is none / it can't be read/parsed."""
    row = crud.get_active_sales_database(db)
    if row is None:
        return {}
    if _cache["key"] == row.object_path:
        return _cache["map"]

    mapping: dict = {}
    try:
        settings = get_core_settings()
        resp = get_minio().get_object(settings.minio_bucket_sales_database, row.object_path)
        try:
            data = resp.read()
        finally:
            resp.close()
            resp.release_conn()
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        rows = ws.iter_rows(values_only=True)
        header = next(rows, None)
        if header:
            norm = [_norm(h).casefold() for h in header]
            uid_i = next((i for i, h in enumerate(norm) if h in ("user id", "user_id", "userid")), None)
            name_i = next((i for i, h in enumerate(norm) if h == "name"), None)
            join_i = next((i for i, h in enumerate(norm) if h.startswith("join posisi")), None)
            # Team Leader / Area Manager: match by header, else fixed column I / K.
            tl_i = next((i for i, h in enumerate(norm) if h == _TL_HEADER), None)
            if tl_i is None and len(norm) > _TL_FALLBACK_IDX:
                tl_i = _TL_FALLBACK_IDX
            am_i = next((i for i, h in enumerate(norm) if h == _AM_HEADER), None)
            if am_i is None and len(norm) > _AM_FALLBACK_IDX:
                am_i = _AM_FALLBACK_IDX
            # NIP TL (col H) + DEDICATED (col F): match by header, else fixed column.
            niptl_i = next((i for i, h in enumerate(norm) if h == _NIP_TL_HEADER), None)
            if niptl_i is None and len(norm) > _NIP_TL_FALLBACK_IDX:
                niptl_i = _NIP_TL_FALLBACK_IDX
            ded_i = next((i for i, h in enumerate(norm) if h == _DEDICATED_HEADER), None)
            if ded_i is None and len(norm) > _DEDICATED_FALLBACK_IDX:
                ded_i = _DEDICATED_FALLBACK_IDX
            # NIP AM (col J, header "NIP TLM"/"NIP AM"): the agent's area manager NIP —
            # an area_manager login's username.
            nipam_i = next((i for i, h in enumerate(norm) if h in _NIP_AM_HEADERS), None)
            if nipam_i is None and len(norm) > _NIP_AM_FALLBACK_IDX:
                nipam_i = _NIP_AM_FALLBACK_IDX
            # NIP BARU (col C): the agent's own NIP — a qc login's username.
            nipbaru_i = next((i for i, h in enumerate(norm) if h == _NIP_BARU_HEADER), None)
            if nipbaru_i is None and len(norm) > _NIP_BARU_FALLBACK_IDX:
                nipbaru_i = _NIP_BARU_FALLBACK_IDX
            if uid_i is not None:
                for r in rows:
                    if not r or uid_i >= len(r):
                        continue
                    # Semua kolom identitas dibaca lewat _person(), bukan _norm():
                    # placeholder roster harus jadi kosong SEBELUM tersimpan, supaya
                    # tidak ada konsumen (dropdown filter, hierarki Statistics,
                    # scoping login) yang perlu tahu soal "-" dan "0".
                    uid = _person(r[uid_i])
                    if not uid:
                        continue  # baris padding "0" — bukan agent
                    name = _person(r[name_i]) if (name_i is not None and name_i < len(r)) else ""
                    join_date = (
                        _to_date(r[join_i], _JOIN_FORMATS)
                        if (join_i is not None and join_i < len(r))
                        else None
                    )
                    team_leader = _person(r[tl_i]) if (tl_i is not None and tl_i < len(r)) else ""
                    area_manager = _person(r[am_i]) if (am_i is not None and am_i < len(r)) else ""
                    nip_tl = _person(r[niptl_i]) if (niptl_i is not None and niptl_i < len(r)) else ""
                    dedicated = _person(r[ded_i]) if (ded_i is not None and ded_i < len(r)) else ""
                    nip_am = _person(r[nipam_i]) if (nipam_i is not None and nipam_i < len(r)) else ""
                    nip_baru = _person(r[nipbaru_i]) if (nipbaru_i is not None and nipbaru_i < len(r)) else ""
                    mapping[uid.casefold()] = {
                        "name": name or None,
                        "join_date": join_date,
                        "team_leader": team_leader or None,
                        "area_manager": area_manager or None,
                        "nip_tl": nip_tl or None,
                        "nip_am": nip_am or None,
                        "dedicated": dedicated or None,
                        "nip_baru": nip_baru or None,
                    }
        wb.close()
    except Exception:
        mapping = {}

    _cache["key"] = row.object_path
    _cache["map"] = mapping
    return mapping


def _dedicated_matches(entry, campaigns) -> bool:
    """Apakah baris roster ini termasuk cakupan ``campaigns``.

    ``None`` berarti TIDAK dibatasi (semua campaign lolos). List KOSONG berarti
    dibatasi ke himpunan kosong, jadi tidak ada satu pun baris yang lolos — keduanya
    tidak boleh disamakan, lihat ``api.rbac.effective_campaigns_for``.

    Pembandingannya casefold karena kolom DEDICATED di spreadsheet campur huruf
    besar-kecil ("CASHLINE" 106 baris, "Cashline" 1 baris).
    """
    if campaigns is None:
        return True
    if not campaigns:
        return False
    ded = _norm(entry.get("dedicated")).casefold()
    return ded in {(c or "").strip().casefold() for c in campaigns}


def _agent_ids_by(db, field: str, value: str, campaigns=None) -> set:
    """Agent USER ID (casefold) yang ``entry[field]``-nya sama dengan ``value``
    dan DEDICATED-nya masuk ``campaigns``. Set kosong bila ``value`` kosong atau
    tidak ada yang cocok.

    Dulu fungsi ini mengunci DEDICATED == "cashline". Akibatnya 273 dari 379 baris
    roster (NTB, LOC, RETENTION, REINSTATE, ACTIVATION, MEGAPAY) tidak pernah
    terlihat sistem. Sekarang campaign-nya datang dari ``roster_campaigns_for`` —
    lihat ``api.rbac.effective_campaigns_for``.
    """
    key = _norm(value)
    if not key:
        return set()
    out = set()
    for uid, entry in active_sales_map(db).items():
        if _norm(entry.get(field)) != key:
            continue
        if not _dedicated_matches(entry, campaigns):
            continue
        out.add(uid)
    return out


def agent_ids_for_tl(db, nip_tl: str, campaigns=None) -> set:
    """Agent USER ID di bawah Team Leader ``nip_tl`` (kolom H ``NIP TL``)."""
    return _agent_ids_by(db, "nip_tl", nip_tl, campaigns)


def agent_ids_for_agent(db, nip_baru: str, campaigns=None) -> set:
    """Agent USER ID milik agent itu sendiri (kolom C ``NIP BARU``)."""
    return _agent_ids_by(db, "nip_baru", nip_baru, campaigns)


def agent_ids_for_am(db, nip_am: str, campaigns=None) -> set:
    """Agent USER ID di bawah Area Manager ``nip_am`` (kolom J ``NIP AM``) —
    seluruh agent di bawah SEMUA team leader-nya (AM -> TL -> Agent)."""
    return _agent_ids_by(db, "nip_am", nip_am, campaigns)


# Kolom roster yang menyimpan NIP orangnya, per cakupan data.
_SCOPE_NIP_FIELD = {
    "sales_agent": "nip_baru",
    "sales_tl": "nip_tl",
    "sales_am": "nip_am",
}


def roster_campaign_index(db, scope: str) -> dict:
    """``{NIP (casefold) -> [campaign, ...]}`` untuk satu tingkat hierarki.

    Versi massal dari ``roster_campaigns_for``: sekali lewat roster, bukan sekali
    per orang. Dipakai menu Manage Role untuk merangkum variasi tag yang benar-benar
    dipegang user sebuah role — dengan ratusan user, memanggil versi per-orang berarti
    ratusan kali melintasi roster untuk jawaban yang sama.
    """
    field = _SCOPE_NIP_FIELD.get(scope)
    if not field:
        return {}
    out: dict = {}
    for entry in active_sales_map(db).values():
        nip = _norm(entry.get(field))
        if not nip:
            continue
        ded = _norm(entry.get("dedicated")).casefold()
        if not ded:
            continue
        out.setdefault(nip.casefold(), set()).add(ded)
    return {k: sorted(v) for k, v in out.items()}


def roster_campaigns_for(db, username: str, scope: str) -> list:
    """Campaign yang melekat pada SESEORANG menurut kolom DEDICATED di roster.

    Inilah tag campaign sisi sales — dan sudah otoritatif tanpa perlu role terpisah
    per campaign: dari 379 baris roster, ke-377 agent dan ke-15 team leader masing
    -masing hanya ada di SATU campaign, sehingga NIP-nya sendiri sudah menentukan
    campaign-nya. Area Manager memang lintas campaign (4 dari 5 orang, satu memegang
    lima), dan itu justru sebabnya campaign tidak bisa dititipkan ke nama role:
    ``users.role`` hanya memuat satu nilai.

    Dikembalikan sebagai NAMA CAMPAIGN (huruf kecil, sejajar ``campaigns.name`` dan
    ``results.campaign``), bukan nilai mentah DEDICATED yang huruf besar.

    List kosong berarti orangnya tidak ada di roster. Pemanggil TIDAK boleh
    menganggapnya "semua campaign" — untuk cakupan sales, himpunan agent-nya juga
    kosong sehingga daftar Results memendek ke nol dengan sendirinya.
    """
    field = _SCOPE_NIP_FIELD.get(scope)
    me = _norm(username)
    if not field or not me:
        return []
    out = set()
    for entry in active_sales_map(db).values():
        if _norm(entry.get(field)) != me:
            continue
        ded = _norm(entry.get("dedicated")).casefold()
        if ded:
            out.add(ded)
    return sorted(out)


# Nama lama, dipertahankan supaya pemanggil yang belum diubah tetap jalan. Keduanya
# mengunci campaign cashline seperti sebelumnya.
def cashline_agent_ids_for_tl(db, nip_tl: str) -> set:
    return agent_ids_for_tl(db, nip_tl, ["cashline"])


def cashline_agent_ids_for_agent(db, nip_baru: str) -> set:
    return agent_ids_for_agent(db, nip_baru, ["cashline"])


def cashline_agent_ids_for_am(db, nip_am: str) -> set:
    return agent_ids_for_am(db, nip_am, ["cashline"])


def hierarchy_filter_options(db, data_scope: str, username: str, campaigns=None) -> dict:
    """Dropdown options for the Results hierarchy filter, scoped by ``data_scope``.

    Returns ``{"area_managers": [...], "team_leaders": [...], "agents": [...]}``
    where each entry is ``{"nip", "name", "nip_tl", "nip_am"}``. Values are NIPs
    (stable keys the list endpoint filters on); names are display-only and may
    repeat or be blank in the source spreadsheet.

    Cakupannya mengikuti ``_scoped_customer_ids``: ``sales_am`` hanya melihat TL &
    agent-nya sendiri, ``sales_tl`` hanya agent-nya. Cakupan tanpa bawahan
    (``sales_agent``, ``qc_assigned``, ``qc_support_own``) mendapat daftar kosong
    sehingga UI menyembunyikan filternya.

    Dulu fungsi ini bercabang pada NAMA role, sehingga role buatan operator — mis.
    ``tl_ntb`` — jatuh ke cabang "tak dikenal" dan kehilangan dropdown hierarkinya
    meski cakupan datanya jelas ``sales_tl``.
    """
    empty = {"area_managers": [], "team_leaders": [], "agents": []}
    data_scope = (data_scope or "").strip()
    me = _norm(username)

    entries = [
        e for e in active_sales_map(db).values()
        if _dedicated_matches(e, campaigns)
    ]
    if data_scope == "all":
        pass  # setiap baris agent masuk cakupan
    elif data_scope == "sales_am":
        entries = [e for e in entries if _norm(e.get("nip_am")) == me]
    elif data_scope == "sales_tl":
        entries = [e for e in entries if _norm(e.get("nip_tl")) == me]
    else:
        return empty

    ams, tls, agents = {}, {}, []
    for e in entries:
        nip_am, nip_tl = _norm(e.get("nip_am")), _norm(e.get("nip_tl"))
        if nip_am and nip_am not in ams:
            ams[nip_am] = {"nip": nip_am, "name": _norm(e.get("area_manager")) or nip_am}
        if nip_tl and nip_tl not in tls:
            tls[nip_tl] = {
                "nip": nip_tl,
                "name": _norm(e.get("team_leader")) or nip_tl,
                "nip_am": nip_am,
            }
        nip_agent = _norm(e.get("nip_baru"))
        if nip_agent:
            agents.append({
                "nip": nip_agent,
                "name": _norm(e.get("name")) or nip_agent,
                "nip_tl": nip_tl,
                "nip_am": nip_am,
            })

    by_name = lambda x: x["name"].casefold()
    return {
        # An Area Manager does not need to filter by themselves, and a Team
        # Leader needs neither level above them.
        "area_managers": sorted(ams.values(), key=by_name) if data_scope == "all" else [],
        "team_leaders": sorted(tls.values(), key=by_name) if data_scope != "sales_tl" else [],
        "agents": sorted(agents, key=by_name),
    }


def agent_ids_for_hierarchy_filter(db, am_nip: str, tl_nip: str, agent_nip: str,
                                  campaigns=None) -> Optional[set]:
    """Agent USER IDs matching the most specific hierarchy filter supplied.

    Returns None when no filter is set (meaning "do not narrow"), which the
    caller must distinguish from an empty set ("filter matched nothing").
    """
    if _norm(agent_nip):
        return agent_ids_for_agent(db, agent_nip, campaigns)
    if _norm(tl_nip):
        return agent_ids_for_tl(db, tl_nip, campaigns)
    if _norm(am_nip):
        return agent_ids_for_am(db, am_nip, campaigns)
    return None


def format_tenure(join_date, as_of) -> Optional[str]:
    """Human-readable tenure between two dates, e.g. "3 tahun 1 bulan".

    Calendar-aware (not ``days // 365``): whole months are counted by walking the
    calendar, so a Feb-29 join date and leap years stay correct. Dibulatkan ke
    bawah sampai satuan BULAN — sisa harinya sengaja tidak ditampilkan. Unit yang
    bernilai nol dihilangkan; di bawah satu bulan terbaca "0 bulan". Returns None
    when either date is missing or ``as_of`` precedes ``join_date``.
    """
    if not join_date or not as_of or as_of < join_date:
        return None

    total_months = (as_of.year - join_date.year) * 12 + (as_of.month - join_date.month)
    if as_of.day < join_date.day:
        total_months -= 1

    years, months = divmod(total_months, 12)

    parts = []
    if years:
        parts.append(f"{years} tahun")
    if months or not parts:
        parts.append(f"{months} bulan")
    return " ".join(parts)


def new_joiner_info(cashline_row, db) -> dict:
    """Compute new-joiner details for a cashline row (dict) via the active sales DB.

    Returns ``{agent_id, submit_date, join_date, diff_days, is_new_joiner, tenure}``.
    ``is_new_joiner`` is True only when both dates are known and their gap
    (``submit_time`` minus ``JOIN POSISI``) is < ``NEW_JOINER_THRESHOLD_DAYS`` days.
    ``tenure`` is that same gap rendered as "3 tahun 1 hari" — measured AS OF THE
    TICKET'S submit date, not today, so a row always describes the agent's tenure
    at the moment of the call it documents.
    """
    info = {
        "agent_id": None,
        "submit_date": None,
        "join_date": None,
        "diff_days": None,
        "is_new_joiner": False,
        "tenure": None,
    }
    ref = cashline_row or {}
    agent_id = _norm(ref.get("agent_id")) or None
    info["agent_id"] = agent_id
    info["submit_date"] = _to_date(ref.get("submit_time"), _SUBMIT_FORMATS)
    if not agent_id:
        return info

    entry = active_sales_map(db).get(agent_id.casefold())
    if entry:
        info["join_date"] = entry.get("join_date")
    if info["submit_date"] and info["join_date"]:
        diff = (info["submit_date"] - info["join_date"]).days
        info["diff_days"] = diff
        info["is_new_joiner"] = diff < NEW_JOINER_THRESHOLD_DAYS
        info["tenure"] = format_tenure(info["join_date"], info["submit_date"])
    return info
