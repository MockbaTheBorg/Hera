# Hera - Hercules Hyperion GUI - by Mockba the Borg
#
"""Scripting API endpoint handlers.

Every handler operates Hera's own device state — the same state a mouse
click or keystroke would change — never Hercules directly (the one
documented exception is TAPE mount/unmount/new, which calls Hera's own
validated business logic, not an arbitrary command; see devices/tape.py).

Handler signature: handler(ctx, path_params, body) -> JSON-able value.
Raise ApiError for anything that should produce a non-200 response.
GUI-touching work is wrapped in ctx.bridge.call_on_gui_thread(...); pure
read-only backend queries (e.g. CPU register dump) may call ctx.api directly.
"""

from .errors import ApiError


# ── helpers ──────────────────────────────────────────────────────────────────

def _index(path_params: dict) -> int:
    try:
        return int(path_params["index"])
    except (KeyError, TypeError, ValueError):
        raise ApiError(400, "Invalid device index")


def _get_device(ctx, index: int):
    devices = ctx.main_window.devices()
    if not (0 <= index < len(devices)):
        raise ApiError(404, f"No device at index {index}")
    return devices[index]


def _require_class(device, expected: str) -> None:
    if device.devclass != expected:
        raise ApiError(
            400, f"Device at this index is {device.devclass!r}, expected {expected!r}"
        )


def _ensure_deck_view(device, headless_parent):
    if device._deck_view is None:
        device._create_deck_container(headless_parent)
    return device._deck_view


def _parse_hex_address(raw) -> int:
    if raw is None:
        raise ApiError(400, "Missing 'address'")
    if isinstance(raw, int):
        return raw & 0xFFF
    text = str(raw).strip()
    if text.lower().startswith("0x"):
        text = text[2:]
    try:
        return int(text, 16) & 0xFFF
    except ValueError:
        raise ApiError(400, f"Invalid address {raw!r}")


_DEVICE_ACTIONS = {
    "CONSOLE": ["select", "console/type", "console/log"],
    "CPU": ["select", "cpu/ipl_address", "cpu/ipl", "cpu/command", "cpu/state"],
    "DSP": ["select", "dsp3270/type_text", "dsp3270/aid", "dsp3270/screen",
            "dsp3270/setup", "dsp3270/connect", "dsp3270/disconnect"],
    "PRT": ["select", "printer/output", "printer/discard", "printer/save", "printer/paper_color",
            "printer/font_size", "printer/test", "printer/connect", "printer/disconnect",
            "printer/type (3215 console printer only)",
            "printer/print_command_output (3215 console printer only)"],
    "RDR": ["select", "reader/deck", "reader/load", "reader/new", "reader/submit", "reader/setup",
            "reader/toggle_view"],
    "PCH": ["select", "punch/deck", "punch/discard", "punch/save", "punch/setup",
            "punch/toggle_view", "punch/connect", "punch/disconnect"],
    "TAPE": ["select", "tape/files", "tape/mount", "tape/unmount", "tape/new", "tape/status"],
}


# ── status ───────────────────────────────────────────────────────────────────

def get_status(ctx, path_params, body):
    def _do():
        cfg = ctx.main_window.config
        return {
            "connected": ctx.main_window.is_connected(),
            "host": cfg.host,
            "port": cfg.port,
        }

    return ctx.bridge.call_on_gui_thread(_do)


# ── discovery ────────────────────────────────────────────────────────────────

def list_devices(ctx, path_params, body):
    def _do():
        devices = ctx.main_window.devices()
        selected = ctx.main_window.active_device_index()
        return [
            {
                "index": i,
                "devnum": d.devnum,
                "devclass": d.devclass,
                "devtype": d.devtype,
                "label": d.label,
                "selected": i == selected,
                "actions": _DEVICE_ACTIONS.get(d.devclass, ["select"]),
            }
            for i, d in enumerate(devices)
        ]

    return ctx.bridge.call_on_gui_thread(_do)


