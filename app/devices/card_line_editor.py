# Hera - Hercules Hyperion GUI - by Mockba the Borg
#
"""
Pure TSO/ISPF-EDIT-style line editor commands for a card deck buffer.

No Qt dependency — operates on a plain list[str] plus an integer line
pointer. Used by the reader/editor scripting API route; the route is
responsible for pushing the mutated list back into the deck widget via
set_lines() so the GUI stays in sync.

Pointer model: 0-based, valid range [0, len(lines)]. ptr == len(lines) is
the END state (one past the last line, ready to append).

Per card_editor.py: cols 0-71 are the editable data area, cols 72-79 are a
locked sequence-number zone regenerated on every set_lines() regardless of
what a caller writes there. FIND/CHANGE/LIST here only ever look at the
data area (line[:DATA_COLS]) — matching that lock — and INSERT/REPLACE
report `"truncated": true` when the supplied text overflows it, since
anything past col 72 is silently discarded downstream.
"""

import re

from .card_data import DATA_COLS

_QUOTED = re.compile(r"'((?:[^']|'')*)'")
_BARE_SIGN = re.compile(r"([+-])(\d*)")


class EditorCommandError(Exception):
    pass


def _parse_quoted(rest: str) -> list[str]:
    values = []
    rest = rest.strip()
    while rest.startswith("'"):
        m = _QUOTED.match(rest)
        if not m:
            raise EditorCommandError("Unterminated quoted string")
        values.append(m.group(1).replace("''", "'"))
        rest = rest[m.end():].strip()
    return values


def _parse_int(rest: str, default):
    tok = rest.split()[0] if rest.split() else ""
    if not tok:
        return default
    try:
        return int(tok)
    except ValueError:
        raise EditorCommandError(f"Expected a number, got {tok!r}")


def _overflow(text: str) -> bool:
    """True if `text` has non-blank content beyond DATA_COLS. Growing a
    replacement inside an already-padded 72-char line can push its raw
    length past 72 while only displacing trailing blanks — that's not a
    real truncation, so check what's actually cut off, not the length."""
    return bool(text[DATA_COLS:].strip())


def describe_ptr(lines: list[str], ptr: int) -> dict:
    total = len(lines)
    at_end = ptr >= total
    return {"ptr": None if at_end else ptr + 1, "at_end": at_end, "total_lines": total}


def apply_command(lines: list[str], ptr: int, command: str) -> tuple[int, dict]:
    """Mutates `lines` in place. Returns (new_ptr, extra_result_fields)."""
    text = (command or "").strip()
    if not text:
        raise EditorCommandError("Empty command")

    total = len(lines)

    m = _BARE_SIGN.fullmatch(text)
    if m:
        sign, digits = m.groups()
        n = int(digits) if digits else 1
        if sign == "-":
            return max(0, ptr - n), {}
        return min(total, ptr + n), {}

    parts = text.split(None, 1)
    kw = parts[0].upper()
    rest = parts[1] if len(parts) > 1 else ""

    if kw == "TOP":
        return 0, {}

    if kw == "BOTTOM":
        return max(0, total - 1), {}

    if kw == "END":
        return total, {}

    if kw == "UP":
        n = _parse_int(rest, 1)
        return max(0, ptr - n), {}

    if kw == "DOWN":
        n = _parse_int(rest, 1)
        return min(total, ptr + n), {}

    if kw == "FIND":
        values = _parse_quoted(rest)
        if not values:
            raise EditorCommandError("FIND requires a quoted string")
        needle = values[0]
        start = min(ptr, total)
        for i in range(start, total):
            if needle in lines[i][:DATA_COLS]:
                return i, {"found": True}
        return ptr, {"found": False}

    if kw == "CHANGE":
        values = _parse_quoted(rest)
        if len(values) != 2:
            raise EditorCommandError("CHANGE requires two quoted strings: CHANGE 'a' 'b'")
        if ptr >= total:
            raise EditorCommandError("No current line (pointer at END)")
        old, new = values
        data = lines[ptr][:DATA_COLS]
        if old not in data:
            return ptr, {"changed": False}
        new_data = data.replace(old, new, 1)
        extra = {"changed": True}
        if _overflow(new_data):
            extra["truncated"] = True
        lines[ptr] = new_data[:DATA_COLS]
        return ptr, extra

    if kw == "INSERT":
        values = _parse_quoted(rest)
        new_text = values[0] if values else ""
        extra = {"inserted_at": ptr + 1}
        if _overflow(new_text):
            extra["truncated"] = True
        lines.insert(ptr, new_text[:DATA_COLS])
        return ptr + 1, extra

    if kw == "REPLACE":
        values = _parse_quoted(rest)
        new_text = values[0] if values else ""
        if ptr >= total:
            raise EditorCommandError("No current line (pointer at END); use INSERT")
        extra = {"replaced": True}
        if _overflow(new_text):
            extra["truncated"] = True
        lines[ptr] = new_text[:DATA_COLS]
        return ptr, extra

    if kw == "LIST":
        n = _parse_int(rest, None)
        if not n:
            lo = hi = ptr
        elif n > 0:
            lo, hi = ptr, ptr + n - 1
        else:
            hi = ptr
            lo = ptr + n + 1
        lo = max(0, lo)
        hi = min(total - 1, hi)
        if lo > hi:
            return ptr, {"lines": []}
        return ptr, {
            "lines": [
                {"line": i + 1, "text": lines[i][:DATA_COLS].rstrip()}
                for i in range(lo, hi + 1)
            ]
        }

    raise EditorCommandError(f"Unknown editor command {parts[0]!r}")
