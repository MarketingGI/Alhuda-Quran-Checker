"""Analisis hasil penyelarasan menjadi temuan (finding)."""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict

from .align import Alignment, DiffBlock
from .extract import ensure_fine
from .models import Finding, Rect, Token
from .normalize import char_class, describe

SHAPE_TOL = 0.15  # pt, toleransi pembulatan koordinat bentuk
COLOR_TOL = 0.03
SHIFT_TOL = 0.6  # pt, pergeseran relatif terhadap tetangga
SHIFT_HIGH = 1.5  # pt, pergeseran tanda kecil yang dianggap bisa mengubah bacaan

PALETTE = {
    "hitam": (0.13, 0.12, 0.12),
    "abu-abu": (0.55, 0.55, 0.55),
    "merah": (0.9, 0.1, 0.15),
    "magenta": (0.93, 0.0, 0.55),
    "hijau": (0.0, 0.62, 0.3),
    "biru muda": (0.0, 0.68, 0.94),
    "biru tua": (0.1, 0.25, 0.6),
    "kuning": (0.95, 0.85, 0.2),
    "oranye": (0.95, 0.55, 0.1),
    "krem": (0.99, 0.93, 0.85),
    "putih": (1.0, 1.0, 1.0),
    "coklat": (0.55, 0.35, 0.2),
}


# ------------------------------------------------------------ util bentuk
def color_name(c: tuple) -> str:
    if not c:
        return "tanpa warna"
    c = tuple(c[:3]) if len(c) >= 3 else (c[0],) * 3
    return min(PALETTE, key=lambda k: sum((x - y) ** 2 for x, y in zip(PALETTE[k], c)))


def colors_close(a: tuple, b: tuple) -> bool:
    if len(a) != len(b):
        return False
    return all(abs(x - y) <= COLOR_TOL for x, y in zip(a, b))


def shapes_close(a: Token, b: Token) -> bool:
    if a.kind != b.kind:
        return False
    if a.kind == "char":
        return a.key == b.key
    if a.kind == "marker":
        if len(a.fine) != len(b.fine):
            return False
        # urutan path di dalam penanda ayat bisa berbeda antar-ekspor PDF walau bentuknya sama:
        # bandingkan komponen setelah diurutkan menurut jenis dan posisinya
        key = lambda c: (c[2], round(c[0], 1), round(c[1], 1), len(c[3]))
        for (ax, ay, ak, af), (bx, by, bk, bf) in zip(sorted(a.fine, key=key), sorted(b.fine, key=key)):
            if ak != bk or abs(ax - bx) > 0.3 or abs(ay - by) > 0.3:
                return False
            if len(af) != len(bf) or any(abs(x - y) > SHAPE_TOL for x, y in zip(af, bf)):
                return False
        return True
    if a.key[:2] != b.key[:2] or len(a.fine) != len(b.fine):
        return False
    return all(abs(x - y) <= SHAPE_TOL for x, y in zip(a.fine, b.fine))


def same_glyph(a: Token, b: Token) -> bool:
    return shapes_close(a, b) and (a.kind != "glyph" or colors_close(a.color, b.color))


def describe_token(t: Token) -> str:
    if t.kind == "char":
        return f"{char_class(t.label)} {describe(t.label)}"
    if t.kind == "marker":
        return "penanda ayat (bulatan nomor/simbol)"
    w = t.rect[2] - t.rect[0]
    h = t.rect[3] - t.rect[1]
    col = color_name(t.color)
    if w > 25 and h > 25 and col in ("krem", "putih", "kuning"):
        return f"blok latar warna {col}"
    if h < 0.5 or w < 0.5:
        return f"garis {col}"
    if t.small:
        return f"tanda kecil {col} (harakat/titik/tanda waqaf)"
    return f"bentuk huruf {col}"


def union(rects: list[Rect]) -> Rect:
    return (
        min(r[0] for r in rects),
        min(r[1] for r in rects),
        max(r[2] for r in rects),
        max(r[3] for r in rects),
    )


def _shift_rect(r: Rect, dx: float, dy: float) -> Rect:
    return (r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy)


def _locate_in_naskah(t: Token, blk: DiffBlock) -> tuple[int, Rect]:
    """Perkirakan posisi token master yang hilang di halaman naskah."""
    for pair in (blk.prev_pair, blk.next_pair):
        if pair and pair[0].page == t.page:
            a, b = pair
            return b.page, _shift_rect(t.rect, b.rect[0] - a.rect[0], b.rect[1] - a.rect[1])
    pair = blk.prev_pair or blk.next_pair
    if pair:
        return pair[1].page, pair[1].rect
    return t.page, t.rect


