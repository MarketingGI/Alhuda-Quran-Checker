"""Pemeriksaan naskah tanpa master PDF: dibandingkan dengan teks standar Kemenag.

Dipakai untuk produk baru (desain baru) yang belum punya master. Naskah harus punya
lapisan teks hidup (PDF diekspor sebelum teks di-outline).

Alur (semuanya kode deterministik, tanpa AI):
1. Teks standar dimuat dari file lokal `data/quran_kemenag.json` (offline).
2. Setiap halaman naskah dicari posisinya di teks standar dengan pencocokan potongan
   teks (n-gram), jadi surah/ayat tidak perlu diisi manual.
3. Isi halaman dibandingkan huruf demi huruf dengan potongan teks standar itu,
   memakai penyelarasan yang sama dengan mode teks.
4. Pemeriksaan tambahan: teks yang hilang/terulang di antara halaman, nomor ayat,
   dan huruf yang terpotong di tepi halaman.
"""
from __future__ import annotations

import json
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

import pymupdf as fitz

from . import diff_tokens as dt
from .align import Alignment, align
from .extract import page_has_arabic_text
from .models import SEVERITY_ORDER, CompareResult, Finding, PageInfo, Token
from .normalize import char_class, describe, normalize_text
from .structure import ARABIC_DIGITS, _ayah_numbers

DATA_FILE = Path(__file__).parent / "data" / "quran_kemenag.json"

# Karakter "pembawa" khusus font web Kemenag (bukan huruf/harakat): ە dipakai sebagai
# dudukan tanda waqaf, ۔ penanda tampilan di akhir ayat tertentu, ؈ ؉ penanda khusus.
# Dibuang dari kedua sisi supaya tidak muncul sebagai temuan palsu.
CARRIERS = {"ە", "۔", "؈", "؉", " "}
AYAH_END = "۝"
K = 10  # panjang potongan untuk mencari posisi halaman di teks standar


def _content_char(ch: str) -> bool:
    return not (ch.isspace() or ch in CARRIERS or ch in ARABIC_DIGITS or ch == AYAH_END or ch.isdigit())


# Tanda yang "mengambang" di atas/antara kata (waqaf, ۞, ۩, mim iqlab, tanda ruku' ࣖ).
# Urutan simpannya di PDF tidak bisa diandalkan (di teks standar pun kadang dipisah spasi),
# jadi tidak ikut diselaraskan per huruf, tapi dibandingkan terpisah: tanda apa, di ayat mana,
# dan setelah huruf ke berapa (toleransi beberapa huruf).
FLOATING = {chr(c) for c in range(0x06D6, 0x06DD)} | {"۞", "۩", "ۢ", "ۨ", "ࣖ"}
FLOAT_TOL = 3  # toleransi posisi (jumlah huruf/harakat)
# Penanda tingkat ayat: yang penting ayatnya, bukan huruf ke berapa (sering diletakkan di awal/akhir baris).
AYAH_LEVEL = {"۞", "۩", "ࣖ"}

ALEFS = {"ا", "ٱ"}  # setelah NFD, أ إ آ menjadi ا + tanda
UNREADABLE = "\ufffd"


def _is_mark(ch: str) -> bool:
    return unicodedata.combining(ch) > 0 or ch in ("ٰ",)


def canon(items: list, ch=lambda x: x) -> list:
    """Bentuk kanonik urutan karakter, dipakai sama persis untuk teks standar dan naskah.

    1. Harakat sesudah setiap huruf diurutkan menurut kelas kanonik Unicode (seperti NFC),
       supaya urutan simpan di PDF tidak berpengaruh.
    2. Ligatur lam-alif: PDF sering menyimpan ل ا lalu harakatnya, sedangkan teks standar
       menyimpan ل َ ا. Keduanya dijadikan ل + harakat + ا. (Konsekuensi: harakat yang
       pindah dari lam ke alif di dalam satu ligatur lam-alif tidak terdeteksi.)
    """
    groups: list[list] = []
    for it in items:
        if groups and _is_mark(ch(it)):
            groups[-1].append(it)
        else:
            groups.append([it])
    out: list = []
    i = 0
    while i < len(groups):
        g = groups[i]
        base, marks = g[0], g[1:]
        if ch(base) == "ل" and i + 1 < len(groups) and ch(groups[i + 1][0]) in ALEFS:
            alef, amarks = groups[i + 1][0], groups[i + 1][1:]
            out += [base] + sorted(marks + amarks, key=lambda x: unicodedata.combining(ch(x))) + [alef]
            i += 2
            continue
        out += [base] + sorted(marks, key=lambda x: unicodedata.combining(ch(x)))
        i += 1
    return out


def _rect_union(toks: list[Token]):
    return (min(t.rect[0] for t in toks), min(t.rect[1] for t in toks),
            max(t.rect[2] for t in toks), max(t.rect[3] for t in toks))



def _unreadable(ch: str) -> bool:
    return ch == UNREADABLE or 0xE000 <= ord(ch) <= 0xF8FF


