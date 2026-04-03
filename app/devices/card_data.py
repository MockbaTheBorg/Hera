# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Shared card-domain constants and helpers.
"""

LANGUAGES = ["JCL", "FORTRAN", "ASM", "NONE"]

LANG_EXT: dict[str, str] = {
    "JCL": ".jcl",
    "FORTRAN": ".for",
    "ASM": ".asm",
    "NONE": ".txt",
}

_CHARS = (
    ' &-0123456789ABCDEFGHIJKLMNOPQR/STUVWXYZ:#@' + "'" +
    '="[.<(+|]$*);^' + '\\' + ',%_>?'
)

_HOLES: list[list[int]] = [[]]
_HOLES.extend([[r] for r in range(-2, 10)])
_HOLES.extend([[-2, r] for r in range(1, 10)])
_HOLES.extend([[-1, r] for r in range(1, 10)])
_HOLES.extend([[0, r] for r in range(1, 10)])
_HOLES.extend([[r, 8] for r in range(2, 8)])
_HOLES.extend([[-2, r, 8] for r in range(2, 8)])
_HOLES.extend([[-1, r, 8] for r in range(2, 8)])
_HOLES.extend([[0, r, 8] for r in range(2, 8)])

HOLLERITH: dict[str, list[int]] = {
    ch: holes for ch, holes in zip(_CHARS, _HOLES)
}

_TABS: dict[str, list[int]] = {
    "JCL": [11, 15, 24, 32, 40, 48, 56, 64, 72],
    "ASM": [9, 15, 24, 29, 34, 39, 44, 49, 54, 59, 64, 72],
    "FORTRAN": [5, 6, 10, 14, 18, 22, 26, 30, 34, 38, 42, 46, 50, 54, 58, 72],
    "NONE": [8, 16, 24, 32, 40, 48, 56, 64, 72],
}

DATA_COLS = 72
SEQ_COLS = 8
TOTAL_COLS = DATA_COLS + SEQ_COLS


def hollerith_holes(char: str) -> list[int]:
    """Return Hollerith row indices (-2..9) for char. Uppercased."""
    return HOLLERITH.get(char.upper(), [])


def lang_ext(lang: str) -> str:
    """Return file extension (with dot) for a language mode."""
    return LANG_EXT.get(lang, ".txt")


def pad80(line: str) -> str:
    """Return line padded / truncated to exactly 80 characters."""
    return (line + " " * 80)[:80]


def tabs_for_line(line: str, lang: str) -> list[int]:
    """Return 1-indexed tab stops for this line."""
    if line.startswith("//"):
        return _TABS["JCL"]
    return _TABS.get(lang, _TABS["NONE"])
