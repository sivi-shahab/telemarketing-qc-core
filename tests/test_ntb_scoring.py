"""Skor NTB: aditif NTB 100 + Supplement 25 + MUS 50, kunci minat NTB, tanpa bom
non-tolerable. Evaluasi Cashline (tanpa ``ntb_interest``) tidak boleh berubah.
"""
from qc_core.compliance import scoring
from qc_core.compliance.campaign_profile import critical_item_codes


def _ev(main="INTERESTED", supp="NOT_INTERESTED", mus="NOT_INTERESTED", elig="NOT_REACHED", items=()):
    return {
        "ntb_interest": {"status": main},
        "ntb_supplement_interest": {"status": supp},
        "ntb_mus_interest": {"status": mus},
        "ntb_mus_eligibility": {"status": elig},
        "maximum_score": 999,  # nilai LLM harus diabaikan bila minat terbaca
        "scorecard_result": list(items),
    }


def _item(code, weight, status, tol="YES"):
    return {"item_code": code, "weight": weight, "status": status, "tolerable": tol, "category": "X"}


def test_max_score_per_variant():
    assert scoring.max_score(_ev()) == 100
    assert scoring.max_score(_ev(supp="INTERESTED")) == 125
    assert scoring.max_score(_ev(mus="INTERESTED", elig="ELIGIBLE")) == 150
    assert scoring.max_score(_ev(supp="INTERESTED", mus="INTERESTED", elig="ELIGIBLE")) == 175


def test_mus_stopped_by_health_declaration_not_counted():
    assert scoring.max_score(_ev(mus="INTERESTED", elig="NOT_ELIGIBLE")) == 100


def test_passing_grade_is_90_percent():
    assert scoring.passing_grade(_ev(supp="INTERESTED", mus="INTERESTED", elig="ELIGIBLE")) == 157.5


def test_customer_rejects_main_card_scores_zero_and_fails():
    ev = _ev(main="NOT_INTERESTED", items=[_item("SC_NTB_1", 1, "SESUAI")])
    assert scoring.no_product_interest(ev) is True
    assert scoring.scorecard_score(ev) == 0
    assert scoring.base_ai_status(ev) == "FAIL"


def test_score_is_max_minus_deductions_and_ntb_veto_bomb():
    # item non-tolerable di luar kelompok bomb: hanya memotong bobotnya sendiri, tanpa iris
    ev = _ev(items=[_item("SC_NTB_5", 3, "BELUM_SESUAI", "NO"), _item("SC_NTB_6", 1, "BELUM_SESUAI")])
    assert scoring.scorecard_score(ev) == 96
    assert scoring.non_tolerable_bomb(ev) == 0.0 and scoring.score_bomb_items(ev) == []
    assert scoring.phase3_score(ev) == 96
    assert scoring.has_blocking_intolerable_item(ev) is True  # veto vonis tetap berlaku
    # item Legal Statement gagal: iris 25% (tanpa syarat skor >= passing grade)
    ev = _ev(items=[_item("SC_NTB_71", 5, "BELUM_SESUAI", "NO")])
    assert scoring.non_tolerable_bomb(ev) == -25.0
    assert [b["ratio"] for b in scoring.score_bomb_items(ev)] == [0.25]
    assert scoring.phase3_score(ev) == 70


def test_mus_is_optional_never_mandatory_in_ntb():
    assert scoring.mus_wajib_tidak_dipenuhi(_ev()) is False
    assert scoring.mus_exempt(_ev()) is False


def test_product_breakdown_ntb():
    brk = scoring.product_breakdown(_ev(supp="INTERESTED", mus="INTERESTED", elig="ELIGIBLE"))
    assert [w for _l, w in brk] == [100, 25, 50]


def test_ntb_no_critical_bomb_but_group_bomb():
    # Bom kritis per item dinonaktifkan untuk NTB; yang berlaku satu iris 25% per kelompok (30 Okt 2026).
    assert critical_item_codes(_ev()) == ()
    ev = _ev(items=[_item("SC_NTB_71", 5, "BELUM_SESUAI", "NO")])
    ev["ai_score_critical_compliance_check"] = -25  # nilai bawaan LLM (hasil lama) diabaikan
    ev["critical_compliance_check"] = {"status": "FAIL", "checked_items": [
        {"item_code": "SC_NTB_71", "status": "FAIL", "requirement": "x"}]}
    assert len(scoring.score_bomb_items(ev)) == 1  # hanya iris kelompok, bukan iris kritis
    assert scoring.phase3_score(ev) == 70  # 100 - 5 - 25 (iris kelompok), bukan -25 bawaan LLM tambahan
    assert scoring.has_blocking_intolerable_item(ev) is True  # veto tetap berlaku


def test_critical_codes_per_campaign():
    assert "SC_CL_4" in critical_item_codes({"cashline_interest": {"status": "INTERESTED"}})
    assert "SC_CL_4" in critical_item_codes(None)


def test_cashline_evaluation_unchanged():
    ev = {
        "cashline_interest": {"status": "INTERESTED"},
        "mus_interest": {"status": "INTERESTED"},
        "maximum_score": 150,
        "scorecard_result": [_item("SC_CL_9", 3, "BELUM_SESUAI", "NO")],
    }
    assert scoring.max_score(ev) == 150
    assert scoring.non_tolerable_bomb(ev) == -15.0  # 10% x 150, perilaku semula
    assert [b["ratio"] for b in scoring.score_bomb_items(ev)] == [0.10]


# --- NTB Data Verification & label campaign interest ---------------------------

from qc_core.compliance.ntb_verification import (
    NTB_FIELDS, build_ntb_campaign_interest_verification, build_ntb_data_verification,
)


def test_ntb_fields_map_to_unique_sc_items():
    codes = [c for *_x, c in NTB_FIELDS if c]  # "Lama bekerja" = SC_NTB_76 (hanya ada di scorecard v2)
    assert len(codes) == len(set(codes)) == 26
    assert codes[0] == "SC_NTB_8" and "SC_NTB_76" in codes


def test_data_verification_links_tms_transcript_and_sc_status():
    ev = _ev(items=[_item("SC_NTB_9", 2, "SESUAI"), _item("SC_NTB_10", 2, "BELUM_SESUAI")])
    ev["ntb_application_extraction"] = {"nama_lengkap_ktp": "Budi", "no_ktp": None}
    tms = {"nama-lengkap-sesuai-ktp": "BUDI", "no-ktpkitas": "3171", "telepon-kantor": "0"}
    rows = {r["item_code"]: r for r in build_ntb_data_verification(ev, tms)}
    assert rows["SC_NTB_9"]["tms_value"] == "BUDI" and rows["SC_NTB_9"]["extracted_value"] == "Budi"
    assert rows["SC_NTB_9"]["item_status"] == "SESUAI"
    assert rows["SC_NTB_10"]["extracted_value"] is None and rows["SC_NTB_10"]["item_status"] == "BELUM_SESUAI"
    assert rows["SC_NTB_35"]["tms_value"] is None  # placeholder "0" dianggap kosong


def test_data_verification_without_tms_row_still_lists_fields():
    rows = build_ntb_data_verification(_ev(), None)
    assert len(rows) == 26 and all(r["tms_value"] is None for r in rows)


def test_campaign_interest_labels():
    labels = [l for l, _w in scoring.product_breakdown(_ev(supp="INTERESTED", mus="INTERESTED", elig="ELIGIBLE"))]
    assert labels == ["NTB", "Supplement", "MUS"]
    assert scoring.product_breakdown(_ev(main="NOT_INTERESTED")) == []


# --- Match & similarity NTB Data Verification ----------------------------------

from qc_core.compliance.ntb_verification import compare_field


def test_match_nama_tanggal_dan_digit():
    m, sim, *_ = compare_field("nama-lengkap-sesuai-ktp", "INTAN ARITONANG", "Intan Aritonang")
    assert (m, sim) == ("MATCH", 100.0)
    m, sim, *_ = compare_field("tanggal-lahir", "1981-01-04", "4 Januari 1981")
    assert (m, sim) == ("MATCH", 100.0)
    assert compare_field("handphone", "08119798019", "+62 811-9798-019")[0] == "MATCH"
    m, sim, *_ = compare_field("no-ktpkitas", "3172014401810012", "3172014401810013")
    assert m == "MISMATCH" and sim < 100  # beda 1 digit pun MISMATCH


def test_match_rt_rw_dan_kategori():
    assert compare_field("rumah-rt-new", "014", "14")[0] == "MATCH"
    assert compare_field("rumah-rw-new", "008", "9")[0] == "MISMATCH"
    assert compare_field("jenis-kelamin", "F", "Perempuan")[0] == "MATCH"
    assert compare_field("jenis-kelamin", "F", "Laki-laki")[0] == "MISMATCH"
    assert compare_field("status-perkawinan", "kawin", "sudah menikah")[0] == "MATCH"
    assert compare_field("status-perkawinan", "kawin", "belum menikah")[0] == "MISMATCH"
    assert compare_field("estatement", "Y", "YA")[0] == "MATCH"
    assert compare_field("alamat-pengiriman-kartu", "H", "alamat rumah")[0] == "MATCH"
    assert compare_field("alamat-pengiriman-kartu", "C", "alamat rumah")[0] == "MISMATCH"
    assert compare_field("alamat-tagihan-bulanan", "E", "a@b.com")[0] == "MATCH"


def test_match_penghasilan_rentang_dan_tunggal():
    assert compare_field("penghasilan-kotor-perbulan", "7000000", "6 sampai 7 jutaan")[:2] == ("MATCH", 100.0)
    assert compare_field("penghasilan-kotor-perbulan", "7000000", "tujuh juta")[0] == "MATCH"
    assert compare_field("penghasilan-kotor-perbulan", "7000000", "20 juta")[0] == "MISMATCH"