def get_capabilities(ctx, path_params, body):
    return {
        "routes": [
            {
                "method": entry.method,
                "path": entry.path,
                "description": entry.description,
                "params": entry.params,
            }
            for entry in ROUTES
        ]
    }


# ── device selection ─────────────────────────────────────────────────────────

def select_device(ctx, path_params, body):
    index = _index(path_params)

    def _do():
        if not (0 <= index < len(ctx.main_window.devices())):
            raise ApiError(404, f"No device at index {index}")
        ctx.main_window.select_device_by_index(index)
        return {"index": index, "selected": True}

    return ctx.bridge.call_on_gui_thread(_do)


# ── console ──────────────────────────────────────────────────────────────────

def console_type(ctx, path_params, body):
    index = _index(path_params)
    command = (body or {}).get("command")
    if not command:
        raise ApiError(400, "Missing 'command'")

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "CONSOLE")
        device._pending_command = command
        return {"queued": command}

    return ctx.bridge.call_on_gui_thread(_do)


def console_log(ctx, path_params, body):
    index = _index(path_params)

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "CONSOLE")
        if device._workspace is not None:
            return {"text": device._workspace.current_text()}
        lines = ctx.api.syslog_feed.get_all() or []
        return {"text": "\n".join(lines)}

    return ctx.bridge.call_on_gui_thread(_do)


# ── CPU ──────────────────────────────────────────────────────────────────────

_CPU_OPERATOR_COMMANDS = {"store", "restart", "startall", "stopall", "quit", "ext"}


def cpu_ipl_address(ctx, path_params, body):
    index = _index(path_params)
    addr = _parse_hex_address((body or {}).get("address"))

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "CPU")
        device.set_ipl_address(addr)
        return {"address": f"{addr:03X}"}

    return ctx.bridge.call_on_gui_thread(_do)


def cpu_ipl(ctx, path_params, body):
    index = _index(path_params)
    addr_raw = (body or {}).get("address")

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "CPU")
        if addr_raw is not None:
            device.set_ipl_address(_parse_hex_address(addr_raw))
        addr_str = f"{device._ipl_address:03X}"
        device._pending_command = f"IPL {addr_str}"
        return {"ipl_address": addr_str}

    return ctx.bridge.call_on_gui_thread(_do)


def cpu_command(ctx, path_params, body):
    index = _index(path_params)
    cmd = (body or {}).get("command")
    if cmd not in _CPU_OPERATOR_COMMANDS:
        raise ApiError(
            400, f"Unknown CPU operator command {cmd!r}; allowed: {sorted(_CPU_OPERATOR_COMMANDS)}"
        )

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "CPU")
        device._on_command(cmd)
        return {"queued": cmd}

    return ctx.bridge.call_on_gui_thread(_do)


def cpu_state(ctx, path_params, body):
    index = _index(path_params)

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "CPU")
        return {"status_text": device._status_text, "ipl_address": f"{device._ipl_address:03X}"}

    result = ctx.bridge.call_on_gui_thread(_do)
    result["cpus"] = (ctx.api.get_cpus() or {}).get("cpus", [])
    result["rates"] = ctx.api.get_rates() or {}
    return result


# ── 3270 terminal ────────────────────────────────────────────────────────────

_DSP_AID_KEYS = {"enter": 0x7D, "pa1": 0x6C, "pa2": 0x6E, "pa3": 0x6B, "clear": 0x6D}
_DSP_ACTION_KEYS = {
    "sysreq_attn", "attn", "reset", "erase_input", "dup", "field_mark", "tab", "backtab", "home",
}


def dsp3270_type_text(ctx, path_params, body):
    index = _index(path_params)
    text = (body or {}).get("text", "")
    if not text:
        raise ApiError(400, "Missing 'text'")

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "DSP")
        device.type_text(text)
        return {"sent": text}

    return ctx.bridge.call_on_gui_thread(_do)