# ------------------------------------------------------------ teks standar
@dataclass
class Reference:
    text: str  # seluruh Al-Qur'an, ternormalisasi, tanpa spasi/angka
    seg_of: list[int]  # indeks karakter -> indeks segmen
    segs: list[tuple[int, int, int, int]]  # (surah, ayat [0 = basmalah], awal, akhir)
    surah_names: dict[int, str]
    pages: dict[tuple[int, int], int]  # (surah, ayat) -> halaman mushaf standar
    floats: list[tuple[int, str]] = field(default_factory=list)  # (posisi di text, tanda mengambang)
    source: str = ""
    note: str = ""

    def where(self, idx: int) -> str:
        idx = max(0, min(idx, len(self.text) - 1))
        s, a, _, _ = self.segs[self.seg_of[idx]]
        return f"QS {self.surah_names.get(s, s)} ({s}):" + (f"{a}" if a else " basmalah")

    def span_label(self, r0: int, r1: int) -> str:
        if r1 <= r0:
            return "-"
        s0, a0, _, _ = self.segs[self.seg_of[r0]]
        s1, a1, _, _ = self.segs[self.seg_of[r1 - 1]]
        a = lambda x: str(x) if x else "basmalah"
        if s0 == s1:
            return f"QS {self.surah_names.get(s0, s0)} ({s0}):{a(a0)}–{a(a1)}"
        return f"QS {s0}:{a(a0)} – {s1}:{a(a1)}"


@lru_cache(maxsize=1)
def load_reference(path: str = str(DATA_FILE)) -> Reference:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    names = {s[0]: s[1] for s in data["surah"]}
    basmalah = None
    parts: list[str] = []
    seg_of: list[int] = []
    segs: list[tuple[int, int, int, int]] = []
    pages: dict[tuple[int, int], int] = {}
    floats: list[tuple[int, str]] = []
    pos = 0

    def add(s: int, a: int, raw: str):
        nonlocal pos
        main: list[str] = []
        for ch in _decomp(raw):
            if ch in FLOATING:
                floats.append((pos + len(main), ch))
            elif _content_char(ch):
                main.append(ch)
        t = "".join(canon(main))
        segs.append((s, a, pos, pos + len(t)))
        seg_of.extend([len(segs) - 1] * len(t))
        parts.append(t)
        pos += len(t)

    for s, a, page, _juz, raw in data["ayat"]:
        if s == 1 and a == 1:
            basmalah = raw
        if a == 1 and s not in (1, 9) and basmalah:
            add(s, 0, basmalah)  # basmalah pembuka surah (tidak bernomor)
        add(s, a, raw)
        pages[(s, a)] = page
    return Reference(
        text="".join(parts), seg_of=seg_of, segs=segs, surah_names=names, pages=pages, floats=floats,
        source=data.get("sumber", ""), note=data.get("catatan", ""),
    )


# ------------------------------------------------------------ naskah
@dataclass
class NPage:
    index: int
    lines: list[list[Token]] = field(default_factory=list)  # token isi (tanpa angka & tanda mengambang)
    floats: list[list[tuple[int, Token]]] = field(default_factory=list)  # per baris: (posisi di baris, token)
    digits: list[Token] = field(default_factory=list)  # semua karakter baris (untuk membaca nomor ayat)
    offside: list[Token] = field(default_factory=list)  # karakter di luar halaman
    r0: int = -1  # rentang di teks standar
    r1: int = -1

    @property
    def text(self) -> str:
        return "".join(t.label for ln in self.lines for t in ln)


def _clusters(line: list[Token]) -> list[list[Token]]:
    """Kelompokkan huruf dasar + harakat yang tersimpan sesudahnya."""
    out: list[list[Token]] = []
    for t in line:
        if out and _is_mark(t.label):
            out[-1].append(t)
        else:
            out.append([t])
    return out


def _reverse_clusters(line: list[Token]) -> list[Token]:
    """Balik urutan cluster (huruf + harakatnya): PDF yang menyimpan huruf kiri-ke-kanan."""
    return [t for cl in reversed(_clusters(line)) for t in cl]


def _reverse_chars(line: list[Token]) -> list[Token]:
    """Balik urutan per karakter: PDF yang menyimpan seluruh baris terbalik (harakat sebelum hurufnya)."""
    return line[::-1]


ORIENTATIONS = {
    "asli": lambda ln: ln,
    "cluster terbalik": _reverse_clusters,
    "karakter terbalik": _reverse_chars,
}


def _decomp(text: str) -> str:
    """Normalisasi + dekomposisi kanonik (NFD): أ = ا + ٔ, ئ = ي + ٔ, آ = ا + ٓ.

    Dipakai di kedua sisi supaya cara PDF menyimpan hamzah/madda (huruf jadi atau huruf + tanda)
    tidak dianggap beda. Bila hamzah benar-benar hilang, yang dilaporkan adalah tandanya (ٔ).
    """
    return unicodedata.normalize("NFD", normalize_text(text))


def _finish_line(line: list[Token]) -> tuple[list[Token], list[tuple[int, Token]]]:
    """Susun ulang setelah arah baca ditentukan: normalisasi per karakter, lalu bentuk kanonik.

    Kembalikan (token isi, tanda mengambang beserta posisinya di baris).
    """
    out: list[Token] = []
    floats: list[tuple[int, Token]] = []
    for t in line:
        for ch in _decomp(t.label):
            tok = Token(page=t.page, key=(ch,), rect=t.rect, kind="char", label=ch, line=t.line)
            if ch in FLOATING:
                floats.append((len(out), tok))
            elif _content_char(ch):
                out.append(tok)
    return canon(out, ch=lambda t: t.label), floats


