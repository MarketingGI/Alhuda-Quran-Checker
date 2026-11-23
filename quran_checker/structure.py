"""Pemeriksaan struktur: nomor ayat, basmalah, penanda juz/hizb/sajdah."""
from __future__ import annotations

from difflib import SequenceMatcher

from .models import Finding, Token

ARABIC_DIGITS = {chr(0x0660 + i): i for i in range(10)}
BASMALAH_SKELETON = "بسماللهالرحمنالرحيم"
RUB_EL_HIZB = "۞"  # ۞
SAJDAH = "۩"  # ۩


def _ayah_numbers(tokens: list[Token]) -> list[tuple[int, list[Token]]]:
    out = []
    run: list[Token] = []
    for t in tokens + [None]:
        if t is not None and t.kind == "char" and t.label in ARABIC_DIGITS:
            run.append(t)
            continue
        if run:
            out.append(run)
            run = []
    # Urutan angka di PDF bisa tersimpan kiri-ke-kanan atau terbalik.
    # Pilih arah baca yang menghasilkan paling banyak nomor berurutan (n -> n+1).
    def read(runs, rev):
        return [int("".join(str(ARABIC_DIGITS[x.label]) for x in (r[::-1] if rev else r))) for r in runs]

    def score(nums):
        return sum(1 for p, c in zip(nums, nums[1:]) if c == p + 1)

    fwd, bwd = read(out, False), read(out, True)
    nums = bwd if score(bwd) > score(fwd) else fwd
    return list(zip(nums, out))


def _skeleton(tokens: list[Token]) -> str:
    import unicodedata

    return "".join(
        t.label for t in tokens if t.kind == "char" and unicodedata.category(t.label).startswith("L")
    ).replace("ٱ", "ا").replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")


def check_text_structure(a_tokens: list[Token], b_tokens: list[Token]) -> tuple[list[Finding], list[str]]:
    findings: list[Finding] = []
    notes: list[str] = []
    an = _ayah_numbers(a_tokens)
    bn = _ayah_numbers(b_tokens)
    notes.append(f"Nomor ayat terbaca: master {len(an)}, naskah {len(bn)}.")

    # 1) urutan nomor ayat di naskah: naik 1, atau kembali ke 1 (surah baru)
    for (prev, _), (cur, toks) in zip(bn, bn[1:]):
        if cur != prev + 1 and cur != 1:
            findings.append(
                Finding(
                    category="Nomor ayat tidak berurutan",
                    severity="Tinggi",
                    message=f"Setelah ayat {prev} muncul nomor {cur}.",
                    page=toks[0].page,
                    rect=_union(toks),
                    check="struktur",
                )
            )
    # 2) bandingkan daftar nomor dengan master
    sm = SequenceMatcher(None, [n for n, _ in an], [n for n, _ in bn], autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        ma = [n for n, _ in an[i1:i2]]
        nb = [n for n, _ in bn[j1:j2]]
        toks = [t for _, ts in bn[j1:j2] for t in ts]
        page = toks[0].page if toks else (bn[j1 - 1][1][0].page if j1 > 0 and bn else 0)
        findings.append(
            Finding(
                category="Nomor ayat beda dengan master",
                severity="Tinggi",
                message=f"Master: {ma or '-'}; naskah: {nb or '-'}.",
                page=page,
                rect=_union(toks) if toks else None,
                master_page=an[i1][1][0].page if ma else None,
                master_rect=_union(an[i1][1]) if ma else None,
                check="struktur",
            )
        )
    # 3) jumlah basmalah & penanda hizb/sajdah
    for name, fa, fb in (
        ("basmalah", _skeleton(a_tokens).count(BASMALAH_SKELETON), _skeleton(b_tokens).count(BASMALAH_SKELETON)),
        ("tanda rub'/hizb ۞", sum(t.label == RUB_EL_HIZB for t in a_tokens), sum(t.label == RUB_EL_HIZB for t in b_tokens)),
        ("tanda sajdah ۩", sum(t.label == SAJDAH for t in a_tokens), sum(t.label == SAJDAH for t in b_tokens)),
    ):
        notes.append(f"Jumlah {name}: master {fa}, naskah {fb}.")
        if fa != fb:
            findings.append(
                Finding(
                    category=f"Jumlah {name} beda",
                    severity="Tinggi",
                    message=f"Master {fa}, naskah {fb}.",
                    page=0,
                    check="struktur",
                )
            )
    return findings, notes


def check_vector_structure(a_markers: list[Token], b_markers: list[Token], a_pages: int, b_pages: int) -> tuple[list[Finding], list[str]]:
    """Mode vektor: angka di penanda ayat berupa kurva, jadi dibandingkan per bentuk.

    Penanda ayat yang beda bentuk/hilang/tambah sudah dilaporkan oleh diff glyph.
    Di sini dicatat ringkasan jumlah, plus duplikasi penanda di halaman yang sama.
    """
    findings: list[Finding] = []
    notes = [f"Penanda ayat/simbol (bulatan): master {len(a_markers)}, naskah {len(b_markers)}."]
    if len(a_markers) != len(b_markers):
        findings.append(
            Finding(
                category="Jumlah penanda ayat beda",
                severity="Tinggi",
                message=f"Master {len(a_markers)} penanda, naskah {len(b_markers)} penanda.",
                page=0,
                check="struktur",
            )
        )
    if a_pages == b_pages:
        for p in range(b_pages):
            na = sum(1 for m in a_markers if m.page == p)
            nb = sum(1 for m in b_markers if m.page == p)
            if na != nb:
                notes.append(f"Hal. {p + 1}: penanda ayat master {na}, naskah {nb}.")
    # nomor ayat yang sama muncul dua kali di satu halaman = kemungkinan salah nomor
    seen: dict = {}
    for m in b_markers:
        k = (m.page, m.key)
        if k in seen and seen[k] == 1:
            ref = [x for x in a_markers if x.key == m.key]
            if not any(sum(1 for y in a_markers if y.page == x.page and y.key == m.key) > 1 for x in ref):
                findings.append(
                    Finding(
                        category="Penanda ayat ganda",
                        severity="Tinggi",
                        message="Dua penanda ayat dengan bentuk (nomor) yang sama di halaman ini.",
                        page=m.page,
                        rect=m.rect,
                        check="struktur",
                    )
                )
        seen[k] = seen.get(k, 0) + 1
    return findings, notes


def _union(tokens: list[Token]):
    return (
        min(t.rect[0] for t in tokens),
        min(t.rect[1] for t in tokens),
        max(t.rect[2] for t in tokens),
        max(t.rect[3] for t in tokens),
    )
