"""Struktur data bersama untuk semua modul."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

Rect = tuple[float, float, float, float]  # x0, y0, x1, y1 dalam satuan pt PDF

SEVERITY_ORDER = {"Tinggi": 0, "Sedang": 1, "Rendah": 2}


@dataclass
class Token:
    """Satu unit yang dibandingkan.

    Mode vektor: satu path (bentuk huruf/harakat/tanda) atau satu penanda ayat utuh.
    Mode teks: satu karakter Unicode yang sudah dinormalisasi.
    """

    page: int
    key: tuple  # kunci kasar untuk penyelarasan (tanpa posisi absolut)
    rect: Rect
    kind: str  # 'glyph' | 'marker' | 'char'
    fine: tuple = ()  # koordinat relatif presisi, untuk cek toleransi bentuk
    color: tuple = ()
    clip: Optional[Rect] = None
    line: int = 0
    label: str = ""  # untuk mode teks: karakter; untuk vektor: deskripsi singkat
    small: bool = False  # tanda kecil (harakat/titik/waqaf) vs huruf besar
    raw: tuple = ()  # data path mentah; koordinat presisi dihitung bila perlu (hemat waktu)


@dataclass
class Finding:
    category: str
    severity: str
    message: str
    page: int  # indeks halaman naskah (0-based)
    rect: Optional[Rect] = None  # lokasi di naskah
    master_page: Optional[int] = None
    master_rect: Optional[Rect] = None
    check: str = ""  # 'glyph' | 'teks' | 'visual' | 'struktur' | 'clip' | 'dekorasi'
    detail: dict = field(default_factory=dict)
    id: int = 0


@dataclass
class PageInfo:
    index: int
    mode: str  # 'teks' atau 'vektor'
    frame: Optional[Rect]
    n_tokens: int
    note: str = ""


@dataclass
class CompareResult:
    findings: list[Finding]
    master_pages: list[PageInfo]
    naskah_pages: list[PageInfo]
    notes: list[str]
    mode: str