def test_match_teks_dan_sisi_kosong_tidak_dihukum():
    assert compare_field("rumah-kelurahan-new", "KEL.KEBON PALA", "Kebon Pala")[0] == "MATCH"
    assert compare_field("rumah-kecamatan-new", "KEC.MAKASAR", "Tebet")[0] == "MISMATCH"
    assert compare_field("jabatan", "PEMILIK", None)[:2] == ("SKIPPED_NULL", None)
    assert compare_field("jabatan", None, "staf")[:2] == ("SKIPPED_NULL", None)
    assert compare_field("source-code", "TPIREGRFCNET", "x")[0] == "MATCH"
    assert compare_field("source-code", "TPIBDLREGNET", None)[0] == "MATCH"
    assert compare_field("source-code", "TPLCFC0004", None)[0] == "MISMATCH"
    assert compare_field("source-code", None, None)[0] == "SKIPPED_NULL"


def test_source_code_baris_membawa_source_data():
    rows = build_ntb_data_verification(_ev(), {"source-code": "TPIREGRFCNET"})
    r = next(x for x in rows if x["item_code"] == "SC_NTB_39")
    assert r["match"] == "MATCH" and r["extracted_value"] is None
    assert r["source_value"] == "TPIREGRFCNET, TPIBDLREGNET"
    assert next(x for x in rows if x["item_code"] == "SC_NTB_9")["source_value"] is None


def test_rows_carry_match_fields_and_thresholds():
    rows = build_ntb_data_verification(_ev(), {"nama-lengkap-sesuai-ktp": "BUDI"})
    r = next(x for x in rows if x["item_code"] == "SC_NTB_9")
    assert {"match", "similarity_percent", "reason", "thresholds"} <= set(r) and r["thresholds"]


def test_handphone_keluarga_toleransi_satu_digit():
    from qc_core.compliance.ntb_verification import compare_field
    assert compare_field("handphone-keluarga-dekat", "081234567890", "081234567890")[0] == "MATCH"
    assert compare_field("handphone-keluarga-dekat", "081234567890", "081234567891")[0] == "MATCH"
    assert compare_field("handphone-keluarga-dekat", "081234567890", "081234567811")[0] == "MISMATCH"
    # handphone nasabah tetap persis
    assert compare_field("handphone", "081234567890", "081234567891")[0] == "MISMATCH"


def test_handphone_keluarga_tidak_boleh_sama_dengan_nasabah():
    ev = {"ntb_application_extraction": {"handphone": "0812 3456 7890", "handphone_keluarga_dekat": "081234567890"}}
    rows = {r["field"]: r for r in build_ntb_data_verification(ev, {"handphone-keluarga-dekat": "081234567890"})}
    assert rows["handphone_keluarga_dekat"]["match"] == "MISMATCH"


def test_lama_bekerja_format_yymm():
    from qc_core.compliance.ntb_verification import compare_field, format_lama_kerja, lama_kerja_tms_months
    assert [format_lama_kerja(lama_kerja_tms_months(v)) for v in ("306", "600", "3000")] == [
        "3 tahun 6 bulan", "6 tahun", "30 tahun"]
    assert compare_field("lama-bekerjausaha", "306", "3 tahun 6 bulan")[0] == "MATCH"
    assert compare_field("lama-bekerjausaha", "600", "enam tahun")[0] == "MATCH"
    assert compare_field("lama-bekerjausaha", "3000", "3 tahun")[0] == "MISMATCH"
    rows = {r["field"]: r for r in build_ntb_data_verification(
        {"ntb_application_extraction": {"lama_bekerja": "6 tahun"}}, {"lama-bekerjausaha": "600"})}
    assert rows["lama_bekerja"]["tms_value"] == "6 tahun" and rows["lama_bekerja"]["match"] == "MATCH"


def test_status_kawin_sudah_sama_dengan_kawin():
    from qc_core.compliance.ntb_verification import compare_field
    assert compare_field("status-perkawinan", "kawin", "sudah")[0] == "MATCH"
    assert compare_field("status-perkawinan", "belum kawin", "sudah")[0] == "MISMATCH"


def test_jenis_kelamin_dari_nik_digit_7_12():
    from qc_core.compliance.ntb_verification import gender_from_nik
    assert gender_from_nik("3671062802870004") == "Laki-laki"  # 280287
    assert gender_from_nik("3671066802870004") == "Perempuan"  # 680287 (28 + 40)
    assert gender_from_nik("3172014401810012") == "Perempuan"  # 440181
    assert gender_from_nik("123") is None
    ev = {"ntb_application_extraction": {"no_ktp": None}}
    rows = {r["field"]: r for r in build_ntb_data_verification(
        ev, {"jenis-kelamin": "F", "no-ktpkitas": "3172014401810012"})}
    assert rows["jenis_kelamin"]["match"] == "MATCH" and rows["jenis_kelamin"]["extracted_value"] == "Perempuan"
    rows = {r["field"]: r for r in build_ntb_data_verification(
        ev, {"jenis-kelamin": "M", "no-ktpkitas": "3172014401810012"})}
    assert rows["jenis_kelamin"]["match"] == "MISMATCH"


def test_interest_mus_tms_vs_transkrip():
    def row(tms, status):
        ev = {"ntb_mus_interest": {"status": status}}
        return [r for r in build_ntb_campaign_interest_verification(ev, tms) if r["field"] == "ntb_mus_interest"][0]
    assert row({"pendaftaran-credit-shield": "4-ULTIMA"}, "INTERESTED")["match"] == "MATCH"
    assert row({"pendaftaran-credit-shield": ""}, "NOT_INTERESTED")["match"] == "MATCH"
    assert row({"pendaftaran-credit-shield": "4-ULTIMA"}, "NOT_INTERESTED")["match"] == "MISMATCH"
    assert row({"pendaftaran-credit-shield": ""}, "INTERESTED")["match"] == "MISMATCH"
    assert row(None, "INTERESTED")["match"] == "SKIPPED_NULL"


def test_telepon_kantor_seluler_selalu_salah_kosong_skipped():
    def row(tms, said):
        ev = {"ntb_application_extraction": {"telepon_kantor": said}}
        return [r for r in build_ntb_data_verification(ev, {"telepon-kantor": tms}) if r["field"] == "telepon_kantor"][0]
    assert row("0215550000", "021 555 0000")["match"] == "MATCH"
    assert row("0", None)["match"] == "SKIPPED_NULL"  # kosong tidak dihukum
    assert row("0", "tidak ada")["match"] == "SKIPPED_NULL"
    # seluler: salah walau TMS dan ucapan sama, atau hanya salah satu sisi yang terisi
    assert row("081234567890", "0812 3456 7890")["match"] == "MISMATCH"
    assert row("+6281234567890", None)["match"] == "MISMATCH"
    assert row("0", "08123456789")["match"] == "MISMATCH"
    assert row("6281234567890", "62 812 3456 7890")["match"] == "MISMATCH"


def test_jenis_kelamin_nik_transkrip_tak_terbaca_jatuh_ke_nik_tms():
    ev = {"ntb_application_extraction": {"no_ktp": "tiga enam tujuh satu"}}  # ucapan, bukan 16 digit
    rows = {r["field"]: r for r in build_ntb_data_verification(
        ev, {"jenis-kelamin": "M", "no-ktpkitas": "3671062802870004"})}
    assert rows["jenis_kelamin"]["match"] == "MATCH"


def test_bidang_usaha_jasa_sama_dengan_sektor_jasa():
    from qc_core.compliance.ntb_verification import compare_field
    assert compare_field("bidang-usaha", "SEKTOR JASA", "Jasa")[:2] == ("MATCH", 100.0)
    assert compare_field("bidang-usaha", "SEKTOR JASA", "bidang jasa")[0] == "MATCH"
    assert compare_field("bidang-usaha", "RESTORAN / TEMPAT MAKAN", "restoran tempat makan")[0] == "MATCH"
    assert compare_field("bidang-usaha", "SEKTOR JASA", "Perdagangan")[0] == "MISMATCH"
    assert compare_field("bidang-usaha", "SEKTOR JASA", None)[0] == "SKIPPED_NULL"


def test_pekerjaan_karyawan_sama_dengan_karyawan_swasta():
    from qc_core.compliance.ntb_verification import compare_field
    assert compare_field("pekerjaan", "KARYAWAN SWASTA", "Karyawan")[:2] == ("MATCH", 100.0)
    assert compare_field("pekerjaan", "KARYAWAN SWASTA", "karyawan swasta")[0] == "MATCH"
    assert compare_field("pekerjaan", "WIRASWASTA/PEDAGANG", "wirausaha")[0] == "MATCH"
    assert compare_field("pekerjaan", "WIRASWASTA/PEDAGANG", "Pedagang")[0] == "MATCH"
    assert compare_field("pekerjaan", "KARYAWAN SWASTA", "Karyawan BUMN")[0] == "MISMATCH"
    assert compare_field("pekerjaan", "PNS", "Karyawan")[0] == "MISMATCH"
    assert compare_field("pekerjaan", "PNS", None)[0] == "SKIPPED_NULL"


def _alamat_rows(extraction, tms, items=()):
    ev = _ev(items=list(items))
    ev["ntb_application_extraction"] = extraction
    return {r["item_code"]: r for r in build_ntb_data_verification(ev, tms)}


