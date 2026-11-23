"""Alat bantu membuat naskah uji yang sengaja salah."""
from __future__ import annotations

import os
from pathlib import Path

import pymupdf as fitz

from quran_checker.report import find_arabic_font

DATA = Path(__file__).parent / "data"
MASTER = DATA / "master_426.pdf"
NASKAH_SALAH = DATA / "naskah_426_salah.pdf"


# ------------------------------------------------------------ mode vektor
def paths_inside(page: fitz.Page, rect) -> list[dict]:
    r = fitz.Rect(rect)
    return [d for d in page.get_drawings() if r.contains(d["rect"])]


def remove_paths(page: fitz.Page, rect, pad: float = 0.3) -> int:
    """Hapus path yang sepenuhnya di dalam rect (lewat redaksi, clip lain tetap utuh)."""
    r = fitz.Rect(rect) + (-pad, -pad, pad, pad)
    n = len(paths_inside(page, r))
    page.add_redact_annot(r)
    page.apply_redactions(
        images=fitz.PDF_REDACT_IMAGE_NONE,
        graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
        text=fitz.PDF_REDACT_TEXT_NONE,
    )
    return n


def draw_path(page: fitz.Page, d: dict, dx: float = 0, dy: float = 0, fill=None):
    """Gambar ulang satu path hasil get_drawings(), opsional digeser/diganti warna."""
    off = fitz.Point(dx, dy)
    sh = page.new_shape()
    for it in d["items"]:
        op = it[0]
        if op == "l":
            sh.draw_line(it[1] + off, it[2] + off)
        elif op == "c":
            sh.draw_bezier(it[1] + off, it[2] + off, it[3] + off, it[4] + off)
        elif op == "re":
            sh.draw_rect(it[1] + off)
        elif op == "qu":
            q = it[1]
            sh.draw_quad(fitz.Quad(q.ul + off, q.ur + off, q.ll + off, q.lr + off))
    sh.finish(
        fill=fill if fill is not None else d.get("fill"),
        color=d.get("color") if "s" in d["type"] else None,
        even_odd=bool(d.get("even_odd")),
        closePath=bool(d.get("closePath")),
        width=d.get("width") or 0,
        fill_opacity=d.get("fill_opacity") or 1,
    )
    sh.commit(overlay=True)


def _noop(page: fitz.Page):
    # redaksi kosong di pojok halaman: menormalkan efek samping redaksi PyMuPDF
    # (penulisan ulang teks label samping) agar tidak terbaca sebagai temuan
    remove_paths(page, (1, 1, 2, 2), pad=0)


def processed_master() -> bytes:
    """Master yang sudah melewati proses redaksi yang sama dengan naskah mutasi."""
    doc = fitz.open(MASTER)
    _noop(doc[0])
    return doc.tobytes()


def mutated_master(fn) -> bytes:
    """Salin master, terapkan fungsi mutasi pada halaman 1, kembalikan bytes PDF."""
    doc = fitz.open(MASTER)
    _noop(doc[0])
    fn(doc[0])
    return doc.tobytes()


# --------------------------------------------------------------- mode teks
def make_text_pdf(lines: list[str]) -> bytes:
    """PDF satu halaman berisi teks Arab hidup (satu paragraf per baris, tanpa wrap)."""
    font = find_arabic_font()
    if font is None:
        raise RuntimeError("Tidak ada font Arab di sistem untuk membuat PDF uji")
    css = (
        f"@font-face {{font-family: ar; src: url({os.path.basename(font)});}}"
        "body {font-family: ar; font-size: 14pt; direction: rtl; text-align: right;} p {margin: 0 0 10pt 0;}"
    )
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    body = "".join(f"<p>{ln}</p>" for ln in lines)
    page.insert_htmlbox(fitz.Rect(20, 20, 822, 575), body, css=css, archive=fitz.Archive(os.path.dirname(font)))
    return doc.tobytes()
