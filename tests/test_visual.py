"""Diff visual: geseran sub-piksel/anti-aliasing tidak boleh jadi temuan, perubahan kecil yang nyata harus."""
from pathlib import Path

import pymupdf as fitz
import pytest

from quran_checker.visual import visual_findings

FONT = str(Path(__file__).parent / "fonts" / "AmiriQuran.ttf")
T = "قَصَمْنَا مِنْ قَرْيَةٍ كَانَتْ ظَالِمَةً وَّاَنْشَأْنَا بَعْدَهَا قَوْمًا اٰخَرِيْنَ"


def page(dx=0.0, dy=0.0, mark_dy=0.0, mark=True, dot=True, cream=True, color=(0, 0.5, 0.2)):
    d = fitz.open()
    p = d.new_page(width=500, height=200)
    if cream:
        p.draw_rect(fitz.Rect(40, 30, 200, 60), fill=(1, 0.96, 0.85), color=None)
    p.insert_text((30 + dx, 50 + dy), T, fontfile=FONT, fontname="aq", fontsize=18)
    p.insert_text((30 + dx, 100 + dy), T, fontfile=FONT, fontname="aq", fontsize=18, color=color)
    if mark:  # tanda kecil seukuran fathah
        p.draw_rect(fitz.Rect(300, 130 + mark_dy, 303, 131.2 + mark_dy), fill=(0, 0, 0), color=None)
    if dot:  # titik seukuran titik huruf kecil
        p.draw_circle(fitz.Point(350, 130), 0.6, fill=(0, 0, 0), color=None)
    return fitz.open(stream=d.tobytes(), filetype="pdf")[0]


MASTER = page()


@pytest.mark.parametrize("dpi", [100, 150, 200])
@pytest.mark.parametrize("name,naskah,expected", [
    ("sama persis", dict(), 0),
    ("teks geser 0,15 pt (derau render)", dict(dx=0.15, dy=0.1), 0),
    ("teks geser 0,3 pt (derau render)", dict(dx=0.3, dy=0.25), 0),
    ("tanda kecil hilang", dict(mark=False), 1),
    ("titik kecil hilang", dict(dot=False), 1),
    ("tanda turun 1,5 pt", dict(mark_dy=1.5), 1),
    ("latar krem hilang", dict(cream=False), 1),
    ("warna tajwid beda", dict(color=(0.8, 0, 0.4)), 1),
])
def test_diff_visual(dpi, name, naskah, expected):
    found, _ = visual_findings(MASTER, page(**naskah), 0, 0, dpi, [])
    assert len(found) == expected, name