def test_alamat_rumah_gabungan_semua_komponen_dibandingkan_nol_depan_diabaikan():
    ext = {"alamat_rumah": "Jalan Mawar nomor 5 RT 3 RW 4", "kelurahan": "Cipete", "kecamatan": "Cilandak"}
    tms = {"alamat-rumah-1-new": "JL MAWAR NO 5", "alamat-rumah-2-new": "BLOK C", "rumah-rt-new": "003",
           "rumah-rw-new": "004", "rumah-kelurahan-new": "CIPETE", "rumah-kecamatan-new": "CILANDAK"}
    row = _alamat_rows(ext, tms, [_item("SC_NTB_16", 10, "SESUAI")])["SC_NTB_16"]
    assert row["match"] == "MATCH" and row["item_status"] == "SESUAI"
    assert "BLOK C" in row["tms_value"] and "003" in row["tms_value"]  # minor ikut dibandingkan
    assert "tidak dibandingkan" not in row["reason"]


def test_alamat_singkatan_kp_kel_kec_tm_dianggap_setara():
    from qc_core.compliance.ntb_verification import _alamat_tokens, _alamat_similarity
    assert _alamat_tokens("KP BOJONG KEL.BOJONG KEC.MAJALAYA") == _alamat_tokens("Kampung Bojong Kelurahan Bojong Kecamatan Majalaya")
    assert _alamat_tokens("KEL.KELAPA GADING TM") == _alamat_tokens("Kelurahan Kelapa Gading Timur")
    assert _alamat_similarity("KP SUKA MAJU KEL.CIPETE KEC.CILANDAK TM", "Kampung Suka Maju, Kelurahan Cipete, Kecamatan Cilandak, Timur") == 100.0


def test_alamat_130957fnu6_rumah_dan_kantor_lulus_ambang_60():
    # Data nyata tiket 130957fnu6: kantor baris 1 TMS hanya kelurahan (salah eja), jalannya di baris 2;
    # RT/RW TMS "02" vs ucapan "2". Dulu (major saja, ambang 80) keduanya gagal.
    ext = {"alamat_rumah": "Kampung Bojong Kidul, RT 2, RW 2, Desa Bojong, Kecamatan Majalaya, Kabupaten Bandung, Jawa Barat, 40382",
           "rt": "2", "rw": "2", "kelurahan": "Bojong", "kecamatan": "Majalaya", "nama_perusahaan": "Qube",
           "alamat_kantor": "Kelapa Gading Timur, Jalan Kelapa Cengkir Raya nomor 12 A, Kota Jakarta Utara",
           "kelurahan_kantor": "Kelapa Gading Timur", "pekerjaan": "karyawan swasta"}
    tms = {"alamat-rumah-1-new": "KP BOJONG KIDUL", "alamat-rumah-2-new": "-", "rumah-rt-new": "02", "rumah-rw-new": "02",
           "rumah-kelurahan-new": "KEL.BOJONG", "rumah-kecamatan-new": "KEC.MAJALAYA",
           "nama-perusahaan": "HOTEL QUBE", "alamat-kantor-1-new": "KEPALA GADING TIMUR",
           "alamat-kantor-2-new": "JL KELAPA CENGKIR RAYA NO 12 A", "kantor-kelurahan-new": "KEL.KELAPA GADING TM",
           "kantor-kecamatan-new": "KEC.KELAPA GADING", "pekerjaan": "KARYAWAN SWASTA"}
    rows = _alamat_rows(ext, tms, [_item("SC_NTB_16", 2, "BELUM_SESUAI"), _item("SC_NTB_31", 2, "BELUM_SESUAI")])
    assert rows["SC_NTB_16"]["match"] == "MATCH" and rows["SC_NTB_16"]["similarity_percent"] >= 60
    assert rows["SC_NTB_31"]["match"] == "MATCH" and rows["SC_NTB_31"]["similarity_percent"] >= 60


def test_alamat_rumah_gabungan_gagal_dan_kosong():
    tms = {"alamat-rumah-1-new": "JL MAWAR NO 5", "rumah-kelurahan-new": "CIPETE", "rumah-kecamatan-new": "CILANDAK"}
    row = _alamat_rows({"alamat_rumah": "Jalan Kenanga 99", "kelurahan": "Menteng", "kecamatan": "Tebet"}, tms)["SC_NTB_16"]
    assert row["match"] == "MISMATCH"
    assert _alamat_rows({"alamat_rumah": None}, tms)["SC_NTB_16"]["match"] == "SKIPPED_NULL"


def test_alamat_kantor_gabungan_dan_ibu_rumah_tangga():
    tms = {"nama-perusahaan": "PT MAJU", "alamat-kantor-1-new": "JL SUDIRMAN 1", "kantor-kelurahan-new": "KARET",
           "kantor-kecamatan-new": "SETIABUDI", "pekerjaan": "Karyawan"}
    ext = {"nama_perusahaan": "PT Maju", "alamat_kantor": "Jalan Sudirman 1", "kelurahan_kantor": "Karet",
           "kecamatan_kantor": "Setiabudi", "pekerjaan": "Karyawan"}
    assert _alamat_rows(ext, tms)["SC_NTB_31"]["match"] == "MATCH"
    # Ibu rumah tangga: kantor TMS = alamat rumah (ucapan alamat rumah)
    tms_irt = {"alamat-kantor-1-new": "JL MAWAR NO 5", "kantor-kelurahan-new": "CIPETE", "kantor-kecamatan-new": "CILANDAK"}
    ext_irt = {"pekerjaan": "Ibu rumah tangga", "alamat_rumah": "Jalan Mawar nomor 5", "kelurahan": "Cipete", "kecamatan": "Cilandak"}
    row = _alamat_rows(ext_irt, tms_irt)["SC_NTB_31"]
    assert row["match"] == "MATCH" and "Ibu rumah tangga" in row["reason"]


def test_alamat_tokens_kata_angka_dan_spasi():
    from qc_core.compliance.ntb_verification import _alamat_tokens
    assert _alamat_tokens("nomor tujuh tiga") == ["nomor", "73"]
    assert _alamat_tokens("Blok D satu nomor enam belas") == ["blok", "d1", "nomor", "16"]
    ext = {"alamat_rumah": "Jalan Mawar nomor tujuh tiga", "kelurahan": "Kali Baru", "kecamatan": "Medan Satria"}
    tms = {"alamat-rumah-1-new": "JL MAWAR NO 73", "rumah-kelurahan-new": "KALIBARU", "rumah-kecamatan-new": "MEDANSATRIA"}
    assert _alamat_rows(ext, tms)["SC_NTB_16"]["match"] == "MATCH"


def test_lama_bekerja_item_tanpa_bobot_non_tolerable_veto():
    from qc_core.compliance.ntb_verification import apply_lama_bekerja_verdict
    def ev(spoken):
        e = _ev(items=[_item("SC_NTB_76", 0, "SESUAI", tol="NO")])
        e["ntb_application_extraction"] = {"lama_bekerja": spoken}
        return e
    salah = apply_lama_bekerja_verdict(ev("30 tahun"), {"lama-bekerjausaha": "306"})
    assert salah["scorecard_result"][0]["status"] == "BELUM_SESUAI"
    assert scoring.has_blocking_intolerable_item(salah)
    # bobot 0: tidak mengurangi skor
    assert scoring._item_deduction(salah["scorecard_result"][0]) == 0
    betul = apply_lama_bekerja_verdict(ev("3 tahun 6 bulan"), {"lama-bekerjausaha": "306"})
    assert betul["scorecard_result"][0]["status"] == "SESUAI"
    # TMS kosong / tak disebut -> status LLM dibiarkan
    sk = apply_lama_bekerja_verdict(ev(None), {"lama-bekerjausaha": "306"})
    assert sk["scorecard_result"][0]["status"] == "SESUAI"
    # scorecard lama tanpa item -> aman
    assert apply_lama_bekerja_verdict(_ev(), {"lama-bekerjausaha": "306"})["scorecard_result"] == []


def test_telepon_kantor_kosong_boleh_seluler_ditolak():
    from qc_core.compliance.ntb_verification import apply_telepon_kantor_verdict
    def ev(spoken, status="BELUM_SESUAI"):
        e = _ev(items=[_item("SC_NTB_35", 2, status, tol="NO")])
        e["ntb_application_extraction"] = {"telepon_kantor": spoken}
        return e
    kosong = apply_telepon_kantor_verdict(ev(None), {"telepon-kantor": "0"})
    assert kosong["scorecard_result"][0]["status"] == "SESUAI" and kosong["scorecard_result"][0]["item_score"] == 2
    assert not scoring.has_blocking_intolerable_item(kosong)
    tdk = apply_telepon_kantor_verdict(ev(None, "TIDAK_DINILAI"), {"telepon-kantor": "0"})
    assert tdk["scorecard_result"][0]["status"] == "SESUAI"
    for tms, spoken in (("081234567890", None), (None, "+62 812 3456 7890"), ("021555123", "0812 3456 7890")):
        r = apply_telepon_kantor_verdict(ev(spoken, "SESUAI"), {"telepon-kantor": tms})
        assert r["scorecard_result"][0]["status"] == "BELUM_SESUAI" and scoring.has_blocking_intolerable_item(r)
    # nomor telepon rumah/kantor biasa: status LLM dibiarkan
    ok = apply_telepon_kantor_verdict(ev("021 555 1234", "SESUAI"), {"telepon-kantor": "0215551234"})
    assert ok["scorecard_result"][0]["status"] == "SESUAI"
    # agent tak bertanya tetapi TMS terisi: status LLM dibiarkan
    assert apply_telepon_kantor_verdict(ev(None), {"telepon-kantor": "0215551234"})["scorecard_result"][0]["status"] == "BELUM_SESUAI"


