"""Mode teks: PDF uji dibuat dari teks, lalu satu hal diubah dengan sengaja."""
import pytest

from quran_checker.compare import Options, compare_pdfs
from quran_checker.report import find_arabic_font

from .helpers import make_text_pdf

pytestmark = pytest.mark.skipif(find_arabic_font() is None, reason="butuh font Arab untuk membuat PDF uji")

# Fikstur uji: hanya dipakai untuk membandingkan A dengan A yang dimutasi.
L1 = "مَلْعُوْنِيْنَ ۛ اَيْنَمَا ثُقِفُوْٓا اُخِذُوْا وَقُتِّلُوْا تَقْتِيْلًا ٦١"
L2 = "سُنَّةَ اللّٰهِ فِى الَّذِيْنَ خَلَوْا مِنْ قَبْلُ ۚ وَلَنْ تَجِدَ لِسُنَّةِ اللّٰهِ تَبْدِيْلًا ٦٢"
OPT = Options(visual=False)


def run(lines_naskah):
    return compare_pdfs(make_text_pdf([L1, L2]), make_text_pdf(lines_naskah), OPT)


def cats(res):
    return [(f.category, f.severity) for f in res.findings]


def test_tanpa_perubahan_tidak_ada_temuan():
    res = run([L1, L2])
    assert res.mode == "teks"
    assert res.findings == []


def test_ubah_satu_harakat():
    # fathah pada "خَلَوْا" diganti kasrah
    res = run([L1, L2.replace("خَلَوْا", "خِلَوْا")])
    assert len(res.findings) == 1
    f = res.findings[0]
    assert f.category == "Berubah" and f.severity == "Tinggi"
    assert f.detail["master"] == ["َ"] and f.detail["naskah"] == ["ِ"]
    assert "harakat" in f.message


def test_hapus_satu_huruf():
    res = run([L1, L2.replace("قَبْلُ", "قَلُ")])  # ب dan sukunnya hilang
    assert [f.category for f in res.findings] == ["Hilang"]
    assert sorted(res.findings[0].detail["master"]) == sorted(["ب", "ْ"])


def test_tukar_tanda_waqaf():
    res = run([L1, L2.replace("ۚ", "ۖ")])  # ۚ (jim) -> ۖ (sala)
    assert len(res.findings) == 1
    assert "tanda waqaf" in res.findings[0].message


def test_nomor_ayat_salah():
    res = run([L1, L2.replace("٦٢", "٦٤")])
    c = [f.category for f in res.findings]
    assert "Nomor ayat tidak berurutan" in c
    assert "Nomor ayat beda dengan master" in c


def test_huruf_tambahan():
    res = run([L1.replace("وَقُتِّلُوْا", "وَقُتِّلُوْوا"), L2])
    assert [f.category for f in res.findings] == ["Tambahan"]
