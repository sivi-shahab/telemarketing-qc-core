#!/usr/bin/env python3
"""Bandingkan bentuk prompt LAMA vs BARU — tanpa memanggil LLM sama sekali.

Perubahan 7/10 September 2026 menata ulang blok user message dari
``TRANSCRIPT -> KB -> SCORECARD`` menjadi ``KB -> SCORECARD -> REFERENCE DATA ->
TRANSCRIPT``, dan memisahkan ``reference_text`` dari ``scorecard_text``. Isinya tidak
berubah — hanya letaknya. Skrip ini membuktikan dua hal yang BISA dibuktikan tanpa
model, sehingga reprocess pembanding yang mahal tinggal menjawab satu pertanyaan saja
("apakah vonis modelnya bergeser?"):

1. **ISI IDENTIK.** Untuk tiap tiket nyata, blok-blok kedua bentuk dibandingkan
   byte-per-byte. Kalau ada satu karakter yang berubah, perbedaan hasil model nanti
   tidak bisa lagi diatribusikan ke urutan saja.

2. **AWALAN STABIL.** Prompt caching menagih lebih murah bagian AWAL permintaan yang
   identik dengan permintaan sebelumnya. Skrip ini mengukur panjang awalan yang sama
   antar-tiket berurutan pada kedua bentuk — itulah angka yang seharusnya melonjak,
   dan bisa dibandingkan dengan ``cached_token`` sungguhan setelah deploy.

Pemakaian:
    python tools/bandingkan_bentuk_prompt.py <folder-berisi-PDF-per-tiket> [--kb N] [--sc N]

``--kb``/``--sc`` = ukuran KB & scorecard tiruan dalam ribuan karakter (bawaan mengikuti
ukuran nyata yang tercatat: KB ~24k token, scorecard ~3,8k token).
"""
import argparse
import os
import sys
from os.path import commonprefix

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from qc_core.compliance.evaluator import _build_user_content, format_transcript_for_llm
from qc_core.compliance.pdf_parser import build_transcript


def bentuk_lama(messages, kb, scorecard, files, reference):
    """Bentuk sebelum 7 September: transkrip di DEPAN, reference digabung ke scorecard."""
    transcript = format_transcript_for_llm(messages, files)
    sc = f"{scorecard}\n\n{reference}" if reference.strip() else scorecard
    return f"TRANSCRIPT:\n{transcript}\n\nKB:\n{kb}\n\nSCORECARD:\n{sc}"


def blok(teks):
    """Pecah prompt menjadi ``{nama blok: isi}``."""
    out, nama, buf = {}, None, []
    for baris in teks.split("\n"):
        if baris.endswith(":") and baris[:-1].isupper() and " " not in baris.strip(":").replace(" DATA", ""):
            if nama:
                out[nama] = "\n".join(buf).strip()
            nama, buf = baris[:-1], []
        else:
            buf.append(baris)
    if nama:
        out[nama] = "\n".join(buf).strip()
    return out


