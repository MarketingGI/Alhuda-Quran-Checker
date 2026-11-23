"""Penyelarasan urutan token master vs naskah (tahan reflow).

Dua tingkat:
1. Baris dibandingkan sebagai satu kesatuan (cepat, untuk dokumen ratusan halaman).
2. Blok baris yang tidak sama dibandingkan per token.
Posisi absolut tidak dipakai sebagai kunci, jadi baris/halaman yang bergeser
tetap cocok selama urutan isinya sama.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .models import Token


@dataclass
class DiffBlock:
    a: list[Token]
    b: list[Token]
    prev_pair: tuple[Token, Token] | None = None  # pasangan sama terakhir sebelum blok
    next_pair: tuple[Token, Token] | None = None


@dataclass
class Alignment:
    pairs: list[tuple[Token, Token]] = field(default_factory=list)  # urut menurut naskah
    blocks: list[DiffBlock] = field(default_factory=list)


def align(a_lines: list[list[Token]], b_lines: list[list[Token]]) -> Alignment:
    out = Alignment()
    akeys = [tuple(t.key for t in ln) for ln in a_lines]
    bkeys = [tuple(t.key for t in ln) for ln in b_lines]
    sm = SequenceMatcher(None, akeys, bkeys, autojunk=False)
    pending: list[DiffBlock] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for la, lb in zip(a_lines[i1:i2], b_lines[j1:j2]):
                _add_pairs(out, pending, list(zip(la, lb)))
            continue
        ta = [t for ln in a_lines[i1:i2] for t in ln]
        tb = [t for ln in b_lines[j1:j2] for t in ln]
        _align_tokens(out, pending, ta, tb)
    for blk in pending:  # blok di ujung dokumen
        out.blocks.append(blk)
    return out


def _add_pairs(out: Alignment, pending: list[DiffBlock], pairs):
    if not pairs:
        return
    for blk in pending:
        blk.next_pair = pairs[0]
        out.blocks.append(blk)
    pending.clear()
    out.pairs.extend(pairs)


def _align_tokens(out: Alignment, pending: list[DiffBlock], ta: list[Token], tb: list[Token]):
    sm = SequenceMatcher(None, [t.key for t in ta], [t.key for t in tb], autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            _add_pairs(out, pending, list(zip(ta[i1:i2], tb[j1:j2])))
        else:
            prev = out.pairs[-1] if out.pairs else None
            pending.append(DiffBlock(a=ta[i1:i2], b=tb[j1:j2], prev_pair=prev))