def test_hp_keluarga_mismatch_membuat_sc_belum_sesuai_dengan_alasan():
    from qc_core.compliance.ntb_verification import apply_hp_keluarga_verdict
    def ev(spoken, nasabah=None, status="SESUAI"):
        e = _ev(items=[_item("SC_NTB_25", 2, status, tol="NO")])
        e["ntb_application_extraction"] = {"handphone_keluarga_dekat": spoken, "handphone": nasabah}
        return e
    tms = {"handphone-keluarga-dekat": "081234567890", "handphone": "081299998888"}
    beda = apply_hp_keluarga_verdict(ev("081234500000"), tms)
    it = beda["scorecard_result"][0]
    assert it["status"] == "BELUM_SESUAI" and "tidak sesuai" in it["reason"] and "081234500000" in it["reason"]
    sama = apply_hp_keluarga_verdict(ev("081299998888"), tms)
    assert sama["scorecard_result"][0]["status"] == "BELUM_SESUAI" and "handphone nasabah" in sama["scorecard_result"][0]["reason"]
    # toleransi 1 digit: tetap SESUAI
    assert apply_hp_keluarga_verdict(ev("081234567891"), tms)["scorecard_result"][0]["status"] == "SESUAI"
    # tidak disebut / TMS kosong: status LLM dibiarkan
    assert apply_hp_keluarga_verdict(ev(None), tms)["scorecard_result"][0]["status"] == "SESUAI"


def test_pekerjaan_wirausaha_pedagang_usaha_sama():
    for spoken in ("Usaha", "wirausaha", "Pedagang", "pengusaha", "wiraswasta"):
        assert compare_field("pekerjaan", "WIRASWASTA/PEDAGANG", spoken)[0] == "MATCH", spoken
    assert compare_field("pekerjaan", "PEDAGANG", "wirausaha")[0] == "MATCH"
    assert compare_field("pekerjaan", "KARYAWAN SWASTA", "wirausaha")[0] == "MISMATCH"


def test_ntb_bomb_satu_iris_per_kelompok():
    def gagal(*codes):
        return _ev(items=[_item(c, 1, "BELUM_SESUAI", "NO") for c in codes])
    # banyak item dalam satu kelompok: tetap SATU iris
    assert scoring.non_tolerable_bomb(gagal("SC_NTB_71", "SC_NTB_72")) == -25.0   # Legal Statement
    assert scoring.non_tolerable_bomb(gagal("SC_NTB_46", "SC_NTB_50")) == -25.0   # PDP
    assert scoring.non_tolerable_bomb(gagal("SC_NTB_40")) == -25.0   # sharing data = PDP
    assert scoring.non_tolerable_bomb(gagal("SC_NTB_40", "SC_NTB_46")) == -25.0   # tetap satu iris
    assert scoring.non_tolerable_bomb(gagal("SC_NTB_56", "SC_NTB_59", "SC_NTB_66")) == -25.0  # Final Confirmation
    # kelompok berbeda: iris bertambah, tanpa syarat skor >= passing grade
    ev = gagal("SC_NTB_71", "SC_NTB_46", "SC_NTB_56")
    assert scoring.non_tolerable_bomb(ev) == -75.0 and scoring.phase3_score(ev) == 22
    # KTP: satu atau lebih data salah = satu iris
    ev = _ev(items=[_item("SC_NTB_5", 1, "SESUAI", "NO")])
    ev["ntb_ktp_mismatch"] = ["SC_NTB_10", "SC_NTB_14"]
    assert scoring.non_tolerable_bomb(ev) == -25.0
    assert [b["requirement"] for b in scoring.score_bomb_items(ev)] == ["KTP"]
    # skor dibatasi minimal 0
    ev = gagal("SC_NTB_71", "SC_NTB_46", "SC_NTB_56")
    ev["ntb_ktp_mismatch"] = ["SC_NTB_10"]
    assert scoring.phase3_score(ev) == 0
    # item non-tolerable lain / item tolerable yang gagal: tidak ada iris
    # (SC_NTB_40 tidak lagi di sini: sejak 3 Nov 2026 ia anggota kelompok PDP, lihat di atas)
    assert scoring.non_tolerable_bomb(gagal("SC_NTB_5", "SC_NTB_75")) == 0.0
    assert scoring.non_tolerable_bomb(_ev(items=[_item("SC_NTB_6", 3, "BELUM_SESUAI", "YES")])) == 0.0
    # tidak berminat: skor 0, tidak ada iris
    ev = _ev(main="NOT_INTERESTED", items=[_item("SC_NTB_71", 1, "BELUM_SESUAI", "NO")])
    assert scoring.phase3_score(ev) == 0


def test_ktp_mismatch_dari_verifikasi_hanya_bila_ada_nilai_ktp():
    from qc_core.compliance.ntb_verification import apply_verification_verdicts
    def proses(ktp):
        ev = _ev(items=[_item("SC_NTB_14", 3, "SESUAI", "NO"), _item("SC_NTB_10", 3, "SESUAI", "NO")])
        ev["ntb_application_extraction"] = {"tempat_lahir": "Jakarta", "no_ktp": "3201010101900001"}
        tms = {"tempat-lahir": "Bandung", "no-ktpkitas": "3201010101900001"}
        return apply_verification_verdicts(ev, tms, ktp)["ntb_ktp_mismatch"]
    assert proses({"tempat_lahir": "Surabaya"}) == []  # tempat lahir tidak ikut score bomb KTP
    assert proses({"nik": "3201010101900009"}) == []  # KTP beda tetapi TMS = transkrip: dua sumber sepakat
    assert proses(None) == []  # tanpa KTP ter-OCR tidak dihitung "salah menurut KTP"

    ev = _ev(items=[_item("SC_NTB_10", 3, "SESUAI", "NO")])
    ev["ntb_application_extraction"] = {"no_ktp": "3201010101900002"}
    hasil = apply_verification_verdicts(ev, {"no-ktpkitas": "3201010101900003"}, {"nik": "3201010101900004"})
    assert hasil["ntb_ktp_mismatch"] == ["SC_NTB_10"]  # NIK: ketiganya beda dan ada nilai KTP -> salah


def test_status_sc_mengikuti_match_mismatch_dan_fallback_menanyakan():
    from qc_core.compliance.ntb_verification import apply_verification_verdicts
    items = [_item("SC_NTB_9", 2, "BELUM_SESUAI", "NO"),   # nama: MATCH -> SESUAI
             _item("SC_NTB_10", 2, "SESUAI", "NO"),        # KTP: MISMATCH -> BELUM_SESUAI
             _item("SC_NTB_14", 1, "BELUM_SESUAI", "NO")]  # tempat lahir: tak disebut -> status LLM
    ev = _ev(items=items)
    ev["ntb_application_extraction"] = {"nama_lengkap_ktp": "Budi Santoso", "no_ktp": "3171000000000002", "tempat_lahir": None}
    tms = {"nama-lengkap-sesuai-ktp": "BUDI SANTOSO", "no-ktpkitas": "3171000000000001", "tempat-lahir": "JAKARTA"}
    r = {i["item_code"]: i for i in apply_verification_verdicts(ev, tms)["scorecard_result"]}
    assert r["SC_NTB_9"]["status"] == "SESUAI" and r["SC_NTB_9"]["item_score"] == 2
    assert r["SC_NTB_10"]["status"] == "BELUM_SESUAI" and "TIDAK cocok" in r["SC_NTB_10"]["reason"] and r["SC_NTB_10"]["item_score"] == 0
    assert r["SC_NTB_14"]["status"] == "BELUM_SESUAI"  # tak ada pencocokan: tetap hasil "menanyakan"


def test_status_alamat_gabungan_menular_ke_semua_item_kelompok():
    from qc_core.compliance.ntb_verification import apply_verification_verdicts
    def ev(rumah):
        e = _ev(items=[_item(c, 1, "BELUM_SESUAI", "NO" if c in ("SC_NTB_16", "SC_NTB_20", "SC_NTB_21") else "YES")
                       for c in ("SC_NTB_16", "SC_NTB_17", "SC_NTB_18", "SC_NTB_19", "SC_NTB_20", "SC_NTB_21")])
        e["ntb_application_extraction"] = {"alamat_rumah": rumah, "kelurahan": "Cipete", "kecamatan": "Cilandak"}
        return e
    tms = {"alamat-rumah-1-new": "JL MAWAR NO 5", "rumah-kelurahan-new": "CIPETE", "rumah-kecamatan-new": "CILANDAK"}
    lulus = apply_verification_verdicts(ev("Jalan Mawar nomor lima"), tms)["scorecard_result"]
    assert all(i["status"] == "SESUAI" for i in lulus)  # minor (17-19) ikut lulus walau tak ditanyakan
    assert "Ucapan" not in lulus[0]["evidence"]["quote"] and "TMS:" in lulus[0]["evidence"]["quote"]
    gagal = apply_verification_verdicts(ev("Jalan Kenanga 99"), {**tms, "rumah-kelurahan-new": "MENTENG", "rumah-kecamatan-new": "TEBET"})["scorecard_result"]
    assert all(i["status"] == "BELUM_SESUAI" for i in gagal)


