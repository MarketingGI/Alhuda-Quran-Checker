"""Diff visual: render halaman ke gambar, tandai area piksel yang berbeda."""
from __future__ import annotations

import cv2
import numpy as np
import pymupdf as fitz

from .extract import render_page
from .models import Finding, Rect

PIXEL_THRESHOLD = 20  # beda intensitas (0-255); cukup rendah untuk menangkap blok latar pucat (krem vs putih ≈ 36)
MAX_CHANGED_FRACTION = 0.05  # di atas ini halaman dianggap reflow, diff visual dilewati


def _estimate_shift(a: np.ndarray, b: np.ndarray) -> tuple[int, int]:
    ga = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY).astype(np.float32)
    gb = cv2.cvtColor(b, cv2.COLOR_RGB2GRAY).astype(np.float32)
    (dx, dy), _ = cv2.phaseCorrelate(ga, gb)
    return int(round(dx)), int(round(dy))


NEIGHBOR = 1  # toleransi geseran sub-piksel/anti-aliasing (piksel) saat membandingkan
MIN_CHANGED_PX = 6  # area beda yang lebih kecil dari ini dianggap derau render


def _outside_range(x: np.ndarray, ref: np.ndarray, k: int) -> np.ndarray:
    """True bila nilai x di luar rentang [min, max] tetangga ref (jendela (2k+1)²) lebih dari ambang."""
    ker = np.ones((2 * k + 1, 2 * k + 1), np.uint8)
    lo = cv2.erode(ref, ker).astype(np.int16)
    hi = cv2.dilate(ref, ker).astype(np.int16)
    xi = x.astype(np.int16)
    return ((xi < lo - PIXEL_THRESHOLD) | (xi > hi + PIXEL_THRESHOLD)).any(axis=2)


def diff_regions(a: np.ndarray, b: np.ndarray, min_area_px: int = MIN_CHANGED_PX) -> tuple[list[tuple[int, int, int, int]], float, tuple[int, int]]:
    """Kembalikan kotak beda (piksel, koordinat b), fraksi piksel berubah, dan geseran global.

    Piksel dianggap beda hanya bila nilainya tidak ditemukan di sekitar posisi yang sama
    pada gambar lain (dicek dua arah). Dengan begitu tepi huruf yang bergeser sepersekian
    piksel atau anti-aliasing yang sedikit beda tidak dilaporkan, tapi tanda yang hilang,
    bertambah, atau berubah warna tetap terdeteksi.
    """
    dx, dy = _estimate_shift(a, b)
    if abs(dx) > 0 or abs(dy) > 0:
        m = np.float32([[1, 0, dx], [0, 1, dy]])
        a = cv2.warpAffine(a, m, (b.shape[1], b.shape[0]), borderValue=(255, 255, 255))
    # sedikit dihaluskan: garis tipis 1 piksel yang bergeser sepersekian piksel jadi sebanding
    sa = cv2.GaussianBlur(a, (3, 3), 0.8)
    sb = cv2.GaussianBlur(b, (3, 3), 0.8)
    raw = (_outside_range(sb, sa, NEIGHBOR) | _outside_range(sa, sb, NEIGHBOR)).astype(np.uint8)
    frac = float(raw.mean())
    mask = cv2.dilate(raw, np.ones((7, 7), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    if n <= 1:
        return [], frac, (dx, dy)
    # jumlah piksel beda ASLI (sebelum dilasi) per area; area kecil = derau render
    counts = np.bincount(labels[raw > 0], minlength=n)
    boxes = [tuple(int(v) for v in stats[i][:4]) for i in range(1, n) if counts[i] >= min_area_px]
    return boxes, frac, (dx, dy)


def _overlaps(r: Rect, others: list[Rect], pad: float) -> bool:
    for o in others:
        if r[0] <= o[2] + pad and o[0] <= r[2] + pad and r[1] <= o[3] + pad and o[1] <= r[3] + pad:
            return True
    return False


def visual_findings(
    a_page: fitz.Page,
    b_page: fitz.Page,
    page_index: int,
    master_index: int,
    dpi: int,
    known: list[Rect],
) -> tuple[list[Finding], str]:
    if abs(a_page.rect.width - b_page.rect.width) > 1 or abs(a_page.rect.height - b_page.rect.height) > 1:
        return [], f"Hal. {page_index + 1}: ukuran halaman beda, diff visual dilewati."
    a = render_page(a_page, dpi)
    b = render_page(b_page, dpi)
    if a.shape != b.shape:
        b = cv2.resize(b, (a.shape[1], a.shape[0]))
    boxes, frac, (dx, dy) = diff_regions(a, b)
    note = ""
    if frac > MAX_CHANGED_FRACTION:
        return [], (
            f"Hal. {page_index + 1}: {frac:.0%} piksel berbeda (kemungkinan reflow/tata letak bergeser); "
            "diff visual dilewati, andalkan diff glyph/teks."
        )
    if dx or dy:
        note = f"Hal. {page_index + 1}: seluruh halaman bergeser {dx},{dy} px, sudah dikoreksi sebelum diff visual."
    s = dpi / 72.0
    out = []
    from .diff_tokens import _cluster_rects

    rects = [(x / s, y / s, (x + w) / s, (y + h) / s) for x, y, w, h in boxes]
    for r in _cluster_rects(rects, gap=3.0):
        if _overlaps(r, known, pad=3.0):
            continue  # sudah dijelaskan temuan lain
        out.append(
            Finding(
                category="Beda visual",
                severity="Sedang",
                message="Tampilan berbeda dari master di area ini (mis. glyph tumpang tindih, fallback font, posisi tanda, atau elemen grafis).",
                page=page_index,
                rect=r,
                master_page=master_index,
                master_rect=r,
                check="visual",
            )
        )
    return out, note
