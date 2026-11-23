"""Gambar perbandingan dan ekspor laporan PDF untuk tim editor."""
from __future__ import annotations

import datetime as _dt
import html
import os
from collections import Counter

import cv2
import numpy as np
import pymupdf as fitz

from .models import CompareResult, Finding, Rect

SEV_RGB = {"Tinggi": (220, 30, 30), "Sedang": (240, 130, 0), "Rendah": (40, 110, 220)}
SEV_PDF = {k: tuple(c / 255 for c in v) for k, v in SEV_RGB.items()}

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\tahoma.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
]


def find_arabic_font() -> str | None:
    for f in FONT_CANDIDATES:
        if os.path.exists(f):
            return f
    return None


# ----------------------------------------------------------------- gambar
def _render(doc: fitz.Document, pno: int, clip: Rect | None, dpi: int) -> np.ndarray:
    page = doc[pno]
    pix = page.get_pixmap(dpi=dpi, clip=fitz.Rect(clip) if clip else None, alpha=False)
    return np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, pix.n)[:, :, :3].copy()


def _expand(r: Rect, pad: float, page_rect: fitz.Rect, min_w: float = 0, min_h: float = 0) -> Rect:
    x0, y0, x1, y1 = r
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    w = max(x1 - x0 + 2 * pad, min_w)
    h = max(y1 - y0 + 2 * pad, min_h)
    out = fitz.Rect(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2) & page_rect
    return (out.x0, out.y0, out.x1, out.y1)


def crop_with_box(doc: fitz.Document, pno: int, rect: Rect | None, sev: str, dpi: int = 200, view: Rect | None = None) -> np.ndarray:
    """Potongan halaman di sekitar temuan, dengan kotak penanda."""
    page_rect = doc[pno].rect
    if rect is None:
        return _render(doc, pno, None, 60)
    v = view or _expand(rect, 14, page_rect, min_w=160, min_h=60)
    img = _render(doc, pno, v, dpi)
    s = dpi / 72
    x0, y0 = int((rect[0] - v[0]) * s), int((rect[1] - v[1]) * s)
    x1, y1 = int((rect[2] - v[0]) * s), int((rect[3] - v[1]) * s)
    cv2.rectangle(img, (x0 - 4, y0 - 4), (x1 + 4, y1 + 4), SEV_RGB.get(sev, (220, 30, 30)), 3)
    return img


def side_by_side(master_doc, naskah_doc, f: Finding, dpi: int = 200) -> tuple[np.ndarray | None, np.ndarray]:
    """Crop master & naskah dengan jendela yang sama besar agar mudah dibandingkan."""
    n_rect = f.rect
    view_n = _expand(n_rect, 14, naskah_doc[f.page].rect, min_w=160, min_h=60) if n_rect else None
    nimg = crop_with_box(naskah_doc, f.page, n_rect, f.severity, dpi, view_n)
    mimg = None
    if master_doc is not None and f.master_page is not None and f.master_page < master_doc.page_count:
        m_rect = f.master_rect or n_rect
        if m_rect is not None:
            if view_n:
                # jendela master: ukuran sama, digeser sesuai posisi temuan di master
                dx, dy = m_rect[0] - n_rect[0], m_rect[1] - n_rect[1]
                view_m = (view_n[0] + dx, view_n[1] + dy, view_n[2] + dx, view_n[3] + dy)
            else:
                view_m = None
            mimg = crop_with_box(master_doc, f.master_page, m_rect, "Rendah", dpi, view_m)
    return mimg, nimg


def _place_label(placed: list, x0: float, y0: float, w: float, h: float, step: float) -> tuple[float, float]:
    """Cari posisi label yang tidak menimpa label lain (geser ke bawah, lalu ke kanan)."""
    for col in range(6):
        x = x0 + col * (w + 1)
        y = y0
        for _ in range(12):
            r = (x, y, x + w, y + h)
            if not any(r[0] < q[2] and q[0] < r[2] and r[1] < q[3] and q[1] < r[3] for q in placed):
                placed.append(r)
                return x, y
            y += step
    placed.append((x0, y0, x0 + w, y0 + h))
    return x0, y0