def test_campaign_interest_verification_tiga_baris_dan_tidak_di_tabel_data():
    ev = {"ntb_interest": {"status": "INTERESTED"}, "ntb_supplement_interest": {"status": "NOT_INTERESTED"},
          "ntb_mus_interest": {"status": "NOT_INTERESTED"}}
    tms = {"kartu-kredit-yang-dikehendaki": "VISA METRO CARD", "supplement-1-chk": "on",
           "pendaftaran-credit-shield": "", "source-code": "TPIREGRFCNET"}
    rows = {r["field"]: r for r in build_ntb_campaign_interest_verification(ev, tms)}
    assert list(rows) == ["ntb_interest", "ntb_supplement_interest", "ntb_mus_interest", "ntb_source_code"]
    assert rows["ntb_source_code"]["match"] == "MISMATCH"  # ada kartu tambahan seharusnya TPIBDLREGNET
    tms2 = {**tms, "source-code": "TPIBDLREGNET"}
    assert {r["field"]: r for r in build_ntb_campaign_interest_verification(ev, tms2)}["ntb_source_code"]["match"] == "MATCH"
    tms3 = {"kartu-kredit-yang-dikehendaki": "X", "source-code": "TPIREGRFCNET"}  # tanpa kolom supplement-N-chk terisi
    r3 = {r["field"]: r for r in build_ntb_campaign_interest_verification(ev, tms3)}
    assert r3["ntb_source_code"]["match"] == "MATCH" and r3["ntb_supplement_interest"]["tms_value"] is None
    assert {r["field"]: r for r in build_ntb_campaign_interest_verification(ev, {**tms3, "source-code": ""})}["ntb_source_code"]["match"] == "SKIPPED_NULL"
    assert rows["ntb_interest"]["match"] == "MATCH"
    assert rows["ntb_supplement_interest"]["match"] == "MISMATCH"   # TMS ada kartu tambahan, transkrip menolak
    assert rows["ntb_mus_interest"]["match"] == "MATCH"
    assert all(r["field"] != "ntb_mus_interest" for r in build_ntb_data_verification(ev, tms))
    assert all(r["match"] == "SKIPPED_NULL" for r in build_ntb_campaign_interest_verification(ev, None))


def test_persetujuan_sharing_data_dicek_dari_microsite_belum_dinilai():
    # Persetujuan sharing data ke mitra dicek dari Microsite (menunggu contoh), bukan dari transkrip atau kecocokan TMS "Y".
    from qc_core.compliance.ntb_verification import apply_persetujuan_data_belum_dinilai, apply_verification_verdicts
    assert compare_field("persetujuan-data-nasabah", "Y", "SETUJU")[0] == "SKIPPED_NULL"
    assert compare_field("persetujuan-data-nasabah", "Y", None)[0] == "SKIPPED_NULL"
    ev = _ev(items=[_item("SC_NTB_40", 1, "BELUM_SESUAI", "NO")])
    ev["ntb_application_extraction"] = {"persetujuan_sharing_data": "SETUJU"}
    tms = {"persetujuan-data-nasabah": "Y"}
    row = {x["field"]: x for x in build_ntb_data_verification(ev, tms)}["persetujuan_sharing_data"]
    assert row["match"] == "SKIPPED_NULL" and row["tms_value"] == "Y" and row["extracted_value"] is None
    assert any("Microsite" in x for x in row["thresholds"])
    ev = apply_persetujuan_data_belum_dinilai(apply_verification_verdicts(ev, tms), tms)
    assert ev["scorecard_result"][0]["status"] == "TIDAK_DINILAI"  # tanpa potongan skor dan tanpa veto
    assert scoring.scorecard_score(ev) == 100 and scoring.has_blocking_intolerable_item(ev) is False


def test_pdp_supplement_dari_microsite_belum_dinilai_tanpa_bom():
    from qc_core.compliance.ntb_verification import apply_pdp_supplement_belum_dinilai
    ev = _ev(items=[_item("SC_NTB_46", 5, "BELUM_SESUAI", "NO")])
    assert scoring.non_tolerable_bomb(ev) == -25.0
    ev = apply_pdp_supplement_belum_dinilai(ev)
    assert ev["scorecard_result"][0]["status"] == "TIDAK_DINILAI"
    assert scoring.non_tolerable_bomb(ev) == 0.0 and scoring.has_blocking_intolerable_item(ev) is False
    assert apply_pdp_supplement_belum_dinilai(_ev(items=[_item("SC_NTB_5", 1, "BELUM_SESUAI", "NO")]))["scorecard_result"][0]["status"] == "BELUM_SESUAI"


def test_jenis_kartu_dibandingkan_bila_disebut_selain_itu_tms_valid():
    # tidak disebut -> MATCH; hanya "kartu kredit" -> MATCH; nama jenis disebut -> dibandingkan dengan TMS
    col = "kartu-kredit-yang-dikehendaki"
    assert compare_field(col, "VISA PLATINUM", None)[:2] == ("MATCH", 100.0)
    assert compare_field(col, "VISA PLATINUM", "kartu kredit")[0] == "MATCH"
    assert compare_field(col, "VISA METRO CARD", "Visa Metro")[0] == "MATCH"
    assert compare_field(col, "VISA METRO CARD", "kartu kredit Visa Metro Card")[0] == "MATCH"
    assert compare_field(col, "VISA PLATINUM", "Visa Metro")[0] == "MISMATCH"
    assert compare_field(col, "MEGA TRAVEL CARD UMUM", "Visa Gold")[0] == "MISMATCH"
    ev = _ev(items=[_item("SC_NTB_8", 1, "BELUM_SESUAI", "NO")])
    ev["ntb_application_extraction"] = {}
    row = {x["field"]: x for x in build_ntb_data_verification(ev, {"kartu-kredit-yang-dikehendaki": "VISA METRO CARD"})}["jenis_kartu"]
    assert row["match"] == "MATCH" and row["similarity_percent"] == 100.0
    from qc_core.compliance.ntb_verification import apply_verification_verdicts
    assert apply_verification_verdicts(ev, {"kartu-kredit-yang-dikehendaki": "VISA METRO CARD"})["scorecard_result"][0]["status"] == "SESUAI"
    row = {x["field"]: x for x in build_ntb_data_verification(ev, {"kartu-kredit-yang-dikehendaki": ""})}["jenis_kartu"]
    assert row["match"] == "SKIPPED_NULL"


def test_alamat_pengiriman_kartu_alamat_lengkap_sama_dengan_rumah_cocok_kode_h():
    ext = {"alamat_rumah": "Jalan Pendidikan RT 1 RW 6", "kelurahan": "Mangunjaya", "kecamatan": "Tambun Selatan",
           "alamat_pengiriman_kartu": "Jalan Pendidikan, RT 1, RW 6, Kelurahan Mangunjaya, Kecamatan Tambun Selatan, Kabupaten Bekasi, Jawa Barat"}
    tms = {"alamat-rumah-1-new": "JL PENDIDIKAN", "rumah-kelurahan-new": "MANGUNJAYA", "rumah-kecamatan-new": "TAMBUN SELATAN",
           "alamat-kantor-1-new": "JL SUDIRMAN 1", "kantor-kelurahan-new": "KARET", "kantor-kecamatan-new": "SETIABUDI",
           "alamat-pengiriman-kartu": "H"}
    rows = {r["field"]: r for r in build_ntb_data_verification(_ev(), None)}  # struktur baris
    ev = _ev(); ev["ntb_application_extraction"] = ext
    r = {x["field"]: x for x in build_ntb_data_verification(ev, tms)}["alamat_pengiriman_kartu"]
    assert r["match"] == "MATCH" and "alamat rumah" in r["reason"]
    # TMS C (kantor) tetapi yang disebut alamat rumah -> MISMATCH
    r = {x["field"]: x for x in build_ntb_data_verification(ev, {**tms, "alamat-pengiriman-kartu": "C"})}["alamat_pengiriman_kartu"]
    assert r["match"] == "MISMATCH"
    # kata "rumah" tetap dipahami seperti sebelumnya
    ev["ntb_application_extraction"] = {"alamat_pengiriman_kartu": "ke alamat rumah"}
    assert {x["field"]: x for x in build_ntb_data_verification(ev, tms)}["alamat_pengiriman_kartu"]["match"] == "MATCH"


def test_alamat_pengiriman_subset_alamat_rumah_benar_bila_tms_h():
    ext = {"alamat_rumah": "Kampung Bojong Kidul, RT 2, RW 2, Desa Bojong, Kecamatan Majalaya", "kelurahan": "Bojong",
           "kecamatan": "Majalaya", "alamat_pengiriman_kartu": "Ke Majalaya aja"}
    tms = {"alamat-rumah-1-new": "KP BOJONG KIDUL", "rumah-kelurahan-new": "KEL.BOJONG", "rumah-kecamatan-new": "KEC.MAJALAYA",
           "alamat-kantor-1-new": "KEPALA GADING TIMUR", "kantor-kelurahan-new": "KEL.KELAPA GADING", "alamat-pengiriman-kartu": "H"}
    ev = _ev(); ev["ntb_application_extraction"] = ext
    r = {x["field"]: x for x in build_ntb_data_verification(ev, tms)}["alamat_pengiriman_kartu"]
    assert r["match"] == "MATCH" and "bagian dari alamat rumah" in r["reason"]
    # TMS C (kantor) tetapi yang disebut bagian alamat rumah -> MISMATCH
    r = {x["field"]: x for x in build_ntb_data_verification(ev, {**tms, "alamat-pengiriman-kartu": "C"})}["alamat_pengiriman_kartu"]
    assert r["match"] == "MISMATCH"
    # kata di luar alamat tidak dianggap subset
    ev["ntb_application_extraction"] = {**ext, "alamat_pengiriman_kartu": "Ke Surabaya aja"}
    r = {x["field"]: x for x in build_ntb_data_verification(ev, tms)}["alamat_pengiriman_kartu"]
    assert r["match"] == "MISMATCH"