def _hits(ref: Reference, s: str, step: int = 9) -> int:
    return sum(1 for i in range(0, max(0, len(s) - K + 1), step) if s[i:i + K] in ref.text)


def _raw_lines(page: fitz.Page, pno: int) -> list[list[Token]]:
    """Karakter apa adanya dari lapisan teks (tanpa normalisasi), satu token per karakter.

    Normalisasi baru dilakukan setelah arah baca ditentukan, karena menormalkan urutan yang
    masih terbalik bisa salah menggabungkan huruf (mis. ا + ٓ menjadi آ).
    """
    raw = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_PRESERVE_LIGATURES)
    rows = []
    for b in raw["blocks"]:
        for ln in b.get("lines", []):
            chars = [c for sp in ln["spans"] for c in sp["chars"]]
            if any("؀" <= c["c"] <= "ۿ" or "ﭐ" <= c["c"] <= "﻿" or "ࢠ" <= c["c"] <= "ࣿ" for c in chars):
                rows.append((ln["bbox"], chars))
    rows.sort(key=lambda r: (round(r[0][1]), -r[0][2]))
    out = []
    for k, (_bbox, chars) in enumerate(rows):
        toks = []
        for c in chars:
            for ch in normalize_text(c["c"], drop_tatweel=False) if _is_presentation(c["c"]) else c["c"]:
                toks.append(Token(page=pno, key=(ch,), rect=tuple(c["bbox"]), kind="char", label=ch, line=k))
        out.append(toks)
    return out


def _is_presentation(ch: str) -> bool:
    cp = ord(ch)
    return 0xFB50 <= cp <= 0xFDFF or 0xFE70 <= cp <= 0xFEFF


def _read_pages(doc: fitz.Document) -> tuple[list[NPage], list[int]]:
    pages: list[NPage] = []
    no_text: list[int] = []
    for i, page in enumerate(doc):
        if not page_has_arabic_text(page):
            no_text.append(i)
            continue
        np_ = NPage(index=i)
        pr = page.rect
        for ln in _raw_lines(page, i):
            content = [t for t in ln if _content_char(t.label)]
            np_.digits += ln + [Token(page=i, key=(' ',), rect=(0, 0, 0, 0), kind='sep', label=' ')]
            np_.offside += [
                t for t in content
                if t.rect[0] < pr.x0 - 0.5 or t.rect[1] < pr.y0 - 0.5 or t.rect[2] > pr.x1 + 0.5 or t.rect[3] > pr.y1 + 0.5
            ]
            if content:
                np_.lines.append(content)
        pages.append(np_)
    return pages, no_text


def _orient(ref: Reference, pages: list[NPage]) -> str:
    """Pilih arah baca yang paling cocok dengan teks standar (dihitung dari beberapa halaman pertama)."""
    score = {}
    for name, fn in ORIENTATIONS.items():
        score[name] = sum(
            _hits(ref, "".join(t.label for ln in p.lines for t in _finish_line(fn(ln))[0])) for p in pages[:8]
        )
    return max(score, key=lambda k: (score[k], k == "asli"))