# -------------------------------------------------------- analisis blok
def analyze_blocks(
    al: Alignment, replaced: list[tuple[Token, Token]] | None = None
) -> tuple[list[Finding], list[tuple[Token, Token]]]:
    """Temuan dari blok beda. `replaced` (opsional) diisi pasangan yang dianggap 'diganti'."""
    findings: list[Finding] = []
    extra_pairs: list[tuple[Token, Token]] = []
    rest: list[tuple[DiffBlock, list[Token], list[Token]]] = []
    for blk in al.blocks:
        ra = list(blk.a)
        rb = list(blk.b)
        # 1) pasangkan yang sebenarnya sama (beda hanya karena pembulatan kunci)
        used = set()
        keep_a = []
        for a in ra:
            hit = None
            for j, b in enumerate(rb):
                if j not in used and same_glyph(a, b):
                    hit = j
                    break
            if hit is None:
                keep_a.append(a)
            else:
                used.add(hit)
                extra_pairs.append((a, rb[hit]))
        rb = [b for j, b in enumerate(rb) if j not in used]
        rest.append((blk, keep_a, rb))

    # 2) bentuk sama yang oleh penyelarasan terlempar ke blok tetangga:
    #    'hilang' di satu blok + 'tambahan' di blok lain, bentuk identik, posisi sama.
    for i, (blk, ra, _) in enumerate(rest):
        keep_a = []
        for a in ra:
            exp_page, exp = _locate_in_naskah(a, blk)
            hit = None
            for k in range(max(0, i - 4), min(len(rest), i + 5)):
                for j, b in enumerate(rest[k][2]):
                    if (
                        b.page == exp_page
                        and abs(b.rect[0] - exp[0]) < 3
                        and abs(b.rect[1] - exp[1]) < 3
                        and same_glyph(a, b)
                    ):
                        hit = (k, j)
                        break
                if hit:
                    break
            if hit is None:
                keep_a.append(a)
            else:
                k, j = hit
                extra_pairs.append((a, rest[k][2].pop(j)))
        rest[i] = (blk, keep_a, rest[i][2])

    # 3) sisa dipasangkan berurutan = diganti; sisanya hilang/tambahan
    for blk, ra, rb in rest:
        if not ra and not rb:
            continue
        groups: dict[str, list] = defaultdict(list)
        n = min(len(ra), len(rb))
        for a, b in zip(ra[:n], rb[:n]):
            if a.kind == "glyph" and shapes_close(a, b):
                groups["warna"].append((a, b))
            else:
                groups["diganti"].append((a, b))
                if replaced is not None:
                    replaced.append((a, b))
        for a in ra[n:]:
            groups["hilang"].append((a, None))
        for b in rb[n:]:
            groups["tambahan"].append((None, b))
        for cat, items in groups.items():
            findings.append(_block_finding(cat, items, blk))
    return findings, extra_pairs


def _describe_change(a: Token, b: Token) -> str:
    da, db = describe_token(a), describe_token(b)
    if da != db:
        return f"{da} → {db}"
    wa, ha = a.rect[2] - a.rect[0], a.rect[3] - a.rect[1]
    wb, hb = b.rect[2] - b.rect[0], b.rect[3] - b.rect[1]
    bits = []
    if abs(wa - wb) >= 0.2:
        bits.append(f"lebar {wa:.1f} → {wb:.1f} pt")
    if abs(ha - hb) >= 0.2:
        bits.append(f"tinggi {ha:.1f} → {hb:.1f} pt")
    if not bits:
        bits.append("garis bentuknya tidak sama")
    return f"{da} di master dan naskah berbeda ({', '.join(bits)})"


