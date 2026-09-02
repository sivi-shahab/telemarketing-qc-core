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


def no_product_interest(evaluation: dict) -> bool:
    """True bila nasabah TIDAK berminat pada Mega Cashline MAUPUN Mega Ultima Shield.

    Ini pemicu ZERO-SCORE RULE pada prompt: bila kedua minat bukan "INTERESTED"
    (sehingga ``campaign_interest`` kosong), skor dipaksa 0 dan AI Status FAIL —
    tidak peduli berapa item scorecard yang terpenuhi. Alasannya: panggilan yang
    tidak menghasilkan minat tidak layak dinilai bagus hanya karena prosedurnya
    rapi.

    Sampai 28 Agustus 2026 aturan ini HANYA hidup di prompt, sehingga hitung ulang
    deterministik di modul ini melewatkannya: ``max_score`` jatuh ke
    ``maximum_score`` lalu dikurangi bobot BELUM_SESUAI, menghasilkan skor tinggi
    dan AI Status PASS untuk tiket yang oleh LLM sudah benar dinyatakan FAIL.
    Contoh nyata: 0110505ngB -> LLM 0/FAIL, hitung ulang 101.25/PASS.

    Evaluasi lama yang belum punya blok minat sama sekali dikecualikan (return
    False): tanpa datanya, "tidak berminat" adalah tebakan, dan menebak di sini
    akan menolkan tiket yang tidak bersalah.
    """
    cashline = evaluation.get("cashline_interest")
    mus = evaluation.get("mus_interest")
    if not isinstance(cashline, dict) and not isinstance(mus, dict):
        return False
    cashline_status = (cashline or {}).get("status")
    mus_status = (mus or {}).get("status")
    return cashline_status != "INTERESTED" and mus_status != "INTERESTED"


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
    """Skor scorecard = skor maksimal dikurangi bobot tiap item BELUM_SESUAI.

    ZERO-SCORE RULE didahulukan: nasabah yang tidak berminat pada kedua produk
    mendapat 0, berapa pun item scorecard yang terpenuhi (lihat
    ``no_product_interest``)."""
    if no_product_interest(evaluation):
        return 0
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
    # ZERO-SCORE RULE: tanpa minat pada produk mana pun, vonisnya FAIL tanpa
    # membandingkan skor ke passing grade — skornya sudah dipaksa 0 di atas, tetapi
    # dinyatakan eksplisit di sini supaya tidak bergantung pada passing_grade > 0.
    if no_product_interest(evaluation):
        return "FAIL"
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