def _locate(ref: Reference, s: str, hint: int | None) -> tuple[int | None, float]:
    """Cari offset halaman di teks standar. Kembalikan (offset, tingkat keyakinan 0..1)."""
    grams = [(i, s[i:i + K]) for i in range(0, max(0, len(s) - K + 1), 7)]
    if not grams:
        return None, 0.0

    def vote(lo: int, hi: int) -> tuple[int | None, float]:
        c: Counter = Counter()
        for i, g in grams:
            j = ref.text.find(g, lo, hi)
            n = 0
            while j != -1 and n < 40:
                c[(j - i) // 60] += 1
                j = ref.text.find(g, j + 1, hi)
                n += 1
        if not c:
            return None, 0.0
        best_bin, _ = max(c.items(), key=lambda kv: kv[1] + c.get(kv[0] - 1, 0) + c.get(kv[0] + 1, 0))
        votes = c[best_bin] + c.get(best_bin - 1, 0) + c.get(best_bin + 1, 0)
        return best_bin * 60, votes / len(grams)

    if hint is not None:
        off, conf = vote(max(0, hint - 3000), min(len(ref.text), hint + 3 * len(s) + 3000))
        if off is not None and conf >= 0.3:
            return off, conf
    return vote(0, len(ref.text))


# ------------------------------------------------------------ perbandingan
def _ref_tokens(ref: Reference, r0: int, r1: int) -> list[list[Token]]:
    """Token teks standar, satu 'baris' per segmen (ayat/basmalah)."""
    lines: list[list[Token]] = []
    cur_seg = None
    for i in range(r0, r1):
        sg = ref.seg_of[i]
        if sg != cur_seg:
            lines.append([])
            cur_seg = sg
        ch = ref.text[i]
        lines[-1].append(Token(page=-1, key=(ch,), rect=(0, 0, 0, 0), kind="char", label=ch, raw=(i,)))
    return lines


def _trim_span(ref: Reference, off: int, toks: list[Token]) -> tuple[int, int]:
    """Tentukan rentang teks standar yang benar-benar diwakili halaman ini.

    Ujung rentang = blok cocok pertama/terakhir (minimal 5 karakter), lalu diperluas sebanyak
    karakter naskah yang tidak cocok di ujung halaman, supaya huruf yang salah di awal/akhir
    halaman tetap terbandingkan.
    """
    margin = 300 + len(toks) // 4
    lo, hi = max(0, off - margin), min(len(ref.text), off + len(toks) + margin)
    s = "".join(t.label for t in toks)
    sm = SequenceMatcher(None, ref.text[lo:hi], s, autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size >= 5]
    if not blocks:
        return off, off
    first, last = blocks[0], blocks[-1]
    lead = sum(1 for c in s[:first.b] if not _unreadable(c))
    tail = sum(1 for c in s[last.b + last.size:] if not _unreadable(c))
    # hanya sisa kecil di ujung yang dianggap huruf salah; sisa panjang = teks lain (dilaporkan sebagai tambahan)
    lead = lead if lead <= 3 else 0
    tail = tail if tail <= 3 else 0
    r0 = lo + first.a - min(lead, first.a)
    r1 = lo + last.a + last.size + min(tail, hi - lo - (last.a + last.size))
    return max(lo, r0), min(hi, r1)


def _loc_of_block(ref: Reference, blk) -> str:
    for t in list(blk.a) + [p[0] for p in (blk.prev_pair, blk.next_pair) if p]:
        if t.raw:
            return ref.where(t.raw[0])
    return ""


def _fix_finding(f: Finding, loc: str, page: int, blk) -> Finding:
    f.master_page = None
    f.master_rect = None
    f.check = "standar"
    f.message = (f.message.replace("di master", "di teks standar").replace("Master:", "Teks standar:")
                 .replace("tidak ada di master", "tidak ada di teks standar"))
    if loc:
        f.message = f"[{loc}] " + f.message
        f.detail["lokasi"] = loc
    if f.rect is None or f.page < 0:
        anchor = next((p[1] for p in (blk.prev_pair, blk.next_pair) if p), None)
        f.page = anchor.page if anchor else page
        f.rect = anchor.rect if anchor else None
    x0, y0, x1, y1 = f.rect or (0, 0, 0, 0)
    if f.rect and (x1 - x0 < 4 or y1 - y0 < 4):  # titik sisip (huruf hilang): beri ukuran agar terlihat
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        f.rect = (cx - 6, cy - 9, cx + 6, cy + 9)
    return f


def _diff_page(ref: Reference, p: NPage) -> tuple[list[Finding], list]:
    """Bandingkan satu halaman dengan rentang teks standarnya. Kembalikan (temuan, pasangan sama)."""
    al: Alignment = align(_ref_tokens(ref, p.r0, p.r1), p.lines)
    findings: list[Finding] = []
    unread: list[tuple[int, Token]] = []
    for blk in al.blocks:
        loc = _loc_of_block(ref, blk)
        if blk.b and not blk.a and all(_unreadable(t.label) for t in blk.b):
            # karakter tak terbaca tanpa pasangan: mungkin tanda mengambang yang glyph-nya tidak terpetakan
            pos = (blk.prev_pair[0].raw[0] + 1) if blk.prev_pair else (blk.next_pair[0].raw[0] if blk.next_pair else None)
            if pos is not None:
                unread.extend((pos, t) for t in blk.b)
                continue
        if blk.b and all(_unreadable(t.label) for t in blk.b) and all(_is_mark(t.label) for t in blk.a):
            # glyph gabungan (mis. syaddah+fathah) yang tidak punya kode Unicode: satu temuan "tidak terbaca"
            anchor = blk.b[0]
            findings.append(Finding(
                category="Tidak terbaca (pemetaan font)", severity="Sedang",
                message=f"[{loc}] Lapisan teks PDF tidak bisa dibaca di sini, jadi tidak bisa dibandingkan otomatis. "
                        f"Teks standar di posisi ini: {''.join(t.label for t in blk.a) or '-'}. Cek dengan mata.",
                page=anchor.page, rect=_rect_union(blk.b), check="standar",
                detail={"master": [t.label for t in blk.a], "naskah": [t.label for t in blk.b], "lokasi": loc},
            ))
            continue
        fs, _ = dt.analyze_blocks(Alignment(pairs=[], blocks=[blk]))
        findings += [_fix_finding(f, loc, p.index, blk) for f in fs]
    out = dt.merge_replacements(_merge_moved(findings))
    for f in out:
        nk = f.detail.get("naskah") or []
        if nk and all(_unreadable(c) for c in nk):
            f.category = "Tidak terbaca (pemetaan font)"
            f.severity = "Sedang"
            exp = "".join(f.detail.get("master") or []) or "-"
            f.message = (f"[{f.detail.get('lokasi', '')}] Lapisan teks PDF tidak bisa dibaca di sini, jadi tidak bisa "
                         f"dibandingkan otomatis. Teks standar di posisi ini: {exp}. Cek dengan mata.")
    return out, al.pairs, unread


def _ayah_of(loc: str) -> tuple:
    try:
        sa = loc.split("(")[1]
        s_, a_ = sa.split("):")
        return int(s_), int(a_) if a_.strip().isdigit() else 0
    except (IndexError, ValueError):
        return ()


def _merge_moved(findings: list[Finding]) -> list[Finding]:
    """'Hilang' + 'Tambahan' karakter yang sama di ayat yang sama/berdekatan = karakter berpindah tempat."""
    hil = [f for f in findings if f.category == "Hilang" and len(f.detail.get("master", [])) == 1]
    tam = [f for f in findings if f.category == "Tambahan" and len(f.detail.get("naskah", [])) == 1]
    drop, out = set(), []
    for h in hil:
        ha = _ayah_of(h.detail.get("lokasi", ""))
        for t in tam:
            ta = _ayah_of(t.detail.get("lokasi", ""))
            if id(t) in drop or t.page != h.page or h.detail["master"] != t.detail["naskah"]:
                continue
            if not ha or not ta or ha[0] != ta[0] or abs(ha[1] - ta[1]) > 1:
                continue
            ch = h.detail["master"][0]
            symbol = char_class(ch) in ("tanda waqaf", "tanda kecil mushaf")
            drop.update((id(h), id(t)))
            out.append(Finding(
                category="Posisi berpindah", severity="Sedang" if symbol else "Tinggi",
                message=f"[{h.detail.get('lokasi', '')}] {describe(ch)} ada di naskah, tapi letaknya dalam urutan teks "
                        f"berbeda dengan teks standar (sekitar {t.detail.get('lokasi', '')}). "
                        + ("Bisa juga hanya urutan simpan di PDF; cek posisinya dengan mata." if symbol else "Cek dengan mata."),
                page=t.page, rect=t.rect, check="standar",
                detail={"master": [ch], "naskah": [ch], "lokasi": h.detail.get("lokasi", "")},
            ))
            break
    return [f for f in findings if id(f) not in drop] + out


def _non_ayah_lines(ref: Reference, p: NPage) -> list[list[Token]]:
    """Baris yang hampir tidak cocok dengan teks standar (judul surah, header, atau baris rusak berat)."""
    span = ref.text[max(0, p.r0 - 200):p.r1 + 200]
    out = []
    for ln in p.lines:
        s = "".join(t.label for t in ln)
        if len(s) < 4:
            continue
        sm = SequenceMatcher(None, span, s, autojunk=False)
        matched = sum(b.size for b in sm.get_matching_blocks() if b.size >= 3)
        if matched / len(s) < 0.35:
            out.append(ln)
    return out


def _page_floats(p: NPage, pairs) -> list[tuple[int, Token]]:
    """Petakan tanda mengambang naskah ke posisi di teks standar.

    Utamanya lewat letak di halaman: huruf terdekat (secara horizontal) di baris yang sama.
    Urutan simpan tanda waqaf di PDF tidak bisa diandalkan, letak gambarnya bisa.
    Bila tidak ada huruf berpasangan di baris itu, pakai urutan simpan sebagai cadangan.
    """
    pos_of = {id(b): a.raw[0] for a, b in pairs}
    flat = [t for ln in p.lines for t in ln]
    out = []
    base = 0
    for ln, fl in zip(p.lines, p.floats):
        paired = [t for t in ln if id(t) in pos_of]
        for k, tok in fl:
            ref_pos = None
            if paired:
                cx = (tok.rect[0] + tok.rect[2]) / 2
                near = min(paired, key=lambda t: abs((t.rect[0] + t.rect[2]) / 2 - cx))
                # tanda di kiri huruf terdekat = sesudahnya dalam urutan baca (kanan-ke-kiri)
                ref_pos = pos_of[id(near)] + (1 if cx < (near.rect[0] + near.rect[2]) / 2 else 0)
            else:
                g = base + k
                for j in range(g, min(len(flat), g + 12)):
                    if id(flat[j]) in pos_of:
                        ref_pos = pos_of[id(flat[j])] - (j - g)
                        break
            if ref_pos is not None:
                out.append((ref_pos, tok))
        base += len(ln)
    return out


def _compare_floats(ref: Reference, located: list[NPage], got: list[tuple[int, Token]], ref_to_naskah,
                    unread: list[tuple[int, Token]] = ()) -> list[Finding]:
    """Bandingkan tanda mengambang: cocok persis, berubah, bergeser, hilang, tambahan, atau tidak terbaca."""
    spans = [(p.r0, p.r1) for p in located]
    expected = [(pos, ch) for pos, ch in ref.floats if any(r0 <= pos <= r1 for r0, r1 in spans)]
    exp_left = list(expected)
    got_left = list(got)
    findings: list[Finding] = []

    def take(pred):
        pairs = []
        for e in list(exp_left):
            best = None
            for g in got_left:
                if pred(e, g) and (best is None or abs(g[0] - e[0]) < abs(best[0] - e[0])):
                    best = g
            if best is not None:
                exp_left.remove(e)
                got_left.remove(best)
                pairs.append((e, best))
        return pairs

    def segs(pos: int) -> set[int]:
        # posisi tepat di akhir ayat bisa dihitung milik ayat itu atau ayat berikutnya
        return {ref.seg_of[max(0, min(q, len(ref.seg_of) - 1))] for q in (pos - 1, pos)}

    same_ayah = lambda a, b: bool(segs(a) & segs(b))
    near_ayah = lambda a, b: any(abs(x - y) <= 1 for x in segs(a) for y in segs(b))
    take(lambda e, g: e[1] == g[1].label and abs(e[0] - g[0]) <= FLOAT_TOL)
    take(lambda e, g: e[1] == g[1].label and e[1] in AYAH_LEVEL and same_ayah(e[0], g[0]))
    for e, g in take(lambda e, g: abs(e[0] - g[0]) <= FLOAT_TOL):
        findings.append(Finding(
            category="Tanda waqaf/simbol berubah", severity="Tinggi",
            message=f"[{ref.where(max(0, e[0] - 1))}] Teks standar: {describe(e[1])}; naskah: {describe(g[1].label)}.",
            page=g[1].page, rect=_pad(g[1].rect), check="standar",
            detail={"master": [e[1]], "naskah": [g[1].label], "lokasi": ref.where(max(0, e[0] - 1))},
        ))
    for e, g in take(lambda e, g: e[1] == g[1].label and (abs(e[0] - g[0]) <= 15 or same_ayah(e[0], g[0])
                                                          or (e[1] in AYAH_LEVEL and near_ayah(e[0], g[0])))):
        findings.append(Finding(
            category="Tanda waqaf/simbol bergeser", severity="Sedang",
            message=f"[{ref.where(max(0, e[0] - 1))}] {describe(e[1])} ada, tapi letaknya sekitar {abs(g[0] - e[0])} huruf/harakat "
                    "dari posisi di teks standar. Cek apakah tanda ini di kata yang benar.",
            page=g[1].page, rect=_pad(g[1].rect), check="standar",
            detail={"master": [e[1]], "naskah": [g[1].label], "lokasi": ref.where(max(0, e[0] - 1))},
        ))
    # tanda yang di naskah tidak terbaca (glyph tanpa kode Unicode) di sekitar posisi yang benar
    unread_left = list(unread)
    for e in list(exp_left):
        hit = next((u for u in unread_left if abs(u[0] - e[0]) <= FLOAT_TOL
                    or (e[1] in AYAH_LEVEL and same_ayah(u[0], e[0]))), None)
        if hit:
            exp_left.remove(e)
            unread_left.remove(hit)
            findings.append(Finding(
                category="Tidak terbaca (pemetaan font)", severity="Sedang",
                message=f"[{ref.where(max(0, e[0] - 1))}] Lapisan teks PDF tidak bisa dibaca di sini. Di teks standar ada {describe(e[1])}; "
                        "cek dengan mata apakah tanda itu tercetak benar.",
                page=hit[1].page, rect=_pad(hit[1].rect), check="standar",
                detail={"master": [e[1]], "naskah": [hit[1].label], "lokasi": ref.where(max(0, e[0] - 1))},
            ))
    for pos, tok in unread_left:
        findings.append(Finding(
            category="Tidak terbaca (pemetaan font)", severity="Sedang",
            message=f"[{ref.where(pos)}] Ada karakter yang tidak terbaca di lapisan teks PDF, dan teks standar tidak punya "
                    "apa-apa di posisi ini. Cek dengan mata.",
            page=tok.page, rect=_pad(tok.rect), check="standar",
            detail={"master": [], "naskah": [tok.label], "lokasi": ref.where(pos)},
        ))
    for pos, ch in exp_left:
        anchor = ref_to_naskah.get(pos) or ref_to_naskah.get(pos - 1)
        page = anchor.page if anchor else next((p.index for p in located if p.r0 <= pos <= p.r1), located[0].index)
        findings.append(Finding(
            category="Tanda waqaf/simbol hilang", severity="Tinggi",
            message=f"[{ref.where(pos)}] {describe(ch)} ada di teks standar tapi tidak ada di naskah.",
            page=page, rect=_pad(anchor.rect) if anchor else None, check="standar",
            detail={"master": [ch], "naskah": [], "lokasi": ref.where(pos)},
        ))
    for pos, tok in got_left:
        findings.append(Finding(
            category="Tanda waqaf/simbol tambahan", severity="Tinggi",
            message=f"[{ref.where(pos)}] {describe(tok.label)} ada di naskah tapi tidak ada di teks standar.",
            page=tok.page, rect=_pad(tok.rect), check="standar",
            detail={"master": [], "naskah": [tok.label], "lokasi": ref.where(pos)},
        ))
    return findings


def _pad(r, w: float = 6, h: float = 9):
    x0, y0, x1, y1 = r
    if x1 - x0 >= 4 and y1 - y0 >= 4:
        return r
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return (cx - w, cy - h, cx + w, cy + h)


def compare_with_reference(
    naskah: bytes | str,
    progress: Callable[[float, str], None] | None = None,
    reference_path: Optional[str] = None,
) -> CompareResult:
    prog = progress or (lambda f, m: None)
    ref = load_reference(reference_path or str(DATA_FILE))
    doc = fitz.open(stream=bytes(naskah), filetype="pdf") if isinstance(naskah, (bytes, bytearray)) else fitz.open(naskah)
    notes = [
        "Mode pemeriksaan: TEKS STANDAR (tanpa master PDF). Naskah dibandingkan huruf demi huruf dengan teks Al-Qur'an standar.",
        f"Sumber teks standar: {ref.source}. {ref.note}",
    ]
    findings: list[Finding] = []

    prog(0.05, "Membaca lapisan teks naskah")
    pages, no_text = _read_pages(doc)
    if not pages:
        raise ValueError(
            "Naskah ini tidak punya lapisan teks Arab (teksnya sudah di-outline menjadi kurva). "
            "Pemeriksaan dengan teks standar butuh PDF yang diekspor dari InDesign SEBELUM teks di-outline."
        )
    if no_text:
        notes.append(
            "Halaman tanpa lapisan teks Arab (tidak diperiksa terhadap teks standar): "
            + ", ".join(str(i + 1) for i in no_text[:30]) + (" …" if len(no_text) > 30 else "")
        )

    orient = _orient(ref, pages)
    if orient != "asli":
        notes.append(f"Urutan teks di lapisan PDF tidak kanan-ke-kiri; dibaca ulang dengan arah '{orient}'.")
    for p in pages:
        done = [_finish_line(ORIENTATIONS[orient](ln)) for ln in p.lines]
        done = [d for d in done if d[0]]
        p.lines = [d[0] for d in done]
        p.floats = [d[1] for d in done]
    bad = sum(1 for p in pages for ln in p.lines for t in ln if _unreadable(t.label))
    if bad:
        notes.append(
            f"PERINGATAN: {bad} karakter di lapisan teks tidak terbaca (pemetaan font ke Unicode rusak, biasanya "
            "untuk harakat bertumpuk atau ligatur). Tempat-tempat itu dilaporkan sebagai 'Tidak terbaca' dan perlu dicek mata."
        )

    # 0) baris judul surah ("سورة ..."): tidak ikut dibandingkan
    for p in pages:
        keep = []
        for i, ln in enumerate(p.lines):
            letters = "".join(t.label for t in ln if unicodedata.category(t.label).startswith("L"))
            if letters.startswith(("سورة", "سوره", "سورت")) and len(letters) <= 25:
                findings.append(Finding(
                    category="Judul surah (tidak dibandingkan)", severity="Rendah",
                    message="Baris judul surah, tidak ikut dibandingkan dengan teks standar: " + "".join(t.label for t in ln),
                    page=p.index, rect=_rect_union(ln), check="standar",
                ))
            else:
                keep.append(i)
        p.lines = [p.lines[i] for i in keep]
        p.floats = [p.floats[i] for i in keep]

    # 1) cari posisi setiap halaman di teks standar
    hint = None
    located: list[NPage] = []
    page_info: list[PageInfo] = []
    for k, p in enumerate(pages):
        prog(0.1 + 0.3 * k / len(pages), f"Mencari posisi halaman {p.index + 1} di teks standar")
        toks = [t for ln in p.lines for t in ln]
        off, conf = _locate(ref, p.text, hint)
        if off is None or conf < 0.12:
            findings.append(Finding(
                category="Halaman tidak dikenali", severity="Sedang",
                message="Isi halaman ini tidak bisa dicocokkan dengan teks Al-Qur'an standar "
                        "(mungkin halaman doa/pengantar, atau pemetaan font ke Unicode rusak). Periksa manual.",
                page=p.index, check="standar",
            ))
            page_info.append(PageInfo(p.index, "standar", None, len(toks), note="tidak dikenali"))
            continue
        p.r0, p.r1 = _trim_span(ref, off, toks)
        # baris judul surah/header: keluarkan dari pembandingan, laporkan agar dicek manual
        odd = _non_ayah_lines(ref, p)
        if odd and len(odd) < len(p.lines):
            for ln in odd:
                letters = "".join(t.label for t in ln if unicodedata.category(t.label).startswith("L"))
                if letters.startswith("سور"):
                    findings.append(Finding(
                        category="Judul surah (tidak dibandingkan)", severity="Rendah",
                        message="Baris judul surah, tidak ikut dibandingkan dengan teks standar: " + "".join(t.label for t in ln),
                        page=p.index, rect=_rect_union(ln), check="standar",
                    ))
                    continue
                findings.append(Finding(
                    category="Baris di luar teks ayat", severity="Sedang",
                    message="Baris ini tidak cocok dengan teks standar dan tidak ikut dibandingkan "
                            "(biasanya judul surah atau header; bila ini baris ayat, berarti rusak berat): "
                            + "".join(t.label for t in ln),
                    page=p.index, rect=_rect_union(ln), check="standar",
                    detail={"naskah": [t.label for t in ln]},
                ))
            keep = [i for i, ln in enumerate(p.lines) if not any(ln is o for o in odd)]
            p.lines = [p.lines[i] for i in keep]
            p.floats = [p.floats[i] for i in keep]
            toks = [t for ln in p.lines for t in ln]
            p.r0, p.r1 = _trim_span(ref, off, toks)
        hint = p.r1
        located.append(p)
        page_info.append(PageInfo(p.index, "standar", None, len(toks), note=ref.span_label(p.r0, p.r1)))

    # 2) bandingkan isi per halaman
    got_floats: list[tuple[int, Token]] = []
    got_unread: list[tuple[int, Token]] = []
    ref_to_naskah: dict[int, Token] = {}
    for k, p in enumerate(located):
        prog(0.4 + 0.45 * k / max(1, len(located)), f"Membandingkan halaman {p.index + 1} dengan teks standar")
        fs, pairs, unread = _diff_page(ref, p)
        got_unread += unread
        findings += fs
        got_floats += _page_floats(p, pairs)
        for a_tok, b_tok in pairs:
            ref_to_naskah[a_tok.raw[0]] = b_tok
        notes.append(f"Hal. {p.index + 1}: {ref.span_label(p.r0, p.r1)}.")

    findings += _compare_floats(ref, located, got_floats, ref_to_naskah, got_unread)

    # 3) kesinambungan antarhalaman
    for a, b in zip(located, located[1:]):
        if b.r0 > a.r1:
            gap = ref.text[a.r1:b.r0]
            findings.append(Finding(
                category="Teks hilang di antara halaman", severity="Tinggi",
                message=f"[{ref.where(a.r1)}] {len(gap)} karakter teks standar tidak ada di akhir hal. {a.index + 1} "
                        f"maupun awal hal. {b.index + 1}: {gap[:80]}{'…' if len(gap) > 80 else ''}",
                page=b.index, rect=_rect_union(b.lines[0]) if b.lines else None, check="standar",
                detail={"master": list(gap[:80]), "naskah": [], "lokasi": ref.where(a.r1)},
            ))
        elif b.r0 < a.r1:
            dup = ref.text[b.r0:a.r1]
            findings.append(Finding(
                category="Teks terulang di awal halaman", severity="Tinggi",
                message=f"[{ref.where(b.r0)}] Awal hal. {b.index + 1} mengulang {len(dup)} karakter dari akhir hal. {a.index + 1}: "
                        f"{dup[:80]}{'…' if len(dup) > 80 else ''}",
                page=b.index, rect=_rect_union(b.lines[0]) if b.lines else None, check="standar",
                detail={"master": [], "naskah": list(dup[:80]), "lokasi": ref.where(b.r0)},
            ))
    if located:
        first, last = located[0], located[-1]
        if not any(sg[2] == first.r0 for sg in ref.segs):
            notes.append(f"Naskah dimulai di tengah ayat ({ref.where(first.r0)}). Wajar bila naskah hanya potongan.")
        if not any(sg[3] == last.r1 for sg in ref.segs):
            notes.append(f"Naskah berakhir di tengah ayat ({ref.where(max(0, last.r1 - 1))}). Wajar bila naskah hanya potongan.")

    # 4) nomor ayat: dibaca dari lapisan teks, dibandingkan dengan nomor ayat yang selesai di rentang naskah
    total_digits = sum(1 for p in located for t in p.digits if t.label in ARABIC_DIGITS)
    if total_digits == 0:
        notes.append("Nomor ayat tidak ada di lapisan teks (mungkin berupa gambar/ornamen), jadi tidak diperiksa di mode ini.")
    else:
        expected: list[int] = []
        seen_seg: set[int] = set()
        for p in located:
            for k, (s_, a_, st, en) in enumerate(ref.segs):
                if a_ and p.r0 < en <= p.r1 + 1 and k not in seen_seg:
                    seen_seg.add(k)
                    expected.append(a_)
        # arah baca angka (kiri-ke-kanan atau terbalik) ditentukan sekali untuk seluruh naskah
        got = _ayah_numbers([t for p in located for t in p.digits])
        sm = SequenceMatcher(None, expected, [n for n, _ in got], autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                continue
            toks = [t for _, ts in got[j1:j2] for t in ts]
            near = toks or ([t for _, ts in got[j1 - 1:j1] for t in ts] if j1 > 0 else [])
            findings.append(Finding(
                category="Nomor ayat beda dengan teks standar", severity="Tinggi",
                message=f"Seharusnya: {expected[i1:i2] or '-'}; di naskah: {[n for n, _ in got[j1:j2]] or '-'}.",
                page=near[0].page if near else located[0].index, rect=_rect_union(near) if near else None, check="struktur",
            ))
        notes.append(f"Nomor ayat terbaca di naskah: {len(got)} (seharusnya {len(expected)}).")

    # 5) huruf terpotong di tepi halaman
    for p in located:
        if p.offside:
            findings.append(Finding(
                category="Terpotong di tepi halaman", severity="Tinggi",
                message=f"{len(p.offside)} karakter keluar dari batas halaman: " + "".join(t.label for t in p.offside[:20]),
                page=p.index, rect=_rect_union(p.offside), check="clip",
            ))
    notes.append(
        "Tanpa master PDF, diff visual, warna tajwid, dan elemen non-teks (header, ornamen) tidak bisa dibandingkan. "
        "Setelah edisi ini lulus tashih, simpan PDF-nya sebagai master untuk cetak ulang."
    )

    findings.sort(key=lambda f: (f.page, f.rect[1] if f.rect else 0, -(f.rect[2] if f.rect else 0), SEVERITY_ORDER[f.severity]))
    for k, f in enumerate(findings, 1):
        f.id = k
    prog(1.0, "Selesai")
    return CompareResult(findings=findings, master_pages=[], naskah_pages=page_info, notes=notes, mode="standar")
