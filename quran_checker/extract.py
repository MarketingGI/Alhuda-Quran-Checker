"""Ekstraksi isi halaman PDF menjadi token yang bisa dibandingkan.

Dua jalur:
- Mode teks: PDF punya lapisan teks Arab (teks hidup) -> token per karakter.
- Mode vektor: teks mushaf sudah di-outline (kurva) -> token per path/bentuk.
  Bentuk yang sama dari font yang sama menghasilkan sidik bentuk yang sama,
  di posisi mana pun ia berada. Inilah yang membuat diff tetap jalan walau reflow.
"""
from __future__ import annotations

import statistics
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass

import pymupdf as fitz

from .models import Rect, Token
from .normalize import INVISIBLE, normalize_text

ARABIC_MIN_CHARS = 30


# --------------------------------------------------------------------- umum
def _r(rect) -> Rect:
    return (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))


def count_arabic_chars(page: fitz.Page) -> int:
    text = page.get_text("text")
    return sum(
        1
        for c in text
        if "؀" <= c <= "ۿ" or "ݐ" <= c <= "ݿ" or "ﭐ" <= c <= "﻿"
    )


def page_has_arabic_text(page: fitz.Page) -> bool:
    return count_arabic_chars(page) >= ARABIC_MIN_CHARS


def _center(r: Rect) -> tuple[float, float]:
    return ((r[0] + r[2]) / 2, (r[1] + r[3]) / 2)


def _inside(pt, r: Rect) -> bool:
    return r[0] <= pt[0] <= r[2] and r[1] <= pt[1] <= r[3]


def _area(r: Rect) -> float:
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


# ------------------------------------------------------------- mode vektor
@dataclass
class RawPath:
    d: dict
    rect: Rect
    clip: Rect | None
    types: str
    raw: tuple  # (items, ox, oy, lebar garis); koordinat presisi dihitung bila perlu
    color: tuple
    stroke: tuple
    kind: str  # 'f', 's', 'fs'


def compute_fine(raw: tuple) -> tuple:
    """Koordinat path relatif terhadap pojok kiri-atas bentuknya (sidik bentuk presisi)."""
    items, ox, oy, width = raw
    fine = []
    for it in items:
        for q in it[1:]:
            if not isinstance(q, tuple):
                continue  # mis. orientasi persegi
            if q and isinstance(q[0], tuple):  # quad: 4 titik
                for p in q:
                    fine += [p[0] - ox, p[1] - oy]
            elif len(q) == 2:  # titik
                fine += [q[0] - ox, q[1] - oy]
            elif len(q) == 4:  # persegi
                fine += [q[0] - ox, q[1] - oy, q[2] - ox, q[3] - oy]
    if width is not None:
        fine.append(width)
    return tuple(fine)


def ensure_fine(t: Token) -> Token:
    if not t.fine and t.raw:
        t.fine = compute_fine(t.raw)
    return t


def _q(v, step):
    return round(v / step) * step


def _color(c):
    return tuple(round(x, 2) for x in c) if c else ()


def _walk(page: fitz.Page) -> list[RawPath]:
    """Telusuri semua gambar vektor sambil melacak clip efektif tiap path."""
    out: list[RawPath] = []
    stack: list[tuple[int, Rect | None]] = []
    # get_cdrawings = versi mentah (tuple) dari get_drawings, ~6x lebih cepat
    for d in page.get_cdrawings(extended=True):
        lvl = d.get("level", 0)
        while stack and stack[-1][0] >= lvl:
            stack.pop()
        t = d["type"]
        if t == "clip":
            stack.append((lvl, tuple(float(v) for v in d["scissor"])))
            continue
        if t == "group":
            stack.append((lvl, None))
            continue
        clips = [c for _, c in stack if c is not None]
        clip = None
        if clips:
            x0 = max(c[0] for c in clips)
            y0 = max(c[1] for c in clips)
            x1 = min(c[2] for c in clips)
            y1 = min(c[3] for c in clips)
            clip = (x0, y0, x1, y1)
        rect = tuple(float(v) for v in d["rect"])
        items = d.get("items", [])
        types = "".join(it[0] for it in items)
        width = d.get("width") or 0
        out.append(
            RawPath(
                d=d,
                rect=rect,
                clip=clip,
                types=types,
                raw=(items, rect[0], rect[1], width if "s" in t else None),
                color=_color(d.get("fill")),
                stroke=_color(d.get("color")) if "s" in t else (),
                kind=t,
            )
        )
    return out


def _shape_key(p: RawPath) -> tuple:
    w = p.rect[2] - p.rect[0]
    h = p.rect[3] - p.rect[1]
    return (p.kind, p.types, round(w), round(h), _q_color(p.color), _q_color(p.stroke))


def _q_color(c):
    return tuple(round(x * 20) for x in c) if c else ()


