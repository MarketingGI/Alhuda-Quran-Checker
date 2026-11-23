"""Mode vektor: master asli (teks outline) dimutasi langsung di level path PDF.

Butuh tests/data/master_426.pdf (halaman 426 dari master). Tes dilewati bila tidak ada.
"""
import pymupdf as fitz
import pytest

from quran_checker.compare import Options, compare_pdfs

from .helpers import MASTER, NASKAH_SALAH, draw_path, mutated_master, paths_inside, processed_master, remove_paths

pytestmark = pytest.mark.skipif(not MASTER.exists(), reason="file master uji tidak ada")
OPT = Options(visual=True, visual_dpi=150)

# Lokasi bentuk di halaman 426 (pt), diperoleh dari ekstraksi master
HARAKAT = (220.0, 234.4, 226.6, 239.0)  # tanda kecil hitam di baris 4
HURUF = (379.6, 760.1, 389.2, 770.5)  # huruf hitam di baris terakhir (sebelah tanda ج)
WAQF_JIM = (370.4, 759.8, 379.1, 770.0)  # tanda waqaf ج (2 path)
WAQF_QALA = (204.3, 223.3, 214.8, 233.8)  # tanda waqaf قلى (2 path)


_BASE = None


def compare(naskah_bytes, base=None):
    """Bandingkan dengan master yang diproses sama (lihat helpers.processed_master)."""
    global _BASE
    if base is None:
        if _BASE is None:
            _BASE = processed_master()
        base = _BASE
    return compare_pdfs(base, naskah_bytes, OPT)


def near(f, rect, pad=4.0):
    r = f.rect
    return r and r[0] <= rect[2] + pad and rect[0] <= r[2] + pad and r[1] <= rect[3] + pad and rect[1] <= r[3] + pad


def test_master_vs_master_bersih():
    data = MASTER.read_bytes()
    assert compare(data, base=data).findings == []


def test_redaksi_kosong_tidak_memicu_temuan():
    # kontrol: alat mutasi (redaksi) sendiri tidak boleh menimbulkan temuan palsu
    res = compare(mutated_master(lambda p: remove_paths(p, (300, 60, 301, 61), pad=0)))
    assert res.findings == []


def test_hapus_satu_harakat():
    def mut(p):
        assert remove_paths(p, HARAKAT) == 1
    res = compare(mutated_master(mut))
    high = [f for f in res.findings if f.severity == "Tinggi"]
    assert len(high) == 1 and high[0].category == "Hilang" and near(high[0], HARAKAT)
    assert "tanda kecil" in high[0].message


def test_hapus_satu_huruf():
    def mut(p):
        assert remove_paths(p, HURUF) == 1
    res = compare(mutated_master(mut))
    high = [f for f in res.findings if f.severity == "Tinggi"]
    assert len(high) == 1 and high[0].category == "Hilang" and near(high[0], HURUF)
    assert "bentuk huruf" in high[0].message


def test_ubah_harakat_jadi_bentuk_lain():
    def mut(p):
        d = paths_inside(p, fitz.Rect(HARAKAT) + (-0.3, -0.3, 0.3, 0.3))[0]
        other = paths_inside(p, fitz.Rect(WAQF_QALA) + (-0.3, -0.3, 0.3, 0.3))
        dot = min(other, key=lambda x: x["rect"].width)  # titik kecil merah
        remove_paths(p, HARAKAT)
        draw_path(p, dot, d["rect"].x0 - dot["rect"].x0, d["rect"].y0 - dot["rect"].y0, fill=d["fill"])
    res = compare(mutated_master(mut))
    high = [f for f in res.findings if f.severity == "Tinggi"]
    assert len(high) == 1 and high[0].category == "Berubah" and near(high[0], HARAKAT)


def test_geser_harakat_ke_bawah():
    def mut(p):
        d = paths_inside(p, fitz.Rect(HARAKAT) + (-0.3, -0.3, 0.3, 0.3))[0]
        remove_paths(p, HARAKAT)
        draw_path(p, d, 0, 4.0)
    res = compare(mutated_master(mut))
    shift = [f for f in res.findings if f.category == "Posisi bergeser"]
    assert len(shift) == 1 and shift[0].severity == "Tinggi"
    assert "4.0 pt ke bawah" in shift[0].message