def test_ibu_rumah_tangga_tms_kantor_kosong_dianggap_sama_dengan_rumah():
    from qc_core.compliance.ntb_verification import apply_verification_verdicts
    ev = _ev(items=[_item(c, 1, "BELUM_SESUAI", "NO") for c in ("SC_NTB_30", "SC_NTB_31", "SC_NTB_32", "SC_NTB_33", "SC_NTB_34")])
    ev["ntb_application_extraction"] = {"pekerjaan": "Ibu rumah tangga", "alamat_rumah": "Jalan Mawar 5"}
    row = {x["field"]: x for x in build_ntb_data_verification(ev, {"pekerjaan": "IRT"})}["alamat_kantor"]
    assert row["match"] == "MATCH" and "Ibu rumah tangga" in row["reason"]
    out = apply_verification_verdicts(ev, {"pekerjaan": "IRT"})["scorecard_result"]
    assert all(i["status"] == "SESUAI" for i in out)
    # bukan IRT dan TMS kantor kosong: tetap SKIPPED (status LLM)
    ev2 = _ev(items=[_item("SC_NTB_31", 1, "BELUM_SESUAI", "NO")])
    ev2["ntb_application_extraction"] = {"pekerjaan": "Karyawan"}
    assert {x["field"]: x for x in build_ntb_data_verification(ev2, {})}["alamat_kantor"]["match"] == "SKIPPED_NULL"


def test_item_yang_dihilangkan_llm_ditambah_lalu_telepon_kantor_kosong_sesuai():
    import json
    from qc_core.compliance.ntb_verification import apply_telepon_kantor_verdict, ensure_scorecard_items
    master = json.dumps([
        {"category": "Pengisian Data Basic", "item_code": "SC_NTB_9", "requirement": "x", "kb_reference": "KB_NTB_9", "weight": 2, "tolerable": "NO"},
        {"category": "Pengisian Data Basic", "item_code": "SC_NTB_35", "requirement": "telp kantor", "kb_reference": "KB_NTB_35", "weight": 2, "tolerable": "NO"}])
    ev = _ev(items=[_item("SC_NTB_9", 2, "SESUAI", "NO")])   # LLM tidak mengembalikan SC_NTB_35
    ev["ntb_application_extraction"] = {"telepon_kantor": None}
    ev = ensure_scorecard_items(ev, master)
    row = next(i for i in ev["scorecard_result"] if i["item_code"] == "SC_NTB_35")
    assert row["status"] == "TIDAK_DINILAI" and row["weight"] == 2 and row["tolerable"] == "NO"
    assert not scoring.has_blocking_intolerable_item(ev) and scoring.scorecard_score(ev) == 100
    ev = apply_telepon_kantor_verdict(ev, {"telepon-kantor": "0"})
    assert next(i for i in ev["scorecard_result"] if i["item_code"] == "SC_NTB_35")["status"] == "SESUAI"
    assert len(ev["scorecard_result"]) == 2
    # teks scorecard rusak -> aman
    assert ensure_scorecard_items(_ev(), "bukan json")["scorecard_result"] == []


def test_alamat_kantor_hanya_nama_perusahaan_terekstrak_tidak_dibandingkan_parsial():
    # 0203106ktH: ekstraksi hanya "Hatindo" (alamat kantor null) -> bukan MISMATCH 13%, melainkan SKIPPED
    tms = {"nama-perusahaan": "PT HATINDO", "alamat-kantor-1-new": "JL RAYA CEGER NO 3",
           "kantor-kelurahan-new": "KEL.CIPAYUNG", "kantor-kecamatan-new": "KEC.CIPAYUNG", "pekerjaan": "KARYAWAN SWASTA"}
    ev = _ev(items=[_item("SC_NTB_31", 2, "SESUAI", "NO")])
    ev["ntb_application_extraction"] = {"nama_perusahaan": "Hatindo", "alamat_kantor": None, "pekerjaan": "Karyawan"}
    row = {x["field"]: x for x in build_ntb_data_verification(ev, tms)}["alamat_kantor"]
    assert row["match"] == "SKIPPED_NULL"
    from qc_core.compliance.ntb_verification import apply_verification_verdicts
    assert apply_verification_verdicts(ev, tms)["scorecard_result"][0]["status"] == "SESUAI"  # status LLM dipakai


def test_email_dinormalkan_dari_ucapan():
    from qc_core.compliance.ntb_verification import normalize_email
    assert normalize_email("Hidayat Rizki75 at gmail dot com") == "hidayatrizki75@gmail.com"
    assert normalize_email("wahyupurnomoadi at gmail dot com") == "wahyupurnomoadi@gmail.com"
    assert normalize_email("budi underscore santoso at yahoo dot co dot id") == "budi_santoso@yahoo.co.id"
    assert normalize_email("a@b.com") == "a@b.com"
    assert compare_field("email-address", "hidayatrizky75@gmail.com", "Hidayat Rizki75 at gmail dot com")[0] == "MATCH"  # rizky/rizki
    assert compare_field("email-address", "budi@gmail.com", "Budi at gmail dot com")[0] == "MATCH"
    assert compare_field("email-address", "budi75@gmail.com", "Budi76 at gmail dot com")[0] == "MISMATCH"  # angka beda
    assert compare_field("email-address", "budi@gmail.com", "andi at yahoo dot com")[0] == "MISMATCH"
    assert compare_field("email-address", "budi@gmail.com", None)[0] == "SKIPPED_NULL"
    # domain dinilai terpisah: local panjang yang identik tidak menutupi domain yang beda
    assert compare_field("email-address", "hidayatrizkiramadhan@gmail.com", "hidayatrizkiramadhan at yahoo dot com")[0] == "MISMATCH"


# --- NTB Supplement Verification (kartu tambahan) ------------------------------

def _supl_tms(**kw):
    base = {"full-name-supplektp-1-new": " NOVIA ", "jenis-kelamin-1-new": "F",
            "hub-status-keluarga-1-new": "Istri", "alamat-pengiriman-kartu": "H"}
    base.update(kw)
    return base


def _supl_rows(ev, tms):
    from qc_core.compliance.ntb_verification import build_ntb_supplement_verification
    return {r["field"]: r for r in build_ntb_supplement_verification(ev, tms)}


def test_supplement_verification_empty_when_no_card_anywhere():
    from qc_core.compliance.ntb_verification import build_ntb_supplement_verification
    ev = _ev()
    ev["ntb_application_extraction"] = {"kartu_tambahan": []}
    assert build_ntb_supplement_verification(ev, {"full-name-supplektp-1-new": ""}) == []
    assert build_ntb_supplement_verification(ev, None) == []


def test_supplement_verification_match_and_item_links():
    ev = _ev(items=[_item("SC_NTB_42", 2, "SESUAI"), _item("SC_NTB_44", 2, "BELUM_SESUAI")])
    ev["ntb_application_extraction"] = {"kartu_tambahan": [{"nama": "Novia", "jenis_kelamin": "Perempuan", "hubungan": "istri saya"}]}
    rows = _supl_rows(ev, _supl_tms())
    assert rows["kartu_tambahan_1_nama"]["match"] == "MATCH" and rows["kartu_tambahan_1_nama"]["tms_value"] == "NOVIA"
    assert rows["kartu_tambahan_1_jenis_kelamin"]["match"] == "MATCH"
    assert rows["kartu_tambahan_1_hubungan"]["match"] == "MATCH"
    assert rows["kartu_tambahan_1_nama"]["item_code"] == "SC_NTB_42" and rows["kartu_tambahan_1_nama"]["item_status"] == "SESUAI"
    assert rows["kartu_tambahan_1_hubungan"]["item_status"] == "BELUM_SESUAI"


def test_supplement_verification_mismatch_and_skipped():
    ev = _ev()
    ev["ntb_application_extraction"] = {"kartu_tambahan": [{"nama": "Rina", "jenis_kelamin": "Laki-laki", "hubungan": None}]}
    rows = _supl_rows(ev, _supl_tms())
    # satu kartu di tiap sisi dipasangkan menurut urutan walau nama berbeda
    assert rows["kartu_tambahan_1_nama"]["match"] == "MISMATCH"
    assert rows["kartu_tambahan_1_jenis_kelamin"]["match"] == "MISMATCH"
    assert rows["kartu_tambahan_1_hubungan"]["match"] == "SKIPPED_NULL"  # tidak disebut


def test_supplement_hubungan_groups():
    from qc_core.compliance.ntb_verification import compare_field
    cmp = lambda t, s: compare_field("hub-status-keluarga", t, s)[0]
    assert cmp("SaudaraLaki-laki", "kakak saya") == "MATCH"
    assert cmp("Saudaraperempuan", "adik") == "MATCH"
    assert cmp("OrangTua", "ibu saya") == "MATCH"
    assert cmp("Anak", "anak") == "MATCH"
    assert cmp("Suami", "istri") == "MISMATCH"
    assert cmp("Istri", "anak") == "MISMATCH"


def test_supplement_pairing_by_name_not_order():
    ev = _ev()
    ev["ntb_application_extraction"] = {"kartu_tambahan": [
        {"nama": "Budi Santoso", "jenis_kelamin": "Laki-laki", "hubungan": "anak"},
        {"nama": "Novia", "jenis_kelamin": "Perempuan", "hubungan": "istri"},
    ]}
    tms = _supl_tms(**{"full-name-supplektp-2-new": "BUDI SANTOSO", "jenis-kelamin-2-new": "M", "hub-status-keluarga-2-new": "Anak"})
    rows = _supl_rows(ev, tms)
    assert rows["kartu_tambahan_1_nama"]["extracted_value"] == "Novia" and rows["kartu_tambahan_1_nama"]["match"] == "MATCH"
    assert rows["kartu_tambahan_2_nama"]["extracted_value"] == "Budi Santoso" and rows["kartu_tambahan_2_nama"]["match"] == "MATCH"
    assert rows["kartu_tambahan_2_hubungan"]["match"] == "MATCH"