def _pf_aid_byte(key: str):
    """Return the AID byte for 'pf1'..'pf24', or None if key isn't a PF key."""
    if not key.startswith("pf"):
        return None
    from ..widgets.terminal_screen import _PF_AIDS

    try:
        n = int(key[2:])
    except ValueError:
        return None
    return _PF_AIDS.get(n)


def dsp3270_aid(ctx, path_params, body):
    index = _index(path_params)
    key = str((body or {}).get("key", "")).lower()

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "DSP")
        pf_byte = _pf_aid_byte(key)
        if key in _DSP_AID_KEYS:
            device._send_aid(_DSP_AID_KEYS[key], focus=False)
        elif pf_byte is not None:
            device._send_aid(pf_byte, focus=False)
        elif key in _DSP_ACTION_KEYS:
            action = "sysreq_attn" if key == "attn" else key
            device._send_action(action, focus=False)
        else:
            raise ApiError(400, f"Unknown 3270 key {key!r}")
        return {"key": key}

    return ctx.bridge.call_on_gui_thread(_do)


def dsp3270_setup(ctx, path_params, body):
    index = _index(path_params)
    font_size = (body or {}).get("font_size")
    model = (body or {}).get("model")
    if font_size is None:
        raise ApiError(400, "Missing 'font_size'")

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "DSP")
        device.set_font_size(font_size)
        if model is not None:
            device.set_model(model)
        return {"font_size": device._font_size_px, "model": device._model}

    return ctx.bridge.call_on_gui_thread(_do)


def dsp3270_connect(ctx, path_params, body):
    index = _index(path_params)

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "DSP")
        if device._session is not None:
            device._session.connect_session()
            device._on_connection_state_changed(device._session_connected())
        return {"connected": device._session_connected()}

    return ctx.bridge.call_on_gui_thread(_do)


def dsp3270_disconnect(ctx, path_params, body):
    index = _index(path_params)

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "DSP")
        # Same effect as _on_disconnect_accepted, skipping the confirm
        # dialog a script cannot answer.
        if device._session is not None:
            device._session.disconnect_session()
        device._on_connection_state_changed(False)
        return {"connected": False}

    return ctx.bridge.call_on_gui_thread(_do)


def dsp3270_screen(ctx, path_params, body):
    index = _index(path_params)

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "DSP")
        cols = device._cols
        mask = list(device._protected_mask)
        protected_rows = (
            [mask[r * cols:(r + 1) * cols] for r in range(len(mask) // cols)] if mask else []
        )
        return {
            "lines": list(device._mini_lines),
            "cursor": {"row": device._cursor_row, "col": device._cursor_col},
            "protected": protected_rows,
        }

    return ctx.bridge.call_on_gui_thread(_do)


# ── printer ──────────────────────────────────────────────────────────────────

def _default_printer_path(device, config) -> str:
    import os
    from datetime import datetime
    from pathlib import Path

    prefix = "CON" if device._is_3215 else "PRT"
    spool_folder = getattr(config, "spool_folder", "spool") if config else "spool"
    spool_path = Path(os.path.expanduser(spool_folder))
    if not spool_path.is_absolute():
        spool_path = Path.cwd() / spool_path
    spool_path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return str(spool_path / f"{prefix}_{device._devnum}_{timestamp}.pdf")


def printer_type(ctx, path_params, body):
    index = _index(path_params)
    command = (body or {}).get("command")
    if not command:
        raise ApiError(400, "Missing 'command'")

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "PRT")
        if not device._is_3215:
            raise ApiError(400, "This PRT device has no command input (not a 3215 console printer)")
        device._pending_command = command
        return {"queued": command}

    return ctx.bridge.call_on_gui_thread(_do)


def printer_output(ctx, path_params, body):
    index = _index(path_params)

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "PRT")
        return {"lines": list(device._all_lines)}

    return ctx.bridge.call_on_gui_thread(_do)


