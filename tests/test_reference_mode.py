"""Mode teks standar (tanpa master PDF): naskah dibandingkan dengan teks Kemenag bawaan.

PDF uji dibuat dari teks standar itu sendiri (hal. 425–428 mushaf standar: QS 33:51 – 34:7),
lalu satu hal diubah dengan sengaja. Font uji: Amiri Quran (OFL), ada di tests/fonts.
"""
import json
from pathlib import Path

import pymupdf as fitz
import pytest

from quran_checker.reference import DATA_FILE, compare_with_reference, load_reference

FONT = Path(__file__).parent / "fonts" / "AmiriQuran.ttf"
DATA = json.loads(Path(DATA_FILE).read_text(encoding="utf-8"))
AYAT = {(s, a): t for s, a, _p, _j, t in DATA["ayat"]}
BY_PAGE: dict[int, list] = {}
for s, a, p, _j, t in DATA["ayat"]:
    BY_PAGE.setdefault(p, []).append((s, a, t))
NAMES = {x[0]: x[2] for x in DATA["surah"]}
BASMALAH = AYAT[(1, 1)]


def num(a: int) -> str:
    return "".join(chr(0x660 + int(c)) for c in str(a))


def page_lines(p: int) -> list[str]:
    out = []
    for s, a, t in BY_PAGE[p]:
        if a == 1:
            out.append("سورة " + NAMES[s])
            if s not in (1, 9):
                out.append(BASMALAH)
        words = (t + " " + num(a)).split(" ")
        out += [" ".join(words[i:i + 14]) for i in range(0, len(words), 14)]
    return out


def make_pdf(pages: list[list[str]]) -> bytes:
    doc = fitz.open()
    for lines in pages:
        pg = doc.new_page(width=842, height=60 + 22 * len(lines))
        for k, ln in enumerate(lines):
            pg.insert_text((20, 40 + 22 * k), ln, fontfile=str(FONT), fontname="aq", fontsize=9)
    return doc.tobytes()


PAGES = [425, 426, 427, 428]


def run(mutate=None):
    pages = [page_lines(p) for p in PAGES]
    if mutate:
        mutate(pages)
    return compare_with_reference(make_pdf(pages))


def tinggi(res):
    return [f for f in res.findings if f.severity == "Tinggi"]


def test_teks_standar_lengkap():
    ref = load_reference()
    assert sum(1 for s in ref.segs if s[1]) == 6236
    assert sum(1 for s in ref.segs if s[1] == 0) == 112  # basmalah pembuka, kecuali al-Fatihah & at-Taubah


def test_tanpa_perubahan_tidak_ada_temuan_tinggi():
    res = run()
    assert res.mode == "standar"
    assert tinggi(res) == [], [f.message for f in tinggi(res)]
    # halaman dikenali otomatis
    assert "(33):55–62" in res.naskah_pages[1].note
    assert "Nomor ayat terbaca di naskah: 30 (seharusnya 30)." in res.notes


def test_ubah_satu_harakat():
    def m(pages):
        pages[1] = [ln.replace("خَلَوْا", "خِلَوْا") for ln in pages[1]]
    t = tinggi(run(m))
    assert len(t) == 1
    assert t[0].category == "Berubah" and "(33):62" in t[0].message
    assert t[0].detail["master"] == ["َ"] and t[0].detail["naskah"] == ["ِ"]


def test_hapus_satu_kata():
    def m(pages):
        pages[3] = [ln.replace(" الْحَمْدُ", "", 1) for ln in pages[3]]
    t = tinggi(run(m))
    assert [f.category for f in t] == ["Hilang"]
    assert "(34):1" in t[0].message


def test_baris_hilang_di_antara_halaman():
    def m(pages):
        pages[1] = pages[1][:-1]  # baris terakhir hal. 426 dibuang
    t = tinggi(run(m))
    assert [f.category for f in t] == ["Teks hilang di antara halaman"]
    assert t[0].page == 2


def test_nomor_ayat_salah():
    def m(pages):
        pages[2] = [ln.replace(num(64), num(69)) for ln in pages[2]]
    t = tinggi(run(m))
    assert [f.category for f in t] == ["Nomor ayat beda dengan teks standar"]
    assert "[64]" in t[0].message and "[69]" in t[0].message


def test_tukar_tanda_waqaf():
    def m(pages):
        # 33:62 "قَبْلُ ۚوَلَنْ": ۚ (jim) -> ۖ (sala)
        pages[1] = [ln.replace("ۚوَلَنْ", "ۖوَلَنْ") for ln in pages[1]]
    t = tinggi(run(m))
    assert [f.category for f in t] == ["Tanda waqaf/simbol berubah"]


def test_halaman_terbalik_urutannya():
    def m(pages):
        pages[1], pages[2] = pages[2], pages[1]
    cats = {f.category for f in tinggi(run(m))}
    assert {"Teks hilang di antara halaman", "Teks terulang di awal halaman"} & cats


def test_naskah_outline_ditolak_dengan_pesan_jelas():
    doc = fitz.open()
    pg = doc.new_page()
    pg.draw_rect(fitz.Rect(50, 50, 200, 200), color=(0, 0, 0), fill=(0, 0, 0))
    with pytest.raises(ValueError, match="di-outline"):
        compare_with_reference(doc.tobytes())