def test_tukar_tanda_waqaf():
    def mut(p):
        jim = paths_inside(p, fitz.Rect(WAQF_JIM) + (-0.3, -0.3, 0.3, 0.3))
        qala = paths_inside(p, fitz.Rect(WAQF_QALA) + (-0.3, -0.3, 0.3, 0.3))
        assert len(jim) == 2 and len(qala) == 2
        remove_paths(p, WAQF_JIM)
        remove_paths(p, WAQF_QALA)
        for d in jim:
            draw_path(p, d, WAQF_QALA[0] - WAQF_JIM[0], WAQF_QALA[1] - WAQF_JIM[1], fill=qala[0]["fill"])
        for d in qala:
            draw_path(p, d, WAQF_JIM[0] - WAQF_QALA[0], WAQF_JIM[1] - WAQF_QALA[1], fill=jim[0]["fill"])
    res = compare(mutated_master(mut))
    high = [f for f in res.findings if f.severity == "Tinggi"]
    assert any(near(f, WAQF_JIM) for f in high), res.findings
    assert any(near(f, WAQF_QALA) for f in high), res.findings
    assert all(near(f, WAQF_JIM) or near(f, WAQF_QALA) for f in res.findings)


def test_ubah_warna_tajwid():
    def mut(p):
        d = paths_inside(p, fitz.Rect(HURUF) + (-0.3, -0.3, 0.3, 0.3))[0]
        remove_paths(p, HURUF)
        draw_path(p, d, fill=(0.0, 0.65, 0.32))  # hitam -> hijau
    res = compare(mutated_master(mut))
    assert [f.category for f in res.findings] == ["Warna berubah"]
    assert "hitam" in res.findings[0].message and "hijau" in res.findings[0].message


def test_nomor_ayat_diganti():
    """Angka di penanda ayat 61 diganti angka dari penanda ayat 60."""
    def mut(p):
        m60 = fitz.Rect(204.0, 666.0, 232.0, 706.0)
        m61 = fitz.Rect(223.0, 713.0, 251.0, 753.0)
        a = paths_inside(p, m60)
        b = paths_inside(p, m61)
        # angka = path yang bentuknya hanya ada di salah satu penanda
        def sig(d, base):
            return (len(d["items"]), round(d["rect"].width, 1), round(d["rect"].height, 1))
        sa = {sig(d, m60) for d in a}
        sb = {sig(d, m61) for d in b}
        digits60 = [d for d in a if sig(d, m60) not in sb]
        digits61 = [d for d in b if sig(d, m61) not in sa]
        assert digits60 and digits61
        dx, dy = m61.x0 - m60.x0, m61.y0 - m60.y0
        for d in digits61:
            remove_paths(p, d["rect"], pad=0.05)
        for d in digits60:
            draw_path(p, d, dx, dy)
    res = compare(mutated_master(mut))
    m61 = (223.0, 713.0, 251.0, 753.0)
    high = [f for f in res.findings if f.severity == "Tinggi"]
    assert high and all(near(f, m61) for f in high), res.findings
    assert any("penanda ayat" in f.category.lower() or "penanda ayat" in f.message for f in high)


@pytest.mark.skipif(not NASKAH_SALAH.exists(), reason="file naskah uji tidak ada")
def test_file_naskah_ada_salah_dari_tim():
    res = compare(NASKAH_SALAH.read_bytes(), base=MASTER.read_bytes())
    c = sorted(f.category for f in res.findings)
    assert c == ["Glyph terpotong", "Glyph terpotong", "Hilang", "Hilang"]
    cut = [f for f in res.findings if f.category == "Glyph terpotong"]
    assert any("801.5 → 793.4" in f.message for f in cut)  # frame teks naik ±2,9 mm
    hilang = [f for f in res.findings if f.category == "Hilang"]
    assert all("blok latar" in f.message for f in hilang)  # latar krem النبي & قبل
