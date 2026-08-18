"""Hitung ulang similarity verifikasi STATIK (tanggal_lahir & nama_ibu_kandung) di
Python, tidak lagi mempercayai angka dari LLM.

Kenapa perlu: angka ``similarity_percent`` menentukan tiga hal sekaligus — MATCH vs
MISMATCH, masuk-tidaknya ke zona abu-abu (minta KK/KTP), dan lewat itu AI Status
tiket. Ternyata LLM tidak selalu menghitungnya benar: pada tiket 221111rBUk pasangan
nilai yang PERSIS SAMA ("ARNIYETTI" vs "Sarieti") dilaporkan 44% pada satu run dan
56% pada run berikutnya — yang benar 56 (jarak Levenshtein 4 atas panjang 9). Selisih
12 poin seperti itu bisa memindahkan tiket melewati ambang 80 / 87,5, yaitu antara
"kesalahan agent" dan "cukup minta dokumen".

Yang dihitung di sini HANYA dua field statik, karena hanya keduanya yang punya ambang
zona abu-abu. Field dinamis & cashline dibiarkan apa adanya (aturan pencocokannya
lebih longgar: substring alamat, akumulasi digit telepon, envelope produk — bukan
sekadar Levenshtein, jadi menghitung ulang di sini justru akan salah).

Sekaligus menegakkan aturan TAHAP 2 "pakai penyebutan TERBAIK" (KB v21 / prompt v50)
secara deterministik: setiap penyebutan nasabah diadu ke acuan Ascend dan yang
similarity-nya tertinggi yang dipakai. Seri dimenangkan penyebutan PALING BARU
(elemen terakhir ``extracted_mentions``), sama dengan bunyi aturannya.

TIDAK menyentuh baris yang gugur TAHAP 1 (penyebutan tidak konsisten): di baris itu
``similarity_percent`` berisi kemiripan ANTAR-PENYEBUTAN, bukan terhadap Ascend.
"""
import re

# Bulan Indonesia + Inggris (termasuk singkatan yang lazim muncul di transkrip).
_MONTHS = {
    "januari": 1, "januar": 1, "january": 1, "jan": 1,
    "februari": 2, "pebruari": 2, "february": 2, "feb": 2, "peb": 2,
    "maret": 3, "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "mei": 5, "may": 5,
    "juni": 6, "june": 6, "jun": 6,
    "juli": 7, "july": 7, "jul": 7,
    "agustus": 8, "august": 8, "agu": 8, "agt": 8, "aug": 8,
    "september": 9, "sept": 9, "sep": 9,
    "oktober": 10, "october": 10, "okt": 10, "oct": 10,
    "november": 11, "nopember": 11, "nov": 11,
    "desember": 12, "december": 12, "des": 12, "dec": 12,
}