def page_with_boxes(doc: fitz.Document, pno: int, findings: list[Finding], dpi: int = 110) -> np.ndarray:
    img = _render(doc, pno, None, dpi)
    s = dpi / 72
    mine = [f for f in findings if f.page == pno and f.rect is not None]
    for f in mine:  # kotak dulu, baru label, supaya label tidak tertutup kotak lain
        x0, y0, x1, y1 = (int(v * s) for v in f.rect)
        cv2.rectangle(img, (x0 - 3, y0 - 3), (x1 + 3, y1 + 3), SEV_RGB[f.severity], 2)
    placed: list = []
    for f in mine:
        c = SEV_RGB[f.severity]
        x0, y0, x1, y1 = (int(v * s) for v in f.rect)
        label = str(f.id)
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        lx, ly = _place_label(placed, x1 + 4, y0 - 3, tw + 6, th + 6, th + 8)
        lx, ly = int(lx), int(ly)
        cv2.rectangle(img, (lx, ly), (lx + tw + 6, ly + th + 6), c, -1)
        cv2.putText(img, label, (lx + 3, ly + th + 3), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return img


def to_jpg(img: np.ndarray, max_w: int = 1400, quality: int = 85) -> bytes:
    """JPEG untuk laporan: jauh lebih kecil dari PNG, tetap tajam untuk dibaca editor."""
    if img.shape[1] > max_w:
        img = cv2.resize(img, (max_w, int(img.shape[0] * max_w / img.shape[1])), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", cv2.cvtColor(img, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes()


def to_png(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    return buf.tobytes()


# ------------------------------------------------------------- laporan PDF
CSS = """
* { font-family: ar, sans-serif; }
body { font-size: 9pt; color: #222; }
h1 { font-size: 15pt; margin: 0 0 4pt 0; }
h2 { font-size: 11pt; margin: 0 0 3pt 0; }
.muted { color: #666; }
.sev { font-weight: bold; }
td, th { border: 0.5pt solid #bbb; padding: 2pt 4pt; font-size: 9pt; }
table { border-collapse: collapse; }
.ar { direction: rtl; font-size: 13pt; }
"""


def _htmlbox(page: fitz.Page, rect: fitz.Rect, body: str, archive, css: str) -> float:
    """Tulis HTML ke halaman, kembalikan tinggi yang terpakai."""
    spare, scale = page.insert_htmlbox(rect, body, css=css, archive=archive)
    if spare < 0:
        return rect.height
    return rect.height - spare


def build_report_pdf(master: bytes | str | None, naskah: bytes | str, result: CompareResult, master_name: str, naskah_name: str) -> bytes:
    """master=None: mode teks standar (tanpa master PDF)."""
    from .compare import open_pdf

    A, B = (open_pdf(master) if master else None), open_pdf(naskah)
    std = A is None
    L_MASTER = "Teks standar" if std else "Master"
    font = find_arabic_font()
    archive = None
    css = CSS
    if font:
        archive = fitz.Archive(os.path.dirname(font))
        css = f"@font-face {{font-family: ar; src: url({os.path.basename(font)});}}\n" + CSS
    out = fitz.open()
    out.set_metadata({"title": "Alhuda Quran Checker - Laporan Pemeriksaan Naskah", "creator": "Alhuda Quran Checker"})
    W, H, M = 595, 842, 36

    # --- halaman ringkasan
    page = out.new_page(width=W, height=H)
    sev = Counter(f.severity for f in result.findings)
    rows = "".join(
        f"<tr><td>{f.id}</td><td>{f.page + 1}</td><td class='sev' style='color:rgb{SEV_RGB[f.severity]}'>{f.severity}</td>"
        f"<td>{html.escape(f.category)}</td></tr>"
        for f in result.findings[:60]
    )
    more = f"<p class='muted'>… dan {len(result.findings) - 60} temuan lain di halaman berikutnya.</p>" if len(result.findings) > 60 else ""
    notes = "".join(f"<li>{html.escape(n)}</li>" for n in result.notes)
    body = f"""
    <h1>Alhuda Quran Checker — Laporan Pemeriksaan Naskah</h1>
    <p class='muted'>Dibuat {_dt.datetime.now():%d-%m-%Y %H:%M} · pembanding deterministik (tanpa AI)</p>
    <p><b>{L_MASTER}:</b> {html.escape(master_name)}{'' if std else f' ({A.page_count} hal.)'}<br/>
    <b>Naskah:</b> {html.escape(naskah_name)} ({B.page_count} hal.)</p>
    <p><b>Total temuan: {len(result.findings)}</b> —
    <span style='color:rgb{SEV_RGB["Tinggi"]}'>Tinggi {sev.get("Tinggi", 0)}</span> ·
    <span style='color:rgb{SEV_RGB["Sedang"]}'>Sedang {sev.get("Sedang", 0)}</span> ·
    <span style='color:rgb{SEV_RGB["Rendah"]}'>Rendah {sev.get("Rendah", 0)}</span></p>
    <ul>{notes}</ul>
    <h2>Daftar temuan</h2>
    <table><tr><th>No</th><th>Hal.</th><th>Keparahan</th><th>Kategori</th></tr>{rows}</table>{more}
    """
    _htmlbox(page, fitz.Rect(M, M, W - M, H - M), body, archive, css)

    # --- detail per temuan: teks + crop master | naskah
    page = out.new_page(width=W, height=H)
    y = M
    col_w = (W - 2 * M - 12) / 2
    for f in result.findings:
        mimg, nimg = side_by_side(A, B, f, dpi=170)
        wide = nimg.shape[1] / nimg.shape[0] > 3  # temuan selebar baris: susun atas-bawah
        cw = (W - 2 * M) if wide else col_w

        def h_of(img):
            return 0 if img is None else cw * img.shape[0] / img.shape[1]

        img_h = min(max(h_of(mimg), h_of(nimg)), 220)
        block_h = (2 * (img_h + 11) + 4) if wide else img_h
        if std:  # tanpa master PDF: hanya crop naskah, selebar halaman
            wide, cw = True, W - 2 * M
            img_h = min(h_of(nimg), 220)
            block_h = img_h + 11
        arab = ""
        if f.detail.get("master") or f.detail.get("naskah"):
            arab = (
                f"<p>Naskah: <span class='ar'>{html.escape(''.join(f.detail.get('naskah', [])) or '-')}</span> &nbsp; "
                f"{L_MASTER}: <span class='ar'>{html.escape(''.join(f.detail.get('master', [])) or '-')}</span></p>"
            )
        text = (
            f"<h2><span style='color:rgb{SEV_RGB[f.severity]}'>#{f.id} [{f.severity}]</span> "
            f"{html.escape(f.category)} — hal. naskah {f.page + 1}"
            + (f", hal. master {f.master_page + 1}" if f.master_page is not None else "")
            + f"</h2><p>{html.escape(f.message)}</p>{arab}"
        )
        need = 80 + block_h + 20
        if y + need > H - M:
            page = out.new_page(width=W, height=H)
            y = M
        used = _htmlbox(page, fitz.Rect(M, y, W - M, y + 120), text, archive, css)
        y += used + 4
        for k, (img, lab) in enumerate(((nimg, "NASKAH"),) if std else ((nimg, "NASKAH"), (mimg, "MASTER"))):
            if lab is None:
                continue
            if std:
                k = 0
            if wide:
                x, yy = M, y + k * (img_h + 15)
            else:
                x, yy = M + k * (col_w + 12), y
            page.insert_text((x, yy + 8), lab, fontsize=7, fontname="hebo",
                             color=(0.18, 0.44, 0.84) if lab == "MASTER" else (0.33, 0.33, 0.33))
            if img is not None:
                ih = min(h_of(img), 220)
                iw = img.shape[1] * ih / img.shape[0]
                ir = fitz.Rect(x, yy + 11, x + iw, yy + 11 + ih)
                page.insert_image(ir, stream=to_jpg(img))
                # bingkai: biru = master, abu tua = naskah, agar dua potongan tidak menyatu
                frame = (0.18, 0.44, 0.84) if lab == "MASTER" else (0.33, 0.33, 0.33)
                page.draw_rect(ir + (-1.5, -1.5, 1.5, 1.5), color=frame, width=2)
            else:
                page.insert_text((x, yy + 24), "(tidak ada pasangan di master)", fontsize=8, fontname="helv")
        y += (block_h + 4 if wide else 11 + img_h) + 16
        page.draw_line((M, y - 8), (W - M, y - 8), color=(0.85, 0.85, 0.85), width=0.5)

    # --- halaman naskah beranotasi (vektor asli, hanya halaman yang punya temuan)
    pages = sorted({f.page for f in result.findings if f.rect is not None})
    for p in pages:
        out.insert_pdf(B, from_page=p, to_page=p)
        pg = out[-1]
        placed: list = []
        for f in result.findings:
            if f.page != p or f.rect is None:
                continue
            r = fitz.Rect(f.rect) + (-2, -2, 2, 2)
            col = SEV_PDF[f.severity]
            a = pg.add_rect_annot(r)
            a.set_colors(stroke=col)
            a.set_border(width=1.4)
            a.set_info(title=f"Temuan #{f.id} [{f.severity}]", content=f"{f.category}: {f.message}")
            a.update()
            lw = 5 + 5 * len(str(f.id))
            lx, ly = _place_label(placed, r.x1 + 1, r.y0 - 1, lw, 11, 12)
            lab = fitz.Rect(lx, ly, lx + lw, ly + 11)
            pg.draw_rect(lab, color=col, fill=col)
            pg.insert_text((lab.x0 + 2.5, lab.y1 - 2.5), str(f.id), fontsize=8, fontname="hebo", color=(1, 1, 1))
    try:
        out.subset_fonts()  # tiap blok teks menyematkan font; pangkas ke glyph yang dipakai saja
    except Exception:
        pass
    return out.tobytes(garbage=4, deflate=True)
