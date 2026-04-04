# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Shared card-domain constants and helpers.
"""

import os

DEFAULT_LANGUAGE = "NONE"
FALLBACK_LANGUAGE = "NONE"

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

DATA_COLS = 72
SEQ_COLS = 8
TOTAL_COLS = DATA_COLS + SEQ_COLS

_LANGUAGE_DEFAULTS: dict[str, object] = {
    "ext": ".txt",
    "tab_stops": [8, 16, 24, 32, 40, 48, 56, 64, 72],
    "painted_columns": [],
    "separator_columns": [DATA_COLS],
}

# Central language registry for setup choices and editor behavior.
# Add new languages here. Any missing field falls back to the NONE/default value.
LANGUAGE_DEFINITIONS: dict[str, dict[str, object]] = {
    "JCL": {
        "ext": ".jcl",
        "tab_stops": [6, 12, 72],
        "painted_columns": [5, 11],
        "separator_columns": [5, 6, 11, 12, 71, DATA_COLS],
    },
    "FORTRAN": {
        "ext": ".for",
        "tab_stops": [5, 6, 10, 14, 18, 22, 26, 30, 34, 38, 42, 46, 50, 54, 58, 72],
        "painted_columns": [5],
        "separator_columns": [5, 6, DATA_COLS],
    },
    "ASM": {
        "ext": ".asm",
        "tab_stops": [9, 15, 24, 29, 34, 39, 44, 49, 54, 59, 64, 72],
        "painted_columns": [8, 14],
        "separator_columns": [8, 9, 14, 15, 71, DATA_COLS],
    },
    "NONE": {
        "ext": ".txt",
        "tab_stops": [8, 16, 24, 32, 40, 48, 56, 64, 72],
        "painted_columns": [],
        "separator_columns": [DATA_COLS],
    },
}

LANGUAGES = list(LANGUAGE_DEFINITIONS.keys())


def hollerith_holes(char: str) -> list[int]:
    """Return Hollerith row indices (-2..9) for char. Uppercased."""
    return HOLLERITH.get(char.upper(), [])


def language_names() -> list[str]:
    """Return the available editor languages in UI order."""
    return list(LANGUAGES)


def _language_value(lang: str, key: str):
    fallback = LANGUAGE_DEFINITIONS.get(FALLBACK_LANGUAGE, {})
    definition = LANGUAGE_DEFINITIONS.get(lang, {})
    if key in definition:
        return definition[key]
    if key in fallback:
        return fallback[key]
    return _LANGUAGE_DEFAULTS[key]


def lang_ext(lang: str) -> str:
    """Return file extension (with dot) for a language mode."""
    return str(_language_value(lang, "ext"))


def language_for_extension(ext: str) -> str:
    """Return the language matching a filename extension, else NONE."""
    normalized_ext = ext.lower()
    if normalized_ext and not normalized_ext.startswith("."):
        normalized_ext = f".{normalized_ext}"

    for lang in language_names():
        if lang_ext(lang).lower() == normalized_ext:
            return lang
    return FALLBACK_LANGUAGE


def language_for_path(path: str) -> str:
    """Return the language matching a file path, else NONE."""
    return language_for_extension(os.path.splitext(path)[1])


def painted_columns(lang: str) -> list[int]:
    """Return zero-based columns painted as green language bands."""
    return list(_language_value(lang, "painted_columns"))


def separator_columns(lang: str) -> list[int]:
    """Return zero-based columns rendered as full-height separators."""
    return list(_language_value(lang, "separator_columns"))


def pad80(line: str) -> str:
    """Return line padded / truncated to exactly 80 characters."""
    return (line + " " * 80)[:80]


def tabs_for_line(lang: str) -> list[int]:
    """Return 1-indexed tab stops for the selected language mode."""
    return list(_language_value(lang, "tab_stops"))