def levenshtein(a: str, b: str) -> int:
    """Jarak edit klasik (insert/delete/substitute), iteratif dua baris."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _ratio(a: str, b: str) -> "float | None":
    """Similarity 0-100 dari jarak Levenshtein. None bila kedua sisi kosong."""
    n = max(len(a), len(b))
    if n == 0:
        return None
    return (1 - levenshtein(a, b) / n) * 100


def _norm_name(value) -> str:
    """Normalisasi nama: huruf kecil, spasi beruntun dijadikan satu, dipangkas.

    Tanda baca SENGAJA dipertahankan — penyebutan seperti "S-A-R-I-D-A, Farida"
    (nasabah mengeja) memang berbeda dari "Farida", dan menghapus tanda hubungnya
    akan diam-diam menaikkan skornya."""
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _four_digit_year(value: int) -> int:
    """Tahun 2 digit -> 4 digit dengan aturan yang sama dengan prompt: YY > 25 -> 19YY,
    selain itu 20YY."""
    if value >= 100:
        return value
    return 1900 + value if value > 25 else 2000 + value


def to_ddmmyyyy(value) -> "str | None":
    """Bentuk baku 8 digit ``DDMMYYYY`` dari sebuah tanggal lahir, atau None bila tidak
    terbaca — pemanggil membiarkan angka LLM apa adanya ketimbang menebak.

    Menerima: "23 November 1988", "6 Juni 74", "23-11-1988", "23/11/1988",
    "1988-11-23", "19881123" (YYYYMMDD, format Ascend), "23111988" (DDMMYYYY).
    """
    s = str(value or "").strip()
    if not s:
        return None

    # 1) Teks dengan nama bulan.
    m = re.search(r"(\d{1,2})\s*([A-Za-z]+)\s*(\d{2,4})", s)
    if m:
        month = _MONTHS.get(m.group(2).casefold())
        if month:
            day = int(m.group(1))
            year = _four_digit_year(int(m.group(3)))
            if 1 <= day <= 31:
                return f"{day:02d}{month:02d}{year:04d}"

    digits = re.sub(r"\D", "", s)

    # 2) Angka berpemisah: DD-MM-YYYY / YYYY-MM-DD (dan varian "/" atau ".").
    m = re.fullmatch(r"(\d{1,4})\D(\d{1,2})\D(\d{1,4})", s)
    if m:
        a, b, c = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if len(m.group(1)) == 4:           # YYYY-MM-DD
            return f"{c:02d}{b:02d}{a:04d}"
        return f"{a:02d}{b:02d}{_four_digit_year(c):04d}"  # DD-MM-YY(YY)

    # 3) Rangkaian 8 digit: bedakan YYYYMMDD (Ascend) dari DDMMYYYY.
    if len(digits) == 8:
        head, tail = int(digits[:4]), int(digits[4:])
        if 1900 <= head <= 2100:
            return f"{digits[6:8]}{digits[4:6]}{digits[0:4]}"
        if 1900 <= tail <= 2100:
            return digits
    # 4) DDMMYY (6 digit).
    if len(digits) == 6:
        return f"{digits[0:2]}{digits[2:4]}{_four_digit_year(int(digits[4:6])):04d}"
    return None


def similarity_tanggal_lahir(reference, candidate) -> "float | None":
    """Similarity tanggal lahir atas bentuk baku 8 digit DDMMYYYY, TIDAK dibulatkan
    (87.5 dilaporkan 87.5, sesuai prompt). None bila salah satu sisi tidak terbaca."""
    a, b = to_ddmmyyyy(reference), to_ddmmyyyy(candidate)
    if a is None or b is None:
        return None
    return (1 - levenshtein(a, b) / 8) * 100


def similarity_nama(reference, candidate) -> "float | None":
    """Similarity nama ibu kandung, dibulatkan ke bilangan bulat (sesuai prompt)."""
    a, b = _norm_name(reference), _norm_name(candidate)
    value = _ratio(a, b)
    return None if value is None else float(round(value))


# field -> fungsi similarity-nya.
STATIC_SIMILARITY = {
    "tanggal_lahir": similarity_tanggal_lahir,
    "nama_ibu_kandung": similarity_nama,
}


def mention_values(mentions) -> list:
    """Nilai ucapan saja dari ``extracted_mentions``, apa pun bentuknya.

    Sejak prompt v52 tiap elemen berupa objek ``{"timestamp", "value"}`` supaya dua
    ucapan identik di menit berbeda tidak bisa digabung; hasil lama menyimpan string
    telanjang. Keduanya diterima agar tiket lama tetap terbaca."""
    out = []
    for m in mentions or []:
        if isinstance(m, dict):
            value = m.get("value")
        else:
            value = m
        if value is None or str(value).strip() == "":
            continue
        out.append(str(value).strip())
    return out


def mention_rows(mentions) -> list:
    """``[{"timestamp", "value"}]`` yang sudah dirapikan — dipakai tampilan & export.
    Elemen lama (string telanjang) mendapat timestamp kosong."""
    out = []
    for m in mentions or []:
        if isinstance(m, dict):
            value, ts = m.get("value"), (m.get("timestamp") or "")
        else:
            value, ts = m, ""
        if value is None or str(value).strip() == "":
            continue
        out.append({"timestamp": str(ts).strip(), "value": str(value).strip()})
    return out


def best_static_match(field: str, reference, candidates: list) -> "tuple | None":
    """Penyebutan TERBAIK terhadap ``reference`` beserta similarity-nya:
    ``(nilai, similarity)``. None bila tidak ada satu pun yang bisa dihitung.

    Seri dimenangkan penyebutan PALING BARU — daftar ``candidates`` urut dari yang
    paling lama, jadi perbandingannya memakai ``>=``."""
    fn = STATIC_SIMILARITY.get(field)
    if fn is None:
        return None
    best = None
    for cand in candidates:
        if cand is None or str(cand).strip() == "":
            continue
        score = fn(reference, cand)
        if score is None:
            continue
        if best is None or score >= best[1]:
            best = (cand, score)
    return best