def _block_finding(cat: str, items, blk: DiffBlock) -> Finding:
    a_list = [a for a, _ in items if a is not None]
    b_list = [b for _, b in items if b is not None]
    if b_list:
        page = b_list[0].page
        rects = [b.rect for b in b_list if b.page == page]
    else:
        page, r = _locate_in_naskah(a_list[0], blk)
        rects = [_locate_in_naskah(a, blk)[1] for a in a_list]
    master_page = a_list[0].page if a_list else (blk.prev_pair[0].page if blk.prev_pair else None)
    master_rect = union([a.rect for a in a_list if a.page == master_page]) if a_list else None
    if master_rect is None and blk.prev_pair:
        pa, pb = blk.prev_pair
        master_rect = _shift_rect(union(rects), pa.rect[0] - pb.rect[0], pa.rect[1] - pb.rect[1])

    any_marker = any(t.kind == "marker" for t in a_list + b_list)
    n = len(items)
    if cat == "diganti":
        lines = [_describe_change(a, b) for a, b in items[:6]]
        title = "Penanda ayat berbeda" if any_marker else "Bentuk/karakter berubah"
        msg = f"{title}: {n} item. " + "; ".join(lines)
        sev = "Tinggi"
    elif cat == "warna":
        lines = [f"{color_name(a.color)} → {color_name(b.color)}" for a, b in items[:6]]
        msg = f"Warna berubah (tajwid/penanda) pada {n} bentuk: " + "; ".join(lines)
        sev = "Sedang"
    elif cat == "hilang":
        lines = [describe_token(a) for a in a_list[:6]]
        title = "Penanda ayat hilang" if any_marker else "Hilang dari naskah"
        msg = f"{title}: {n} item ada di master tapi tidak ada di naskah. " + "; ".join(lines)
        sev = "Tinggi"
    else:
        lines = [describe_token(b) for b in b_list[:6]]
        title = "Penanda ayat tambahan" if any_marker else "Tambahan di naskah"
        msg = f"{title}: {n} item tidak ada di master. " + "; ".join(lines)
        sev = "Tinggi"
    if n > 6:
        msg += f"; … (+{n - 6} lagi)"
    check = "teks" if (a_list + b_list)[0].kind == "char" else "glyph"
    if any_marker:
        check = "struktur"
    return Finding(
        category={"diganti": "Berubah", "warna": "Warna berubah", "hilang": "Hilang", "tambahan": "Tambahan"}[cat]
        + (" (penanda ayat)" if any_marker else ""),
        severity=sev,
        message=msg,
        page=page,
        rect=union(rects) if rects else None,
        master_page=master_page,
        master_rect=master_rect,
        check=check,
        detail={
            "master": [a.label for a in a_list] if check == "teks" else [],
            "naskah": [b.label for b in b_list] if check == "teks" else [],
        },
    )


def merge_replacements(findings: list[Finding], gap: float = 1.5) -> list[Finding]:
    """Gabungkan 'Hilang' + 'Tambahan' yang berimpit di lokasi sama menjadi 'Berubah'."""
    hil = [f for f in findings if f.category == "Hilang" and f.rect]
    tam = [f for f in findings if f.category == "Tambahan" and f.rect]
    drop = set()
    merged = []
    for h in hil:
        for t in tam:
            if id(t) in drop or t.page != h.page:
                continue
            a, b = h.rect, t.rect
            if a[0] <= b[2] + gap and b[0] <= a[2] + gap and a[1] <= b[3] + gap and b[1] <= a[3] + gap:
                drop.update((id(h), id(t)))
                lhs = h.message.split(". ", 1)[-1]
                rhs = t.message.split(". ", 1)[-1]
                merged.append(
                    Finding(
                        category="Berubah",
                        severity="Tinggi",
                        message=f"Bentuk/karakter berubah. Master: {lhs} → naskah: {rhs}",
                        page=t.page,
                        rect=union([a, b]),
                        master_page=h.master_page,
                        master_rect=h.master_rect,
                        check=t.check,
                        detail={"master": h.detail.get("master", []), "naskah": t.detail.get("naskah", [])},
                    )
                )
                break
    return [f for f in findings if id(f) not in drop] + merged


# --------------------------------------------- pasangan sama: bentuk & posisi
def analyze_pairs(pairs: list[tuple[Token, Token]]) -> list[Finding]:
    findings: list[Finding] = []
    # bentuk/warna halus (kunci sama tapi detail beda, mis. font fallback)
    for a, b in pairs:
        if a.kind == "char":
            continue
        if not shapes_close(a, b):
            findings.append(
                Finding(
                    category="Bentuk berubah halus",
                    severity="Sedang",
                    message=f"{describe_token(b)} sedikit berbeda bentuknya dari master (cek font/glyph).",
                    page=b.page, rect=b.rect, master_page=a.page, master_rect=a.rect, check="glyph",
                )
            )
        elif a.kind == "glyph" and not colors_close(a.color, b.color):
            findings.append(
                Finding(
                    category="Warna berubah",
                    severity="Sedang",
                    message=f"Warna {describe_token(b)}: master {color_name(a.color)}, naskah {color_name(b.color)}.",
                    page=b.page, rect=b.rect, master_page=a.page, master_rect=a.rect, check="glyph",
                )
            )
    findings += _shift_findings([p for p in pairs if p[0].kind != "char"])
    return findings


