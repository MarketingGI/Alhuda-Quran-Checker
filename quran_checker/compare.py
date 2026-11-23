"""Orkestrasi: buka dua PDF, ekstrak, selaraskan, analisis, kumpulkan temuan."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Optional

import pymupdf as fitz

from . import diff_tokens as dt
from .align import align
from .extract import extract_text_page, extract_vector_page, page_has_arabic_text
from .models import SEVERITY_ORDER, CompareResult, Finding, PageInfo
from .structure import check_text_structure, check_vector_structure
from .visual import visual_findings


@dataclass
class Options:
    visual: bool = True
    visual_dpi: int = 150
    decoration: bool = True
    shifts: bool = True
    force_mode: Optional[str] = None  # 'teks' | 'vektor' | None (otomatis)
    workers: int = 0  # 0 = otomatis (jumlah inti CPU - 1)


def _plausible_char(c: str) -> bool:
    cp = ord(c)
    return (
        0x0600 <= cp <= 0x06FF or 0x0750 <= cp <= 0x077F or 0x08A0 <= cp <= 0x08FF
        or cp < 0x0250 or 0xFD3E <= cp <= 0xFD3F or cp in (0x25CC,)
    )


def open_pdf(data: bytes | str) -> fitz.Document:
    if isinstance(data, (bytes, bytearray)):
        return fitz.open(stream=bytes(data), filetype="pdf")
    return fitz.open(data)


def detect_mode(a: fitz.Document, b: fitz.Document) -> str:
    pages = list(a) + list(b)
    with_text = sum(1 for p in pages if page_has_arabic_text(p))
    return "teks" if with_text == len(pages) else "vektor"


# ------------------------------------------------- ekstraksi paralel per halaman
_WORKER_DOCS: list = []


def _init_worker(master, naskah):
    global _WORKER_DOCS
    _WORKER_DOCS = [open_pdf(master), open_pdf(naskah)]


def _extract_one(args):
    which, pno, mode = args
    page = _WORKER_DOCS[which][pno]
    if mode == "teks":
        return which, pno, extract_text_page(page, pno, 0)
    return which, pno, extract_vector_page(page, pno, 0)


def _extract_all(master, naskah, na: int, nb: int, mode: str, workers: int, prog):
    jobs = [(0, i, mode) for i in range(na)] + [(1, i, mode) for i in range(nb)]
    out = [[None] * na, [None] * nb]
    total = len(jobs)
    n_workers = workers if workers > 0 else max(1, min(8, (os.cpu_count() or 2) - 1))
    if n_workers > 1 and total >= 6:
        try:
            import multiprocessing as mp
            from concurrent.futures import ProcessPoolExecutor

            # 'spawn' = perilaku default Windows; dipakai di semua OS agar konsisten
            ctx = mp.get_context("spawn")
            with ProcessPoolExecutor(n_workers, mp_context=ctx, initializer=_init_worker, initargs=(master, naskah)) as ex:
                for k, (which, pno, res) in enumerate(ex.map(_extract_one, jobs, chunksize=2), 1):
                    out[which][pno] = res
                    prog(0.5 * k / total, f"Mengekstrak halaman {k}/{total} ({n_workers} proses)")
            return out
        except Exception:  # mis. lingkungan tanpa dukungan multiprocessing: jalan serial
            pass
    _init_worker(master, naskah)
    for k, job in enumerate(jobs, 1):
        which, pno, res = _extract_one(job)
        out[which][pno] = res
        prog(0.5 * k / total, f"Mengekstrak halaman {k}/{total}")
    return out


def compare_pdfs(
    master: bytes | str,
    naskah: bytes | str,
    options: Options | None = None,
    progress: Callable[[float, str], None] | None = None,
) -> CompareResult:
    opt = options or Options()
    prog = progress or (lambda f, m: None)
    A, B = open_pdf(master), open_pdf(naskah)
    mode = opt.force_mode or detect_mode(A, B)
    notes = [f"Mode pemeriksaan: {'TEKS (lapisan teks Unicode)' if mode == 'teks' else 'VEKTOR (teks sudah di-outline, dibandingkan per bentuk glyph)'}."]
    if A.page_count != B.page_count:
        notes.append(f"Jumlah halaman beda: master {A.page_count}, naskah {B.page_count}.")
    findings: list[Finding] = []

    a_lines, b_lines, a_info, b_info = [], [], [], []
    a_vp, b_vp = [], []
    pages = _extract_all(master, naskah, A.page_count, B.page_count, mode, opt.workers, prog)
    for which, lines, info, store in ((0, a_lines, a_info, a_vp), (1, b_lines, b_info, b_vp)):
        for i, pg in enumerate(pages[which]):
            for ln in pg.lines:  # nomor baris global (lintas halaman)
                for t in ln:
                    t.line += len(lines)
            lines.extend(pg.lines)
            if mode == "teks":
                info.append(PageInfo(i, "teks", None, sum(len(l) for l in pg.lines)))
            else:
                store.append(pg)
                info.append(PageInfo(i, "vektor", pg.frame, len(pg.all_text)))

    prog(0.55, "Menyelaraskan master dan naskah")
    al = align(a_lines, b_lines)
    prog(0.65, "Menganalisis perbedaan")
    replaced: list = []
    block_findings, extra_pairs = dt.analyze_blocks(al, replaced)
    block_findings = dt.merge_replacements(block_findings)
    pairs = al.pairs + extra_pairs

    a_tokens = [t for l in a_lines for t in l]
    b_tokens = [t for l in b_lines for t in l]
    if mode == "vektor":
        if opt.shifts:
            findings += dt.analyze_pairs(pairs)
        clip_findings = dt.analyze_clipping(pairs, b_tokens, replaced)
        block_findings = dt.drop_covered_by_clipping(block_findings, clip_findings)
        findings += clip_findings
        sf, sn = check_vector_structure(
            [m for vp in a_vp for m in vp.markers], [m for vp in b_vp for m in vp.markers], A.page_count, B.page_count
        )
        findings += sf
        notes += sn
        if opt.decoration:
            for i in range(min(A.page_count, B.page_count)):
                findings += dt.analyze_decoration(a_vp[i].deco, b_vp[i].deco, i, i)
    else:
        for name, toks in (("master", a_tokens), ("naskah", b_tokens)):
            odd = [t.label for t in toks if not _plausible_char(t.label)]
            if odd:
                sample = " ".join(f"U+{ord(c):04X}" for c in sorted(set(odd))[:8])
                notes.append(
                    f"PERINGATAN {name}: {len(odd)} karakter hasil ekstraksi tidak wajar ({sample}). "
                    "Pemetaan font ke Unicode mungkin rusak; hasil mode teks bisa kurang andal, cek juga mode vektor/visual."
                )
        sf, sn = check_text_structure(a_tokens, b_tokens)
        findings += sf
        notes += sn
    findings = block_findings + findings

    if opt.visual:
        n = min(A.page_count, B.page_count)
        for i in range(n):
            prog(0.7 + 0.28 * i / max(1, n), f"Diff visual halaman {i + 1}/{n}")
            known = [f.rect for f in findings if f.page == i and f.rect]
            vf, note = visual_findings(A[i], B[i], i, i, opt.visual_dpi, known)
            findings += vf
            if note:
                notes.append(note)

    findings.sort(key=lambda f: (f.page, f.rect[1] if f.rect else 0, -(f.rect[2] if f.rect else 0), SEVERITY_ORDER[f.severity]))
    for k, f in enumerate(findings, 1):
        f.id = k
    prog(1.0, "Selesai")
    return CompareResult(findings=findings, master_pages=a_info, naskah_pages=b_info, notes=notes, mode=mode)