def printer_discard(ctx, path_params, body):
    index = _index(path_params)

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "PRT")
        had_unsaved = bool(device._all_lines or device._queued_lines) and not device._saved
        device._clear_buffer()
        return {"discarded": True, "had_unsaved_content": had_unsaved}

    return ctx.bridge.call_on_gui_thread(_do)


def printer_save(ctx, path_params, body):
    index = _index(path_params)
    path = (body or {}).get("path")

    def _do():
        from ..devices.prt1403 import PAGE_LENGTH

        device = _get_device(ctx, index)
        _require_class(device, "PRT")
        if not device._all_lines:
            raise ApiError(409, "Printer buffer is empty")
        target = path or _default_printer_path(device, ctx.config)
        from ..widgets.printer_pdf_export import save_as_pdf

        save_as_pdf(
            lines=device._all_lines[:],
            path=target,
            font_filename=device._font_filename,
            page_length=PAGE_LENGTH,
            color_form=device._color_name,
        )
        device._saved = True
        return {"path": target}

    return ctx.bridge.call_on_gui_thread(_do)


def printer_test(ctx, path_params, body):
    index = _index(path_params)

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "PRT")
        device._do_test()
        return {"queued": True}

    return ctx.bridge.call_on_gui_thread(_do)


def printer_connect(ctx, path_params, body):
    index = _index(path_params)

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "PRT")
        device._do_connect()
        return {"connected": True}

    return ctx.bridge.call_on_gui_thread(_do)


def printer_disconnect(ctx, path_params, body):
    index = _index(path_params)

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "PRT")
        # Same effect as _on_disconnect_accepted, skipping the confirm dialog
        # a script cannot answer — the request itself is the confirmation.
        device._reader.disconnect_socket()
        device._sync_connection_buttons(False)
        return {"connected": False}

    return ctx.bridge.call_on_gui_thread(_do)


def printer_paper_color(ctx, path_params, body):
    index = _index(path_params)
    color = str((body or {}).get("color", "")).upper()

    def _do():
        from ..devices.prt1403 import PAPER_COLORS

        device = _get_device(ctx, index)
        _require_class(device, "PRT")
        if color not in PAPER_COLORS:
            raise ApiError(400, f"Unknown paper color {color!r}; allowed: {sorted(PAPER_COLORS)}")
        device._set_paper_colors(color)
        return {"color": color}

    return ctx.bridge.call_on_gui_thread(_do)


def printer_font_size(ctx, path_params, body):
    index = _index(path_params)
    font_size = (body or {}).get("font_size")
    if font_size is None:
        raise ApiError(400, "Missing 'font_size'")

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "PRT")
        device.set_font_size(font_size)
        return {"font_size": device._font_size_px}

    return ctx.bridge.call_on_gui_thread(_do)


def printer_print_command_output(ctx, path_params, body):
    index = _index(path_params)
    if "enabled" not in (body or {}):
        raise ApiError(400, "Missing 'enabled'")
    enabled = bool((body or {})["enabled"])

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "PRT")
        if not device._is_3215:
            raise ApiError(400, "This PRT device has no command input (not a 3215 console printer)")
        device._set_print_command_output(enabled)
        return {"enabled": enabled}

    return ctx.bridge.call_on_gui_thread(_do)


# ── card reader / punch ──────────────────────────────────────────────────────

def _build_setup_values(device, body):
    from ..devices.card_device_base import CardSetupValues

    body = body or {}
    return CardSetupValues(
        color=body.get("color", device._color),
        lang=body.get("lang", device._lang),
        auto_number=bool(body.get("auto_number", device._auto_number)),
        skip_separator_cards=body.get("skip_separator_cards"),
    )


def reader_deck(ctx, path_params, body):
    index = _index(path_params)

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "RDR")
        deck = _ensure_deck_view(device, ctx.bridge.headless_parent)
        return {"lines": list(deck.lines)}

    return ctx.bridge.call_on_gui_thread(_do)