def test_supplement_alamat_pengiriman_follows_main_card():
    ev = _ev(items=[_item("SC_NTB_45", 1, "SESUAI")])
    ev["ntb_application_extraction"] = {"alamat_pengiriman_kartu": "ke rumah", "kartu_tambahan": [{"nama": "Novia"}]}
    row = _supl_rows(ev, _supl_tms())["kartu_tambahan_alamat_pengiriman"]
    assert row["match"] == "MATCH" and row["item_code"] == "SC_NTB_45" and row["item_status"] == "SESUAI"
    ev["ntb_application_extraction"]["alamat_pengiriman_kartu"] = "ke kantor"
    assert _supl_rows(ev, _supl_tms())["kartu_tambahan_alamat_pengiriman"]["match"] == "MISMATCH"


def _supl_ev(status42="SESUAI", status43="SESUAI", status44="SESUAI", status45="SESUAI", kartu=None):
    ev = _ev(items=[_item("SC_NTB_42", 2, status42), _item("SC_NTB_43", 1, status43),
                    _item("SC_NTB_44", 1, status44), _item("SC_NTB_45", 1, status45)])
    ev["ntb_application_extraction"] = {"alamat_pengiriman_kartu": "ke kantor", "kartu_tambahan": kartu if kartu is not None else [
        {"nama": "Novia", "jenis_kelamin": "Perempuan", "hubungan": "anak"}]}
    return ev


def test_supplement_verdicts_mismatch_forces_belum_sesuai_and_match_forces_sesuai():
    from qc_core.compliance.ntb_verification import apply_supplement_verdicts
    ev = apply_supplement_verdicts(_supl_ev(status42="BELUM_SESUAI", status43="BELUM_SESUAI"), _supl_tms())
    by = {i["item_code"]: i for i in ev["scorecard_result"]}
    assert by["SC_NTB_42"]["status"] == "SESUAI" and by["SC_NTB_42"]["item_score"] == 2   # MATCH menaikkan
    assert by["SC_NTB_43"]["status"] == "SESUAI"
    assert by["SC_NTB_44"]["status"] == "BELUM_SESUAI" and by["SC_NTB_44"]["item_score"] == 0  # istri vs anak
    assert "Hubungan kekerabatan" in by["SC_NTB_44"]["reason"]


def test_supplement_verdicts_leave_skipped_not_assessed_and_address_row():
    from qc_core.compliance.ntb_verification import apply_supplement_verdicts
    # hubungan tidak disebut -> SKIPPED_NULL -> status LLM tetap; alamat kirim (SC_NTB_45) tidak ditimpa
    ev = apply_supplement_verdicts(_supl_ev(status44="BELUM_SESUAI", kartu=[{"nama": "Novia", "jenis_kelamin": "Perempuan"}]), _supl_tms())
    by = {i["item_code"]: i for i in ev["scorecard_result"]}
    assert by["SC_NTB_44"]["status"] == "BELUM_SESUAI"
    assert by["SC_NTB_45"]["status"] == "SESUAI"  # sekalipun alamat kirim kartu utama MISMATCH
    # Supplement tidak diikuti (TIDAK_DINILAI) tidak dihidupkan kembali walau TMS punya kartu tambahan
    ev = apply_supplement_verdicts(_supl_ev(status42="TIDAK_DINILAI", status43="TIDAK_DINILAI", status44="TIDAK_DINILAI", kartu=[]), _supl_tms())
    assert {i["item_code"]: i["status"] for i in ev["scorecard_result"]}["SC_NTB_42"] == "TIDAK_DINILAI"


def test_supplement_verdicts_multi_card_any_mismatch_fails_all_match_passes():
    from qc_core.compliance.ntb_verification import apply_supplement_verdicts
    tms = _supl_tms(**{"full-name-supplektp-2-new": "BUDI SANTOSO", "jenis-kelamin-2-new": "M", "hub-status-keluarga-2-new": "Anak"})
    benar = [{"nama": "Novia", "jenis_kelamin": "Perempuan", "hubungan": "istri"},
             {"nama": "Budi Santoso", "jenis_kelamin": "Laki-laki", "hubungan": "anak"}]
    by = {i["item_code"]: i["status"] for i in apply_supplement_verdicts(_supl_ev(status43="BELUM_SESUAI", kartu=benar), tms)["scorecard_result"]}
    assert by["SC_NTB_42"] == by["SC_NTB_43"] == by["SC_NTB_44"] == "SESUAI"
    salah = [benar[0], {**benar[1], "jenis_kelamin": "Perempuan"}]
    by = {i["item_code"]: i["status"] for i in apply_supplement_verdicts(_supl_ev(kartu=salah), tms)["scorecard_result"]}
    assert by["SC_NTB_43"] == "BELUM_SESUAI" and by["SC_NTB_42"] == "SESUAI"


def test_handphone_nasabah_tidak_dibandingkan_dengan_transkrip():
    from qc_core.compliance.ntb_verification import apply_verification_verdicts
    ev = _ev(items=[_item("SC_NTB_22", 2, "SESUAI")])
    ev["ntb_application_extraction"] = {"handphone": "081234567891"}  # beda dari TMS, tetap tidak dibandingkan
    row = {r["field"]: r for r in build_ntb_data_verification(ev, {"handphone": "081234567890"})}["handphone"]
    assert row["match"] == "SKIPPED_NULL" and row["extracted_value"] is None and row["thresholds"]
    item = apply_verification_verdicts(ev, {"handphone": "081234567890"})["scorecard_result"][0]
    assert item["status"] == "SESUAI"  # status dari LLM dibiarkan

def test_ntb_ktp_age_boundaries():
    from qc_core.compliance.ntb_ktp import ntb_age_rejection

    sub = "2026-10-13 10:09:35"
    ok = lambda dob: ntb_age_rejection({"tanggal_lahir": dob}, sub) is None
    assert ok("2005-10-13")        # tepat 21 tahun
    assert not ok("2005-10-14")    # 20 tahun 364 hari
    assert ok("1961-10-13")        # tepat 65 tahun
    assert not ok("1960-10-13")    # 66 tahun
    assert ok(None) and ok("bukan tanggal")
    assert ntb_age_rejection(None, sub) is None


def test_ntb_ktp_lama_nik_bukan_16_digit_ditolak():
    from qc_core.compliance.ntb_ktp import ntb_old_ktp_rejection

    ktp = lambda nik: {"verifications": [{"field": "NIK", "document": nik}, {"field": "Kewarganegaraan", "document": "WNI"}]}
    assert ntb_old_ktp_rejection(ktp("3171234567890123")) is None            # e-KTP, 16 digit
    assert ntb_old_ktp_rejection(ktp("3171 2345 6789 0123")) is None        # pemisah diabaikan
    r = ntb_old_ktp_rejection(ktp("317123456789012"))                         # 15 digit
    assert r["kind"] == "ktp_lama" and "15 digit" in r["reason"]
    assert ntb_old_ktp_rejection(ktp("31712345678901234"))["kind"] == "ktp_lama"  # 17 digit
    assert ntb_old_ktp_rejection(ktp(None)) is None and ntb_old_ktp_rejection(ktp("")) is None  # tak terbaca
    assert ntb_old_ktp_rejection(None) is None and ntb_old_ktp_rejection({}) is None


def test_ntb_ktp_rejection_forces_zero_and_fail():
    from qc_core.compliance.scoring import base_ai_status, scorecard_score

    ev = _ev(items=[])
    assert scorecard_score(ev) != 0
    ev = {**ev, "ntb_ktp_rejection": {"age": 19, "reason": "x"}}
    assert scorecard_score(ev) == 0
    assert base_ai_status(ev) == "FAIL"


def test_ntb_ktp_is_required_and_never_waived():
    from qc_core.compliance.documents import doc_requirements_waived, required_doc_types

    ev = _ev(items=[_item("SC_NTB_5", 3, "BELUM_SESUAI", "NO")])   # non-tolerable gagal
    rj = {"evaluation": ev}
    assert not doc_requirements_waived(rj)
    assert required_doc_types(rj) == ["ktp"]
    assert required_doc_types({"evaluation": {"scorecard_result": []}}) == []


def test_supplement_names_must_be_unique():
    from qc_core.compliance.ntb_verification import apply_supplement_verdicts
    tms = _supl_tms(**{"full-name-supplektp-2-new": "NOVIA", "jenis-kelamin-2-new": "F", "hub-status-keluarga-2-new": "Istri"})
    kartu = [{"nama": "Novia", "jenis_kelamin": "Perempuan", "hubungan": "istri"},
             {"nama": "Novia", "jenis_kelamin": "Perempuan", "hubungan": "istri"}]
    by = {i["item_code"]: i for i in apply_supplement_verdicts(_supl_ev(kartu=kartu), tms)["scorecard_result"]}
    assert by["SC_NTB_42"]["status"] == "BELUM_SESUAI" and "tidak boleh sama" in by["SC_NTB_42"]["reason"]
    # nama berbeda -> tidak terpengaruh; Supplement tidak diikuti -> tidak dihidupkan
    ev = apply_supplement_verdicts(_supl_ev(status42="TIDAK_DINILAI", kartu=kartu), tms)
    assert {i["item_code"]: i["status"] for i in ev["scorecard_result"]}["SC_NTB_42"] == "TIDAK_DINILAI"


def _baris(tms, code):
    return next(x for x in build_ntb_data_verification(_ev(), tms) if x["item_code"] == code)


def test_estatement_mengikuti_alamat_penagihan_tanpa_transkrip():
    r = _baris({"alamat-tagihan-bulanan": "E", "estatement": "Y"}, "SC_NTB_41")
    assert r["match"] == "MATCH" and r["extracted_value"] is None and r["source_value"].startswith("Y")
    assert _baris({"alamat-tagihan-bulanan": "E", "estatement": "N"}, "SC_NTB_41")["match"] == "MISMATCH"
    assert _baris({"alamat-tagihan-bulanan": "H", "estatement": "N"}, "SC_NTB_41")["match"] == "MATCH"
    assert _baris({"alamat-tagihan-bulanan": "C", "estatement": "Y"}, "SC_NTB_41")["match"] == "MISMATCH"
    assert _baris({"alamat-tagihan-bulanan": "E"}, "SC_NTB_41")["match"] == "SKIPPED_NULL"