def find_text_frame(paths: list[RawPath], page_rect: Rect) -> Rect | None:
    """Frame teks = clip yang memuat paling banyak bentuk berbeda."""
    by_clip: dict[Rect, set] = defaultdict(set)
    count: Counter = Counter()
    for p in paths:
        if p.clip is None or p.kind != "f":
            continue
        key = tuple(round(v, 1) for v in p.clip)
        by_clip[key].add(_shape_key(p))
        count[key] += 1
    page_area = _area(page_rect)
    best, best_n = None, 0
    for clip, shapes in by_clip.items():
        if count[clip] < 20 or _area(clip) > 0.9 * page_area:
            continue
        if len(shapes) > best_n:
            best, best_n = clip, len(shapes)
    return best


def _marker_rects(paths: list[RawPath], frame: Rect) -> list[Rect]:
    """Penanda ayat: clip kecil di dalam frame yang berisi banyak path."""
    cnt: Counter = Counter()
    for p in paths:
        if p.clip is not None:
            cnt[tuple(round(v, 1) for v in p.clip)] += 1
    fa = _area(frame)
    out = []
    for clip, n in cnt.items():
        if clip == tuple(round(v, 1) for v in frame):
            continue
        if n >= 5 and _area(clip) < 0.02 * fa and _inside(_center(clip), frame):
            out.append(clip)
    return out