def reader_load(ctx, path_params, body):
    index = _index(path_params)
    lines = (body or {}).get("lines")
    if not isinstance(lines, list):
        raise ApiError(400, "'lines' must be a list of strings")

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "RDR")
        deck = _ensure_deck_view(device, ctx.bridge.headless_parent)
        deck.set_lines(lines)
        return {"count": len(lines)}

    return ctx.bridge.call_on_gui_thread(_do)


def reader_new(ctx, path_params, body):
    index = _index(path_params)

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "RDR")
        deck = _ensure_deck_view(device, ctx.bridge.headless_parent)
        deck.clear()
        return {"cleared": True}

    return ctx.bridge.call_on_gui_thread(_do)


def reader_submit(ctx, path_params, body):
    index = _index(path_params)

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "RDR")
        _ensure_deck_view(device, ctx.bridge.headless_parent)
        device._do_submit()
        return {"submitted": True}

    return ctx.bridge.call_on_gui_thread(_do)


def reader_setup(ctx, path_params, body):
    index = _index(path_params)

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "RDR")
        _ensure_deck_view(device, ctx.bridge.headless_parent)
        device._apply_setup_values(_build_setup_values(device, body))
        return {"color": device._color, "lang": device._lang, "auto_number": device._auto_number}

    return ctx.bridge.call_on_gui_thread(_do)


def reader_toggle_view(ctx, path_params, body):
    index = _index(path_params)

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "RDR")
        _ensure_deck_view(device, ctx.bridge.headless_parent)
        device._toggle_view()
        return {"mode": device._deck_view.mode}

    return ctx.bridge.call_on_gui_thread(_do)


def punch_deck(ctx, path_params, body):
    index = _index(path_params)

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "PCH")
        deck = _ensure_deck_view(device, ctx.bridge.headless_parent)
        return {"lines": list(deck.lines)}

    return ctx.bridge.call_on_gui_thread(_do)


def punch_discard(ctx, path_params, body):
    index = _index(path_params)

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "PCH")
        deck = _ensure_deck_view(device, ctx.bridge.headless_parent)
        deck.clear()
        return {"cleared": True}

    return ctx.bridge.call_on_gui_thread(_do)


def punch_save(ctx, path_params, body):
    index = _index(path_params)
    path = (body or {}).get("path")
    if not path:
        raise ApiError(400, "Missing 'path'")

    def _do():
        from ..devices.card_data import lang_ext

        device = _get_device(ctx, index)
        _require_class(device, "PCH")
        deck = _ensure_deck_view(device, ctx.bridge.headless_parent)
        if not deck.lines:
            raise ApiError(409, "Deck is empty")
        target = path
        ext = lang_ext(device._lang)
        if not target.lower().endswith(ext):
            target += ext
        with open(target, "w", encoding="latin-1", newline="") as fh:
            for line in deck.lines:
                fh.write(line + "\n")
        deck.changed = False
        return {"path": target}

    return ctx.bridge.call_on_gui_thread(_do)


def punch_toggle_view(ctx, path_params, body):
    index = _index(path_params)

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "PCH")
        _ensure_deck_view(device, ctx.bridge.headless_parent)
        device._toggle_view()
        return {"mode": device._deck_view.mode}

    return ctx.bridge.call_on_gui_thread(_do)


def punch_connect(ctx, path_params, body):
    index = _index(path_params)

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "PCH")
        device._do_connect()
        return {"connected": bool(device._reader is not None and device._reader.is_connected)}

    return ctx.bridge.call_on_gui_thread(_do)


def punch_disconnect(ctx, path_params, body):
    index = _index(path_params)

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "PCH")
        # Same effect as _on_disconnect_accepted, skipping the confirm dialog.
        if device._reader is not None:
            device._reader.disconnect_socket()
        device._update_connection_buttons()
        return {"connected": False}

    return ctx.bridge.call_on_gui_thread(_do)


