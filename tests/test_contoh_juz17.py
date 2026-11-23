"""Uji dengan file contoh asli dari tim (juz 17 hal. 323), bila ada di folder ~test-file.

Regresi untuk dua temuan palsu yang pernah muncul:
- 'Beda visual' karena derau render (anti-aliasing) di area yang sebenarnya sama;
- 'Bentuk berubah halus' pada penanda ayat karena urutan path di PDF berbeda.
"""
from pathlib import Path

import pytest

from quran_checker.compare import Options, compare_pdfs

DIR = Path(__file__).parent.parent / "~test-file"
MASTER = DIR / "juz 17 MUSHAF_4 WARNA (TERJEMAH)_GIP_majiid 323 a.pdf"
SALAH = DIR / "juz 17 MUSHAF_4 WARNA (TERJEMAH)_GIP_majiid 323 a (salah).pdf"

pytestmark = pytest.mark.skipif(not (MASTER.exists() and SALAH.exists()), reason="file contoh juz 17 tidak ada")


def test_master_vs_master_bersih():
    assert compare_pdfs(str(MASTER), str(MASTER), Options(workers=1)).findings == []


def test_salah_tanpa_temuan_palsu():
    res = compare_pdfs(str(MASTER), str(SALAH), Options(workers=1))
    cats = [f.category for f in res.findings]
    assert "Beda visual" not in cats
    assert "Bentuk berubah halus" not in cats
    assert sum(f.severity == "Tinggi" for f in res.findings) >= 6


def test_bentuk_identik_tidak_jadi_berubah():
    """Penanda ayat 19: bentuk sama tapi terlempar ke blok tetangga oleh penyelarasan."""
    res = compare_pdfs(str(MASTER), str(SALAH), Options(workers=1))
    for f in res.findings:
        if f.category == "Berubah":
            lhs, _, rhs = f.message.partition("Master: ")[2].partition(" → naskah: ")
            assert lhs != rhs, f.message


def test_temuan_penanda_punya_pasangan_master():
    res = compare_pdfs(str(MASTER), str(SALAH), Options(workers=1))
    marks = [f for f in res.findings if "penanda ayat" in f.category or f.category == "Glyph terpotong"]
    assert marks
    for f in marks:
        assert f.master_page is not None and f.master_rect is not None, f.message
    # satu penanda cukup dilaporkan sekali
    rects = [tuple(round(v) for v in f.rect) for f in marks]
    assert len(rects) == len(set(rects))