def tiket_dari(folder):
    """``{ticket_id: [pdf, ...]}`` — satu folder per tiket, atau PDF datar."""
    hasil = {}
    for akar, _dirs, berkas in os.walk(folder):
        pdf = sorted(os.path.join(akar, b) for b in berkas if b.lower().endswith(".pdf"))
        if pdf:
            hasil[os.path.basename(akar)] = pdf
    return dict(sorted(hasil.items()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--kb", type=int, default=97, help="ukuran KB tiruan, ribuan karakter")
    ap.add_argument("--sc", type=int, default=15, help="ukuran scorecard tiruan, ribuan karakter")
    ap.add_argument("--maks", type=int, default=10, help="maksimal tiket yang diperiksa")
    a = ap.parse_args()

    kb = ("KB " * 500 + "\n") * (a.kb * 1000 // 2001 or 1)
    scorecard = ("SC " * 500 + "\n") * (a.sc * 1000 // 2001 or 1)

    tikets = list(tiket_dari(a.folder).items())[: a.maks]
    if not tikets:
        print(f"Tidak ada PDF di {a.folder}")
        return 1

    print(f"KB tiruan {len(kb):,} karakter | scorecard tiruan {len(scorecard):,} karakter")
    print(f"{len(tikets)} tiket diperiksa\n")

    lama_semua, baru_semua, beda_isi = [], [], []
    for tid, pdfs in tikets:
        files, messages, _durasi, _per_file = build_transcript(pdfs)
        reference = f"=== REFERENCE DATA {tid} ===\nnama: NASABAH {tid}\nlimit: 45000000"

        lama = bentuk_lama(messages, kb, scorecard, files, reference)
        baru = _build_user_content(messages, kb, scorecard, files, reference)
        lama_semua.append(lama)
        baru_semua.append(baru)

        bl, bb = blok(lama), blok(baru)
        # Dibandingkan PER BAGIAN, bukan dengan merangkai ulang bentuk lama: merangkai
        # ulang memasukkan spasi-putih penyambung buatan skrip ini sendiri ke dalam
        # perbandingan, dan yang ingin dibuktikan adalah ISI blok, bukan cara skrip ini
        # menyambungnya.
        masalah = []
        if bl.get("KB") != bb.get("KB"):
            masalah.append("KB")
        if bl.get("TRANSCRIPT") != bb.get("TRANSCRIPT"):
            masalah.append("TRANSCRIPT")
        if bb.get("SCORECARD") != scorecard.strip():
            masalah.append("SCORECARD (baru)")
        if bb.get("REFERENCE DATA") != reference.strip():
            masalah.append("REFERENCE DATA (baru)")
        # Bentuk lama: scorecard lalu reference, menempel dalam SATU blok tanpa label.
        sc_lama = bl.get("SCORECARD", "")
        if not sc_lama.startswith(scorecard.strip()) or not sc_lama.endswith(reference.strip()):
            masalah.append("SCORECARD (lama)")
        if masalah:
            beda_isi.append((tid, masalah))
        print(f"  {tid:<14} {len(files)} PDF  lama={len(lama):>8,}  baru={len(baru):>8,}"
              f"  selisih {len(baru) - len(lama):+d}  {'ISI SAMA' if not masalah else 'ISI BEDA!'}")

    print()
    if beda_isi:
        print("GAGAL — isi blok BERUBAH, bukan cuma urutannya:")
        for tid, beda in beda_isi:
            print(f"   {tid}: {beda}")
        return 1
    selisih = {len(b) - len(l) for l, b in zip(lama_semua, baru_semua)}
    label = len("REFERENCE DATA:\n")
    print("1) ISI IDENTIK di seluruh tiket: blok KB, SCORECARD, TRANSCRIPT dan teks")
    print("   reference sama BYTE-PER-BYTE. Yang berubah hanya letaknya.\n")
    print(f"   Satu-satunya tambahan teks: LABEL blok \"REFERENCE DATA:\" ({label} karakter)")
    print(f"   yang dulu tidak ada — reference data dulu menempel di ekor SCORECARD tanpa")
    print(f"   judul sendiri. Selisih panjang prompt terukur: {sorted(selisih)} karakter,")
    print(f"   {'konsisten' if len(selisih) == 1 else 'TIDAK konsisten — periksa'} di seluruh tiket.\n")

    def awalan_rata(daftar):
        if len(daftar) < 2:
            return 0
        return sum(len(commonprefix([daftar[i], daftar[i + 1]])) for i in range(len(daftar) - 1)) // (len(daftar) - 1)

    al, ab = awalan_rata(lama_semua), awalan_rata(baru_semua)
    rata_lama = sum(map(len, lama_semua)) // len(lama_semua)
    print("2) AWALAN YANG SAMA antar-tiket berurutan (dasar prompt caching):")
    print(f"   bentuk LAMA : {al:>8,} karakter  ({al * 100 // max(rata_lama, 1)}% dari prompt)")
    print(f"   bentuk BARU : {ab:>8,} karakter  ({ab * 100 // max(rata_lama, 1)}% dari prompt)")
    print(f"   selisih     : {ab - al:>+8,} karakter")
    print("\n   Angka inilah yang seharusnya tercermin sebagai lonjakan ``cached_token``")
    print("   pada panggilan ke-2 dan seterusnya setelah deploy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