def punch_setup(ctx, path_params, body):
    index = _index(path_params)

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "PCH")
        _ensure_deck_view(device, ctx.bridge.headless_parent)
        device._apply_setup_values(_build_setup_values(device, body))
        if body and "skip_separator_cards" in body:
            new_val = bool(body["skip_separator_cards"])
            if new_val != device._skip_separator_cards:
                device._skip_separator_cards = new_val
                device._set_persisted_setting(
                    device._skip_separator_key(), "1" if new_val else "0"
                )
        return {
            "color": device._color,
            "lang": device._lang,
            "auto_number": device._auto_number,
            "skip_separator_cards": device._skip_separator_cards,
        }

    return ctx.bridge.call_on_gui_thread(_do)


# ── tape ─────────────────────────────────────────────────────────────────────

def tape_files(ctx, path_params, body):
    index = _index(path_params)

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "TAPE")
        try:
            return {"files": device.list_tape_files()}
        except ValueError as exc:
            raise ApiError(409, str(exc))

    return ctx.bridge.call_on_gui_thread(_do)


def tape_mount(ctx, path_params, body):
    index = _index(path_params)
    filename = (body or {}).get("filename")
    readonly = bool((body or {}).get("readonly", False))
    if not filename:
        raise ApiError(400, "Missing 'filename'")

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "TAPE")
        try:
            return device.mount_tape(filename, readonly=readonly)
        except ValueError as exc:
            raise ApiError(409, str(exc))

    return ctx.bridge.call_on_gui_thread(_do)


def tape_unmount(ctx, path_params, body):
    index = _index(path_params)

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "TAPE")
        try:
            return device.unmount_tape()
        except ValueError as exc:
            raise ApiError(409, str(exc))

    return ctx.bridge.call_on_gui_thread(_do)


def tape_new(ctx, path_params, body):
    index = _index(path_params)
    filename = (body or {}).get("filename")
    volser = (body or {}).get("volser")
    owner = (body or {}).get("owner", "")
    overwrite = bool((body or {}).get("overwrite", False))
    if not filename or not volser:
        raise ApiError(400, "Missing 'filename' or 'volser'")

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "TAPE")
        try:
            return device.new_tape(filename, volser, owner=owner, overwrite=overwrite)
        except ValueError as exc:
            raise ApiError(409, str(exc))

    return ctx.bridge.call_on_gui_thread(_do)


def tape_status(ctx, path_params, body):
    index = _index(path_params)

    def _do():
        device = _get_device(ctx, index)
        _require_class(device, "TAPE")
        return {
            "loaded": device._loaded,
            "protected": device._protected,
            "vol_label": device._vol_label,
            "display_text": device._visible_display_text(),
        }

    return ctx.bridge.call_on_gui_thread(_do)


# ── global preferences ───────────────────────────────────────────────────────

def _read_preferences(ctx) -> dict:
    """Must only be called already on the GUI thread (see set_preferences,
    which calls this directly rather than through get_preferences to avoid
    re-entering call_on_gui_thread from within the GUI thread itself)."""
    from ..config import format_device_order

    cfg = ctx.main_window.config
    return {
        "host": cfg.host,
        "port": cfg.port,
        "poll_interval": cfg.poll_interval,
        "tapes_folder": cfg.tapes_folder,
        "spool_folder": cfg.spool_folder,
        "bitmap_theme": cfg.bitmap_theme,
        "room_background": cfg.room_background,
        "device_order": format_device_order(cfg.device_order),
        "window_x": cfg.window_x,
        "window_y": cfg.window_y,
        "window_width": cfg.window_width,
        "window_height": cfg.window_height,
    }


def get_preferences(ctx, path_params, body):
    return ctx.bridge.call_on_gui_thread(lambda: _read_preferences(ctx))


def set_preferences(ctx, path_params, body):
    def _do():
        current = _read_preferences(ctx)
        merged = {**current, **(body or {})}
        merged["port"] = int(merged["port"])
        merged["poll_interval"] = float(merged["poll_interval"])
        merged["window_x"] = int(merged["window_x"])
        merged["window_y"] = int(merged["window_y"])
        merged["window_width"] = int(merged["window_width"])
        merged["window_height"] = int(merged["window_height"])
        ctx.main_window.apply_settings(merged)
        return _read_preferences(ctx)

    return ctx.bridge.call_on_gui_thread(_do)


