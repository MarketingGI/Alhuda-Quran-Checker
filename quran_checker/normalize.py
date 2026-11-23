"""Normalisasi Unicode teks Arab (dipakai bila PDF punya lapisan teks hidup).

Aturan sengaja minimal dan eksplisit. Huruf yang beda makna di mushaf
(mis. ى alif maqsurah vs ي ya) TIDAK disamakan.
"""
from __future__ import annotations

import unicodedata

# Varian huruf dari keyboard Persia/Urdu yang tampil sama tapi kodenya beda
CHAR_MAP = {
    "ی": "ي",  # ی Farsi yeh -> ي
    "ک": "ك",  # ک keheh -> ك
}
# Angka Persia ۰-۹ -> angka Arab-Indik ٠-٩
CHAR_MAP.update({chr(0x06F0 + i): chr(0x0660 + i) for i in range(10)})

# Karakter tak kasatmata yang dibuang
INVISIBLE = {
    "​", "‌", "‍", "‎", "‏",  # ZWSP, ZWNJ, ZWJ, LRM, RLM
    "‪", "‫", "‬", "‭", "‮",  # penanda arah
    "⁦", "⁧", "⁨", "⁩",
    "؜",  # Arabic letter mark
    "﻿",  # BOM
    "­",  # soft hyphen
}
TATWEEL = "ـ"

# Tanda waqaf dan simbol mushaf kecil di atas/bawah baris
WAQF_MARKS = set(chr(c) for c in range(0x06D6, 0x06DD)) | {"۞", "۩"}
SMALL_HIGH = set(chr(c) for c in range(0x06DF, 0x06ED)) - {"ۥ", "ۦ", "۩"}


def _is_presentation_form(ch: str) -> bool:
    cp = ord(ch)
    return 0xFB50 <= cp <= 0xFDFF or 0xFE70 <= cp <= 0xFEFF


def normalize_text(text: str, drop_tatweel: bool = True) -> str:
    out = []
    for ch in text:
        if ch in INVISIBLE:
            continue
        if drop_tatweel and ch == TATWEEL:
            continue
        if _is_presentation_form(ch):
            ch = unicodedata.normalize("NFKC", ch)
        out.append(CHAR_MAP.get(ch, ch))
    # NFC: susun ulang harakat bertumpuk ke urutan kanonik (mis. syaddah+fathah)
    return unicodedata.normalize("NFC", "".join(out))


def char_class(ch: str) -> str:
    """Golongkan karakter untuk laporan."""
    if ch in WAQF_MARKS:
        return "tanda waqaf"
    if ch in SMALL_HIGH:
        return "tanda kecil mushaf"
    if "٠" <= ch <= "٩" or ch.isdigit():
        return "angka"
    if ch == "۝":
        return "tanda akhir ayat"
    cat = unicodedata.category(ch)
    if cat == "Mn":
        return "harakat"
    if cat.startswith("L"):
        return "huruf"
    if ch.isspace():
        return "spasi"
    return "tanda baca"


def char_name(ch: str) -> str:
    try:
        return unicodedata.name(ch)
    except ValueError:
        return f"U+{ord(ch):04X}"


def describe(ch: str) -> str:
    return f"{ch} (U+{ord(ch):04X} {char_name(ch).title()})"