def _shift_findings(pairs: list[tuple[Token, Token]]) -> list[Finding]:
    by_line: dict[tuple, list] = defaultdict(list)
    for a, b in pairs:
        by_line[(b.page, b.line)].append((a, b))
    out: list[Finding] = []
    for items in by_line.values():
        items.sort(key=lambda p: (-(p[1].rect[0] + p[1].rect[2]) / 2, p[1].rect[1]))
        d = [(b.rect[0] - a.rect[0], b.rect[1] - a.rect[1]) for a, b in items]
        for i, (a, b) in enumerate(items):
            left = d[max(0, i - 3):i]
            right = d[i + 1:i + 4]
            devs = []
            for side in (left, right):
                if side:
                    mx = statistics.median(x for x, _ in side)
                    my = statistics.median(y for _, y in side)
                    devs.append((d[i][0] - mx, d[i][1] - my))
            if not devs:
                continue
            if all(max(abs(dx), abs(dy)) > SHIFT_TOL for dx, dy in devs):
                dx, dy = min(devs, key=lambda v: max(abs(v[0]), abs(v[1])))
                high = b.small and (abs(dy) >= SHIFT_HIGH or abs(dx) >= 2 * SHIFT_HIGH)
                arah = []
                if abs(dy) > SHIFT_TOL:
                    arah.append(f"{abs(dy):.1f} pt ke {'bawah' if dy > 0 else 'atas'}")
                if abs(dx) > SHIFT_TOL:
                    arah.append(f"{abs(dx):.1f} pt ke {'kanan' if dx > 0 else 'kiri'}")
                out.append(
                    Finding(
                        category="Posisi bergeser",
                        severity="Tinggi" if high else "Sedang",
                        message=f"{describe_token(b)} bergeser {' dan '.join(arah)} relatif terhadap huruf di sekitarnya"
                        + (" (bisa mengubah bacaan, mis. fathah↔kasrah)." if high else "."),
                        page=b.page, rect=b.rect, master_page=a.page, master_rect=a.rect, check="glyph",
                    )
                )
    return out


# ---------------------------------------------------------- glyph terpotong
def visible_fraction(t: Token) -> tuple[float, float]:
    """Bagian lebar & tinggi bentuk yang berada di dalam clip (1.0 = utuh)."""
    if t.clip is None or t.kind == "char":
        return 1.0, 1.0
    r, c = t.rect, t.clip
    out = []
    for lo, hi, clo, chi in ((r[0], r[2], c[0], c[2]), (r[1], r[3], c[1], c[3])):
        size = hi - lo
        if size < 0.05:
            out.append(1.0 if clo - 0.3 <= lo <= chi + 0.3 else 0.0)
        else:
            out.append(max(0.0, min(hi, chi) - max(lo, clo)) / size)
    return out[0], out[1]