# ── route table (also drives GET /capabilities) ────────────────────────────

class RouteSpec:
    __slots__ = ("method", "path", "handler", "description", "params")

    def __init__(self, method, path, handler, description, params):
        self.method = method
        self.path = path
        self.handler = handler
        self.description = description
        self.params = params


ROUTES: list[RouteSpec] = [
    RouteSpec("GET", "/status", get_status,
              "Whether Hera currently sees Hercules as connected (and what host:port it targets)", {}),
    RouteSpec("GET", "/devices", list_devices,
              "List devices currently shown in the room (matches the live Hercules configuration)", {}),
    RouteSpec("GET", "/capabilities", get_capabilities,
              "Describe every available route and its parameters", {}),
    RouteSpec("POST", "/devices/{index}/select", select_device,
              "Bring a device to the front, exactly like clicking its room slot", {}),
    RouteSpec("POST", "/devices/{index}/console/type", console_type,
              "Send a command to a CONSOLE device, as if typed and entered", {"command": "string"}),
    RouteSpec("GET", "/devices/{index}/console/log", console_log,
              "Read the current CONSOLE log text", {}),
    RouteSpec("POST", "/devices/{index}/cpu/ipl_address", cpu_ipl_address,
              "Set the CPU IPL address dials", {"address": "string (hex)"}),
    RouteSpec("POST", "/devices/{index}/cpu/ipl", cpu_ipl,
              "Optionally set the IPL address, then IPL the CPU",
              {"address": "string (hex, optional)"}),
    RouteSpec("POST", "/devices/{index}/cpu/command", cpu_command,
              "Press a CPU operator button",
              {"command": f"one of {sorted(_CPU_OPERATOR_COMMANDS)}"}),
    RouteSpec("GET", "/devices/{index}/cpu/state", cpu_state,
              "Read CPU status and registers", {}),
    RouteSpec("POST", "/devices/{index}/dsp3270/type_text", dsp3270_type_text,
              "Type text into a 3270 terminal; no trailing newline leaves it pending",
              {"text": "string"}),
    RouteSpec("POST", "/devices/{index}/dsp3270/aid", dsp3270_aid,
              "Send a 3270 AID key or keyboard action",
              {"key": f"one of {sorted(_DSP_AID_KEYS)}, 'pf1'..'pf24', or {sorted(_DSP_ACTION_KEYS)}"}),
    RouteSpec("GET", "/devices/{index}/dsp3270/screen", dsp3270_screen,
              "Read the current 3270 screen text, cursor position, and per-cell protected/unprotected map",
              {}),
    RouteSpec("POST", "/devices/{index}/dsp3270/setup", dsp3270_setup,
              "Change the 3270 terminal font size and/or monitor model",
              {"font_size": "int (10-32)", "model": "int, optional (2/3/4/5)"}),
    RouteSpec("POST", "/devices/{index}/dsp3270/connect", dsp3270_connect,
              "Connect the 3270 terminal's socket", {}),
    RouteSpec("POST", "/devices/{index}/dsp3270/disconnect", dsp3270_disconnect,
              "Disconnect the 3270 terminal's socket", {}),
    RouteSpec("POST", "/devices/{index}/printer/type", printer_type,
              "Send a command to a 3215 console printer, as if typed and entered (no-op for a 1403)",
              {"command": "string"}),
    RouteSpec("GET", "/devices/{index}/printer/output", printer_output,
              "Read the printer's buffered output", {}),
    RouteSpec("POST", "/devices/{index}/printer/discard", printer_discard,
              "Discard the printer's buffered output", {}),
    RouteSpec("POST", "/devices/{index}/printer/save", printer_save,
              "Save the printer's buffered output as a PDF", {"path": "string (optional)"}),
    RouteSpec("POST", "/devices/{index}/printer/paper_color", printer_paper_color,
              "Change the printer paper color", {"color": "string"}),
    RouteSpec("POST", "/devices/{index}/printer/font_size", printer_font_size,
              "Change the printer workspace's paper font size (does not affect the room mini-print)",
              {"font_size": "int (6-30)"}),
    RouteSpec("POST", "/devices/{index}/printer/print_command_output", printer_print_command_output,
              "Toggle echoing 3215 command output onto the console printer (3215 only)",
              {"enabled": "bool"}),
    RouteSpec("POST", "/devices/{index}/printer/test", printer_test,
              "Trigger the printer's built-in test printout", {}),
    RouteSpec("POST", "/devices/{index}/printer/connect", printer_connect,
              "Connect the printer's socket", {}),
    RouteSpec("POST", "/devices/{index}/printer/disconnect", printer_disconnect,
              "Disconnect the printer's socket", {}),
    RouteSpec("GET", "/devices/{index}/reader/deck", reader_deck,
              "Read the card reader deck content", {}),
    RouteSpec("POST", "/devices/{index}/reader/load", reader_load,
              "Load lines into the card reader deck", {"lines": "list[string]"}),
    RouteSpec("POST", "/devices/{index}/reader/new", reader_new,
              "Clear the card reader deck", {}),
    RouteSpec("POST", "/devices/{index}/reader/submit", reader_submit,
              "Submit the card reader deck to Hercules", {}),
    RouteSpec("POST", "/devices/{index}/reader/setup", reader_setup,
              "Change card reader color/language/auto-number settings",
              {"color": "string (optional)", "lang": "string (optional)",
               "auto_number": "bool (optional)"}),
    RouteSpec("POST", "/devices/{index}/reader/toggle_view", reader_toggle_view,
              "Toggle the card reader deck between editor and card view", {}),
    RouteSpec("GET", "/devices/{index}/punch/deck", punch_deck,
              "Read the card punch deck content", {}),
    RouteSpec("POST", "/devices/{index}/punch/discard", punch_discard,
              "Discard the card punch deck", {}),
    RouteSpec("POST", "/devices/{index}/punch/save", punch_save,
              "Save the card punch deck to a file", {"path": "string"}),
    RouteSpec("POST", "/devices/{index}/punch/setup", punch_setup,
              "Change card punch color/language/auto-number/separator settings",
              {"color": "string (optional)", "lang": "string (optional)",
               "auto_number": "bool (optional)", "skip_separator_cards": "bool (optional)"}),
    RouteSpec("POST", "/devices/{index}/punch/toggle_view", punch_toggle_view,
              "Toggle the card punch deck between editor and card view", {}),
    RouteSpec("POST", "/devices/{index}/punch/connect", punch_connect,
              "Connect the card punch's socket", {}),
    RouteSpec("POST", "/devices/{index}/punch/disconnect", punch_disconnect,
              "Disconnect the card punch's socket", {}),
    RouteSpec("GET", "/devices/{index}/tape/files", tape_files,
              "List tape files available to mount", {}),
    RouteSpec("POST", "/devices/{index}/tape/mount", tape_mount,
              "Mount a tape file", {"filename": "string", "readonly": "bool (optional)"}),
    RouteSpec("POST", "/devices/{index}/tape/unmount", tape_unmount,
              "Unmount the current tape", {}),
    RouteSpec("POST", "/devices/{index}/tape/new", tape_new,
              "Create a new tape file and mount it",
              {"filename": "string", "volser": "string", "owner": "string (optional)",
               "overwrite": "bool (optional)"}),
    RouteSpec("GET", "/devices/{index}/tape/status", tape_status,
              "Read tape drive status", {}),
    RouteSpec("GET", "/preferences", get_preferences, "Read global preferences", {}),
    RouteSpec("POST", "/preferences", set_preferences,
              "Change global preferences (room background, theme, etc.) without opening the dialog",
              {"...": "any subset of the fields returned by GET /preferences"}),
]