def _line_pitch(big: list[Token]) -> float:
    """Perkirakan jarak antarbaris dengan autokorelasi histogram sisi bawah huruf."""
    import numpy as np

    ys = np.array([t.rect[3] for t in big])
    lo = ys.min()
    hist = np.bincount(((ys - lo)).astype(int), minlength=int(ys.max() - lo) + 2).astype(float)
    hist = np.convolve(hist, np.ones(3), mode="same")
    hist -= hist.mean()
    heights = sorted(t.rect[3] - t.rect[1] for t in big)
    lag_min = max(8, int(heights[len(heights) // 2] * 1.2))
    lag_max = min(len(hist) - 1, 300)
    if lag_max <= lag_min:
        return 2.0 * lag_min
    ac = np.array([np.dot(hist[:-lag], hist[lag:]) for lag in range(lag_min, lag_max)])
    # ambil puncak pertama yang cukup kuat (>= 60% puncak tertinggi)
    thr = 0.6 * ac.max()
    for i in range(1, len(ac) - 1):
        if ac[i] >= thr and ac[i] >= ac[i - 1] and ac[i] >= ac[i + 1]:
            return float(lag_min + i)
    return float(lag_min + int(ac.argmax()))


def _baselines(tokens: list[Token]) -> list[float]:
    """Cari garis dasar (baseline) tiap baris.

    Sebagian besar huruf Arab duduk di baseline, jadi sisi bawah huruf besar
    menumpuk di satu nilai y per baris. Puncak histogram = baseline.
    """
    big = [t for t in tokens if not t.small and t.kind == "glyph" and (t.rect[3] - t.rect[1]) > 1]
    if len(big) < 3:
        return [0.0]
    min_sep = 0.7 * _line_pitch(big)
    hist: Counter = Counter(int(t.rect[3] // 2) for t in big)
    # haluskan histogram (jendela 3 bin)
    smooth = {b: hist.get(b - 1, 0) + hist.get(b, 0) + hist.get(b + 1, 0) for b in hist}
    peaks: list[float] = []
    for b, n in sorted(smooth.items(), key=lambda kv: (-kv[1], kv[0])):
        if n < 3:
            break
        y = b * 2 + 1
        if all(abs(y - p) >= min_sep for p in peaks):
            peaks.append(y)
    return sorted(peaks) or [statistics.median(t.rect[3] for t in big)]


def _assign_lines(tokens: list[Token], line_offset: int) -> list[list[Token]]:
    bases = _baselines(tokens)
    lines: list[list[Token]] = [[] for _ in bases]
    for t in tokens:
        cy = _center(t.rect)[1]
        i = len(bases) - 1
        for k, b in enumerate(bases[:-1]):
            # batas baris: 40% jarak ke baseline berikutnya (harakat atas baris
            # berikutnya duduk lebih dekat ke baris berikutnya)
            if cy <= b + 0.4 * (bases[k + 1] - b):
                i = k
                break
        t.line = line_offset + i
        lines[i].append(t)
    for ln in lines:
        ln.sort(key=lambda t: (-round(_center(t.rect)[0], 1), round(_center(t.rect)[1], 1), t.key))
    return [ln for ln in lines if ln]


@dataclass
class VectorPage:
    frame: Rect | None
    lines: list[list[Token]]  # token teks per baris, urut kanan-ke-kiri
    deco: list[Token]  # elemen di luar frame (header, ornamen, legenda)
    markers: list[Token]
    all_text: list[Token]


def extract_vector_page(page: fitz.Page, pno: int, line_offset: int = 0) -> VectorPage:
    page_rect = _r(page.rect)
    paths = _walk(page)
    frame = find_text_frame(paths, page_rect)
    if frame is None:  # tanpa clip: anggap seluruh halaman (dikurangi tepi 5%) adalah teks
        w, h = page_rect[2], page_rect[3]
        frame = (w * 0.05, h * 0.05, w * 0.95, h * 0.95)
    mrects = _marker_rects(paths, frame)

    text_paths, deco_paths = [], []
    marker_members: dict[Rect, list[RawPath]] = defaultdict(list)
    tol = 0.5
    mset = {tuple(round(v, 1) for v in mr): mr for mr in mrects}
    for p in paths:
        c = _center(p.rect)
        pclip = tuple(round(v, 1) for v in p.clip) if p.clip else None
        if pclip in mset:  # anggota penanda ditentukan oleh clip-nya, bukan posisi
            m = mset[pclip]
        elif p.clip is None or _area(p.clip) > 0.5 * _area(page_rect):
            m = next((mr for mr in mrects if _inside(c, mr)), None)  # path tanpa clip (mis. disisipkan)
        else:
            m = None
        in_frame_clip = p.clip is not None and (
            p.clip[0] >= frame[0] - tol and p.clip[1] >= frame[1] - tol
            and p.clip[2] <= frame[2] + tol and p.clip[3] <= frame[3] + tol
        )
        if m is not None:
            marker_members[m].append(p)
        elif in_frame_clip or _inside(c, frame):
            text_paths.append(p)
        else:
            deco_paths.append(p)

    heights = sorted(p.rect[3] - p.rect[1] for p in text_paths if p.kind == "f")
    p90 = heights[int(len(heights) * 0.9)] if heights else 10.0
    small_thr = 0.5 * p90

    tokens: list[Token] = []
    for p in text_paths:
        w = p.rect[2] - p.rect[0]
        h = p.rect[3] - p.rect[1]
        tokens.append(
            Token(
                page=pno,
                key=_shape_key(p),
                rect=p.rect,
                kind="glyph",
                fine=compute_fine(p.raw),
                color=p.color or p.stroke,
                clip=p.clip,
                small=max(w, h) < small_thr,
            )
        )
    markers: list[Token] = []
    for mr, members in marker_members.items():
        members.sort(key=lambda p: (round(p.rect[0] - mr[0], 1), round(p.rect[1] - mr[1], 1)))
        key = ("marker", tuple(sorted(_shape_key(p) for p in members)))
        fine = tuple(
            (p.rect[0] - mr[0], p.rect[1] - mr[1], _shape_key(p), compute_fine(p.raw)) for p in members
        )
        bbox = (
            min(p.rect[0] for p in members),
            min(p.rect[1] for p in members),
            max(p.rect[2] for p in members),
            max(p.rect[3] for p in members),
        )
        markers.append(Token(page=pno, key=key, rect=bbox, kind="marker", fine=fine, clip=mr, label="penanda ayat"))
    all_text = tokens + markers
    lines = _assign_lines(all_text, line_offset)

    deco: list[Token] = []
    for p in deco_paths:
        deco.append(
            Token(page=pno, key=_shape_key(p), rect=p.rect, kind="glyph", raw=p.raw, color=p.color or p.stroke, clip=p.clip)
        )
    return VectorPage(frame=frame, lines=lines, deco=deco, markers=markers, all_text=all_text)


# --------------------------------------------------------------- mode teks
@dataclass
class TextPage:
    lines: list[list[Token]]


def extract_text_page(page: fitz.Page, pno: int, line_offset: int = 0) -> TextPage:
    raw = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_PRESERVE_LIGATURES)
    lines_out: list[list[Token]] = []
    rows = []
    for b in raw["blocks"]:
        for ln in b.get("lines", []):
            chars = [c for s in ln["spans"] for c in s["chars"]]
            if not any("؀" <= c["c"] <= "ۿ" or "ﭐ" <= c["c"] <= "﻿" for c in chars):
                continue
            rows.append((ln["bbox"], chars))
    rows.sort(key=lambda r: (round(r[0][1]), -r[0][2]))
    for i, (bbox, chars) in enumerate(rows):
        # kelompokkan huruf dasar + harakat sesudahnya (satu "cluster")
        clusters: list[list[dict]] = []
        for c in chars:
            if clusters and unicodedata.combining(c["c"]) or (clusters and c["c"] in INVISIBLE):
                clusters[-1].append(c)
            else:
                clusters.append([c])
        toks = []
        for cl in clusters:
            # normalisasi per cluster: urutan harakat kanonik + komposisi NFC
            norm = normalize_text("".join(c["c"] for c in cl))
            norm = "".join(ch for ch in norm if not ch.isspace())
            if not norm:
                continue
            x0 = min(c["bbox"][0] for c in cl)
            y0 = min(c["bbox"][1] for c in cl)
            x1 = max(c["bbox"][2] for c in cl)
            y1 = max(c["bbox"][3] for c in cl)
            for ch in norm:
                toks.append(Token(page=pno, key=(ch,), rect=(x0, y0, x1, y1), kind="char", label=ch, line=line_offset + i))
        if toks:
            lines_out.append(toks)
    return TextPage(lines=lines_out)


def render_page(page: fitz.Page, dpi: int):
    import numpy as np

    pix = page.get_pixmap(dpi=dpi, alpha=False)
    return np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, pix.n)[:, :, :3].copy()