def test_alamat_penagihan_tak_disebut_dicek_terhadap_estatement():
    assert _baris({"alamat-tagihan-bulanan": "E", "estatement": "Y"}, "SC_NTB_38")["match"] == "MATCH"
    assert _baris({"alamat-tagihan-bulanan": "E", "estatement": "N"}, "SC_NTB_38")["match"] == "MISMATCH"
    assert _baris({"alamat-tagihan-bulanan": "H", "estatement": "Y"}, "SC_NTB_38")["match"] == "MISMATCH"
    assert _baris({"alamat-tagihan-bulanan": "E"}, "SC_NTB_38")["match"] == "SKIPPED_NULL"


def test_nama_ktp_tiga_arah_ocr_tms_transkrip():
    def baris(tms, ocr, ucap):
        ev = _ev()
        ev["ntb_application_extraction"] = {"nama_lengkap_ktp": ucap}
        return next(x for x in build_ntb_data_verification(ev, {"nama-lengkap-sesuai-ktp": tms}, ocr) if x["item_code"] == "SC_NTB_9")
    r = baris("BUDI SANTOSO", "Budi Santoso", "Budi Santoso")
    assert r["match"] == "MATCH" and r["source_value"] == "Budi Santoso"
    # voting: minimal 2 dari 3 sumber sepakat; satu sumber yang menyimpang tidak menggagalkan
    assert baris("BUDI SANTOSO", "Budi Santoso", "Andi Wijaya")["match"] == "MATCH"  # transkrip beda
    assert baris("BUDI SANTOSO", "Andi Wijaya", "Budi Santoso")["match"] == "MATCH"  # Microsite beda
    assert baris("Andi Wijaya", "Budi Santoso", "Budi Santoso")["match"] == "MATCH"  # TMS beda
    assert baris("BUDI SANTOSO", "Andi Wijaya", "Rina Marlina")["match"] == "MISMATCH"  # ketiganya beda
    assert baris("BUDI SANTOSO", "Budi Santoso", None)["match"] == "MATCH"  # transkrip kosong: pasangan OCR-TMS saja
    assert baris("BUDI SANTOSO", None, "Andi Wijaya")["match"] == "MISMATCH"  # tanpa OCR: TMS vs transkrip
    assert baris("BUDI SANTOSO", None, None)["match"] == "SKIPPED_NULL"


def test_ktp_ocr_name_ambil_ktp_terakhir_yang_terbaca():
    from qc_core.compliance.ntb_verification import ktp_ocr_name
    docs = [("kk", {"nama_ktp": "X"}), ("ktp", {"nama_ktp": "A"}), ("ktp", {"verifications": []}), ("ktp", {"nama_ktp": " B "})]
    assert ktp_ocr_name(docs) == "B" and ktp_ocr_name([("ktp", {})]) is None


def test_handphone_nasabah_tidak_boleh_sama_dengan_keluarga_dekat():
    def baris(tms, ucap_keluarga=None):
        ev = _ev()
        ev["ntb_application_extraction"] = {"handphone_keluarga_dekat": ucap_keluarga} if ucap_keluarga else {}
        return next(x for x in build_ntb_data_verification(ev, tms) if x["item_code"] == "SC_NTB_22")
    r = baris({"handphone": "081234567890", "handphone-keluarga-dekat": "081234567890"})
    assert r["match"] == "MISMATCH" and any("keluarga dekat" in t for t in r["thresholds"])
    assert baris({"handphone": "081234567890"}, "0812 3456 7890")["match"] == "MISMATCH"  # keluarga dari ucapan
    r = baris({"handphone": "081234567890", "handphone-keluarga-dekat": "081299998888"})
    assert r["match"] == "SKIPPED_NULL" and any("keluarga dekat" in t for t in r["thresholds"])


def test_microsite_csv_per_field_voting_dua_sumber_sepakat(tmp_path, monkeypatch):
    from qc_core.compliance import ntb_verification as nv
    (tmp_path / "tempat-lahir.csv").write_text("ticket_id,value\nT1,Bandung\nT2,Bogor\n", encoding="utf-8")
    monkeypatch.setattr(nv, "MICROSITE_DIR", str(tmp_path))

    def baris(ticket, tms, ucap):
        ev = _ev()
        ev["ntb_application_extraction"] = {"tempat_lahir": ucap}
        row = {"result_id": ticket, "tempat-lahir": tms}
        return next(x for x in nv.build_ntb_data_verification(ev, row) if x["item_code"] == "SC_NTB_14")
    r = baris("T1", "Bandung", "Jakarta")  # TMS = Microsite, transkrip beda -> 2 sumber sepakat
    assert r["match"] == "MATCH" and r["source_value"] == "Bandung" and any("Voting" in t for t in r["thresholds"])
    assert baris("T1", "Jakarta", "Bandung")["match"] == "MATCH"  # Microsite = transkrip
    assert baris("T2", "Bandung", "Jakarta")["match"] == "MISMATCH"  # ketiganya beda
    assert baris("T3", "Bandung", "Jakarta")["match"] == "MISMATCH"  # tanpa Microsite: TMS vs transkrip
    assert baris("T1", "Bandung", None)["match"] == "MATCH"  # transkrip kosong: Microsite vs TMS saja


def test_ktp_ocr_values_semua_field_ktp_ikut_voting():
    from qc_core.compliance import ntb_verification as nv
    docs = [("ktp", {"nama_ktp": "A", "tempat_lahir": "Bandung", "jenis_kelamin": "LAKI-LAKI", "status_perkawinan_ktp": "KAWIN",
                     "verifications": [{"field": "NIK", "document": "3201010101900001"}, {"field": "Kewarganegaraan", "document": "WNI"}]})]
    k = nv.ktp_ocr_values(docs)
    assert k["nama"] == "A" and k["nik"] == "3201010101900001" and k["kewarganegaraan"] == "WNI" and k["tempat_lahir"] == "Bandung"
    assert nv.ktp_ocr_name(docs) == "A" and nv.ktp_ocr_values([("ktp", {})]) == {}

    def baris(code, tms, ucap_key, ucap, ktp):
        ev = _ev()
        ev["ntb_application_extraction"] = {ucap_key: ucap}
        return next(x for x in nv.build_ntb_data_verification(ev, tms, ktp) if x["item_code"] == code)
    r = baris("SC_NTB_14", {"tempat-lahir": "Bandung"}, "tempat_lahir", "Jakarta", {"tempat_lahir": "Bandung"})
    assert r["match"] == "MATCH" and r["source_value"] == "Bandung"  # KTP = TMS, transkrip beda
    assert baris("SC_NTB_14", {"tempat-lahir": "Bogor"}, "tempat_lahir", "Jakarta", {"tempat_lahir": "Bandung"})["match"] == "MISMATCH"
    assert baris("SC_NTB_10", {"no-ktpkitas": "3201010101900001"}, "no_ktp", "3201010101900009", {"nik": "3201010101900001"})["match"] == "MATCH"
    assert baris("SC_NTB_10", {"no-ktpkitas": "3201010101900001"}, "no_ktp", "3201010101900009", None)["match"] == "MISMATCH"  # tanpa KTP: lama


def test_alamat_rumah_voting_dengan_ktp():
    from qc_core.compliance import ntb_verification as nv
    ev = _ev()
    ev["ntb_application_extraction"] = {"alamat_rumah": "Jalan Melati nomor 5 Cibiru", "kelurahan": "Cibiru", "kecamatan": "Cibiru"}
    tms = {"alamat-rumah-1-new": "JL SENDANG SARI 9", "rumah-kelurahan-new": "BOJONGLOA", "rumah-kecamatan-new": "REGOL"}
    ktp = {"alamat": "Jalan Melati nomor 5 Cibiru", "kelurahan": "Cibiru", "kecamatan": "Cibiru"}
    r = next(x for x in nv.build_ntb_data_verification(ev, tms, ktp) if x["field"] == "alamat_rumah")
    assert r["match"] == "MATCH" and "sepakat" in r["reason"]  # KTP = transkrip, TMS beda
    r = next(x for x in nv.build_ntb_data_verification(ev, tms, None) if x["field"] == "alamat_rumah")
    assert r["match"] == "MISMATCH"


def test_supplement_microsite_voting_jenis_kelamin(tmp_path, monkeypatch):
    from qc_core.compliance import ntb_verification as nv
    (tmp_path / "jenis-kelamin-1-new.csv").write_text("ticket_id,value\nT1,Perempuan\n", encoding="utf-8")
    monkeypatch.setattr(nv, "MICROSITE_DIR", str(tmp_path))

    def baris(ticket, ucap):
        ev = _ev()
        ev["ntb_application_extraction"] = {"kartu_tambahan": [{"nama": "Novia", "jenis_kelamin": ucap, "hubungan": "istri saya"}]}
        return _supl_rows(ev, _supl_tms(**{"result_id": ticket}))["kartu_tambahan_1_jenis_kelamin"]
    r = baris("T1", "Laki-laki")  # TMS = Microsite, transkrip beda -> 2 sumber sepakat
    assert r["match"] == "MATCH" and r["source_value"] == "Perempuan" and any("Voting" in t for t in r["thresholds"])
    assert baris("T2", "Laki-laki")["match"] == "MISMATCH" and baris("T2", "Laki-laki")["source_value"] is None
