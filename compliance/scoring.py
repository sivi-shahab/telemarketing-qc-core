"""Deterministic AI score / AI status (PASS=APPROVE, FAIL=RETURN) from an
evaluation dict.

Mirrors the per-result computation in ``api/routers/stats.py`` (the Results table),
factored here so the Statistics aggregation can count Approve/Return consistently.
Input is an evaluation dict that has ALREADY had approved appeals applied; the QC
status override and the non-tolerable veto are applied by the caller.
"""


def _to_num(value):
    """Coerce a number/numeric-string to a number (int when whole), else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        n = float(value)
    else:
        try:
            n = float(value)
        except (TypeError, ValueError):
            return None
    if n != n:  # NaN
        return None
    return int(n) if n == int(n) else n


def _numeric_or_none(value):
    """Return ``value`` as a number (int when whole), or None if not numeric."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value) if value == int(value) else value


def max_score(evaluation: dict):
    """Skor maksimal = jumlah bobot produk yang diminati (Mega Cashline 108.75 +
    Mega Ultima Shield 41.25); fallback ke ``maximum_score``."""
    total = 0.0
    found = False
    if (evaluation.get("cashline_interest") or {}).get("status") == "INTERESTED":
        total += 108.75
        found = True
    if (evaluation.get("mus_interest") or {}).get("status") == "INTERESTED":
        total += 41.25
        found = True
    if found:
        return int(total) if total == int(total) else total
    return _to_num(evaluation.get("maximum_score"))


def scorecard_score(evaluation: dict):
    """Skor scorecard = skor maksimal dikurangi bobot tiap item BELUM_SESUAI."""
    max_sc = max_score(evaluation)
    if max_sc is None:
        return None
    belum = sum(
        w for it in (evaluation.get("scorecard_result") or [])
        if it.get("status") == "BELUM_SESUAI"
        and (w := _to_num(it.get("weight"))) is not None
    )
    score = max_sc - belum
    return int(score) if score == int(score) else score


def has_blocking_intolerable_item(evaluation: dict) -> bool:
    """True bila ada item scorecard non-tolerable (tolerable=NO) yang masih
    BELUM_SESUAI — memaksa AI status RETURN (FAIL) berapapun skornya."""
    for item in evaluation.get("scorecard_result") or []:
        tol = str((item or {}).get("tolerable") or "").strip().upper()
        st = str((item or {}).get("status") or "").strip().upper()
        if tol == "NO" and st == "BELUM_SESUAI":
            return True
    return False


def base_ai_status(evaluation: dict):
    """Base AI status 'PASS'/'FAIL' from the deterministic score vs passing grade
    (fallback to the LLM ``ai_status``), WITHOUT the QC override / non-tolerable veto.
    Returns None when it cannot be determined."""
    phase2 = scorecard_score(evaluation)
    verif = _to_num(evaluation.get("ai_score_verification"))
    critical = _to_num(evaluation.get("ai_score_critical_compliance_check"))
    ai_score = None
    if phase2 is not None or verif is not None or critical is not None:
        ai_score = (phase2 or 0) + (verif or 0) + (critical or 0)
    passing = _numeric_or_none(evaluation.get("passing_grade"))
    if ai_score is not None and passing is not None:
        return "PASS" if ai_score >= passing else "FAIL"
    sv = evaluation.get("ai_status")
    if isinstance(sv, str) and sv.strip():
        return sv.strip().upper()
    return None