def analyze_clipping(
    pairs: list[tuple[Token, Token]], b_tokens: list[Token], replaced: list[tuple[Token, Token]] | None = None
) -> list[Finding]:
    """Bandingkan bagian tampak tiap bentuk (di dalam clip) dengan master.

    `replaced`: pasangan yang bentuknya berbeda (mis. penanda ayat yang terpotong) — dipakai
    supaya temuan tetap menunjuk lokasi yang sama di master."""
    paired = {id(b): a for a, b in pairs}
    for a, b in replaced or []:
        paired.setdefault(id(b), a)
    groups: dict[tuple, list] = defaultdict(list)
    for b in b_tokens:
        if b.clip is None:
            continue
        bw, bh = visible_fraction(b)
        a = paired.get(id(b))
        aw, ah = visible_fraction(a) if a is not None else (1.0, 1.0)
        if bw < aw - 0.02 or bh < ah - 0.02:
            groups[(b.page, tuple(round(v, 1) for v in b.clip))].append((a, b))
    out = []
    for (page, clip), items in groups.items():
        bs = [b for _, b in items]
        as_ = [a for a, _ in items if a is not None]
        edges = []
        a_clip = Counter(tuple(round(v, 1) for v in a.clip) for a in as_ if a.clip).most_common(1)
        if a_clip:
            mc = a_clip[0][0]
            names = ["kiri", "atas", "kanan", "bawah"]
            for k in range(4):
                if abs(mc[k] - clip[k]) > 0.2:
                    edges.append(f"batas {names[k]} {mc[k]:.1f} → {clip[k]:.1f} pt")
        n_marker = sum(1 for b in bs if b.kind == "marker")
        n_small = sum(1 for b in bs if b.small and b.kind == "glyph")
        parts = []
        if n_small:
            parts.append(f"{n_small} tanda kecil/harakat/titik")
        if len(bs) - n_small - n_marker:
            parts.append(f"{len(bs) - n_small - n_marker} huruf")
        if n_marker:
            parts.append(f"{n_marker} penanda ayat")
        msg = (
            f"Glyph terpotong: {', '.join(parts)} keluar dari batas frame/clip "
            f"sehingga sebagian tidak tercetak."
        )
        if edges:
            msg += " Perubahan frame dibanding master: " + ", ".join(edges) + "."
        cut_area = union([b.rect for b in bs])
        out.append(
            Finding(
                category="Glyph terpotong",
                severity="Tinggi",
                message=msg,
                page=page,
                rect=cut_area,
                master_page=as_[0].page if as_ else None,
                master_rect=union([a.rect for a in as_]) if as_ else None,
                check="clip",
            )
        )
    return out


def drop_covered_by_clipping(block_findings: list[Finding], clip_findings: list[Finding]) -> list[Finding]:
    """Penanda ayat yang terpotong juga muncul sebagai 'Berubah (penanda ayat)' di lokasi sama.
    Cukup laporkan sekali, sebagai 'Glyph terpotong' (penyebabnya)."""
    out = []
    for f in block_findings:
        dup = None
        if f.category.startswith("Berubah") and f.rect:
            for c in clip_findings:
                if c.page == f.page and c.rect and _overlap_ratio(f.rect, c.rect) > 0.6:
                    dup = c
                    break
        if dup is None:
            out.append(f)
        else:
            if dup.master_page is None:
                dup.master_page, dup.master_rect = f.master_page, f.master_rect
            if "bentuknya berbeda" not in dup.message:
                dup.message += " Karena terpotong, bentuknya berbeda dari master."
    return out


def _overlap_ratio(a: Rect, b: Rect) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])) or 1e-9
    return w * h / small


# ---------------------------------------------------------------- dekorasi
def analyze_decoration(a_deco: list[Token], b_deco: list[Token], page: int, master_page: int) -> list[Finding]:
    def pos_key(t):
        return (t.key, round(t.rect[0]), round(t.rect[1]))

    ca = defaultdict(list)
    for t in a_deco:
        ca[pos_key(t)].append(t)
    rest_b = []
    for t in b_deco:
        lst = ca.get(pos_key(t))
        if lst:
            lst.pop()
        else:
            rest_b.append(t)
    rest_a = [ensure_fine(t) for lst in ca.values() for t in lst]
    rest_b = [ensure_fine(t) for t in rest_b]
    # pasangkan yang beda tipis karena pembulatan
    still_b = []
    for b in rest_b:
        hit = next(
            (a for a in rest_a if abs(a.rect[0] - b.rect[0]) <= 1 and abs(a.rect[1] - b.rect[1]) <= 1 and same_glyph(a, b)),
            None,
        )
        if hit is not None:
            rest_a.remove(hit)
        else:
            still_b.append(b)
    rects = [t.rect for t in rest_a] + [t.rect for t in still_b]
    out = []
    for cl in _cluster_rects(rects, gap=4.0):
        out.append(
            Finding(
                category="Elemen non-teks berbeda",
                severity="Sedang",
                message="Ada perbedaan di luar area ayat (header, nomor halaman, nama surah/juz, ornamen, atau legenda tajwid).",
                page=page, rect=cl, master_page=master_page, master_rect=cl, check="dekorasi",
            )
        )
    return out


def _cluster_rects(rects: list[Rect], gap: float) -> list[Rect]:
    clusters: list[Rect] = []
    for r in rects:
        r = tuple(r)
        merged = True
        while merged:
            merged = False
            for i, c in enumerate(clusters):
                if r[0] <= c[2] + gap and c[0] <= r[2] + gap and r[1] <= c[3] + gap and c[1] <= r[3] + gap:
                    r = union([r, c])
                    clusters.pop(i)
                    merged = True
                    break
        clusters.append(r)
    return clusters
