#!/usr/bin/env python3
# Hera - Hercules Hyperion GUI - by Mockba the Borg
#
"""heractl - command-line client for Hera's scripting API.

Every device panel Hera can show, and every global preference, is reachable
here the same way it is reachable from examples/common.sh: HERA_API_URL and
HERA_API_TOKEN are honored as defaults, and -h/-p/-t override them.

Usage:
    heractl.py [-h HOST] [-p PORT] [-t TOKEN] [--raw] <command> [args...]
    heractl.py --help

Examples:
    heractl.py devices
    heractl.py select 'DSP 3270 at 0701'
    heractl.py dsp type 0701 'LOGON IBMUSER\\n'
    heractl.py cpu command CPU stopall
    heractl.py tape mount 'TAPE 3480 at 0560' vol001.aws --readonly
    heractl.py preferences set room_background=#3355aa
    heractl.py shutdown

A DEVICE argument accepts, in order of preference: an exact device index
(0, 1, 2, ...), an exact label as shown by `heractl.py devices`
(e.g. "DSP 3270 at 0701"), a devnum (e.g. "0701"), or any unambiguous
substring of a label (e.g. "0701" or "printer").
"""

import argparse
import json
import os
import sys
from urllib.parse import urlsplit

try:
    import requests
except ImportError:
    sys.stderr.write(
        "heractl.py requires the 'requests' package (already a Hera dependency;"
        " run inside Hera's venv or `pip install requests`).\n"
    )
    sys.exit(1)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

_CPU_OPERATOR_COMMANDS = ("store", "restart", "startall", "stopall", "quit", "ext")


def _env_defaults():
    """HERA_API_URL, if set, seeds the host/port defaults (as common.sh uses it)."""
    url = os.environ.get("HERA_API_URL", "")
    if url:
        parts = urlsplit(url if "://" in url else f"//{url}")
        return parts.hostname or DEFAULT_HOST, parts.port or DEFAULT_PORT
    return DEFAULT_HOST, DEFAULT_PORT


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class Client:
    def __init__(self, host, port, token):
        self.base = f"http://{host}:{port}"
        self.token = token

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def get(self, path):
        return self._call("GET", path)

    def post(self, path, body=None):
        return self._call("POST", path, body if body is not None else {})

    def _call(self, method, path, body=None):
        try:
            if method == "GET":
                resp = requests.get(self.base + path, headers=self._headers(), timeout=10)
            else:
                resp = requests.post(
                    self.base + path, headers=self._headers(), json=body or {}, timeout=10
                )
        except requests.exceptions.ConnectionError:
            raise ApiError(
                0,
                f"Cannot reach Hera API at {self.base} — is Hera running with "
                "its scripting API enabled (Preferences > API)?",
            )
        except requests.exceptions.Timeout:
            raise ApiError(0, f"Timed out talking to Hera API at {self.base}{path}")

        try:
            payload = resp.json()
        except ValueError:
            payload = {"error": resp.text or resp.reason}

        if not resp.ok:
            raise ApiError(resp.status_code, payload.get("error", str(payload)))
        return payload


def resolve_device(client, token):
    """Resolve a DEVICE argument (index, label, devnum, or label substring)
    to its device index, the way every /devices/{index}/... route expects."""
    devices = client.get("/devices")

    stripped = token.strip()
    # A bare index is written without leading zeros (0, 1, 2, ...); a devnum
    # like "0009" or "0700" is 4 hex digits and must not be mistaken for one.
    if stripped.lstrip("-").isdigit() and str(int(stripped)) == stripped.lstrip("-") \
            and 0 <= int(stripped) < len(devices):
        return int(stripped)

    needle = stripped.lower()

    exact_label = [d for d in devices if d["label"].lower() == needle]
    if len(exact_label) == 1:
        return exact_label[0]["index"]

    by_devnum = [d for d in devices if d["devnum"] and d["devnum"].lower() == needle]
    if len(by_devnum) == 1:
        return by_devnum[0]["index"]

    partial = [d for d in devices if needle in d["label"].lower()]
    if len(partial) == 1:
        return partial[0]["index"]

    candidates = exact_label or by_devnum or partial
    if candidates:
        listing = "\n".join(f"  {d['index']}: {d['label']}" for d in candidates)
        raise ApiError(0, f"Ambiguous device {token!r}, matches:\n{listing}")
    raise ApiError(0, f"No device matches {token!r}. Run `heractl.py devices` to list them.")


def _dev_path(client, args, suffix):
    return f"/devices/{resolve_device(client, args.device)}/{suffix}"


def _coerce_scalar(text):
    if text.lower() in ("true", "false"):
        return text.lower() == "true"
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def _parse_kv_pairs(pairs):
    body = {}
    for pair in pairs:
        if "=" not in pair:
            raise ApiError(0, f"Expected KEY=VALUE, got {pair!r}")
        key, value = pair.split("=", 1)
        body[key] = _coerce_scalar(value)
    return body


def _bool_flag(value):
    return {"true": True, "false": False}[value]


# ── action implementations: (client, args) -> JSON-able result ─────────────

def act_status(client, args):
    return client.get("/status")


def act_devices(client, args):
    return client.get("/devices")


def act_capabilities(client, args):
    return client.get("/capabilities")


def act_select(client, args):
    return client.post(_dev_path(client, args, "select"))


def act_console_type(client, args):
    return client.post(_dev_path(client, args, "console/type"), {"command": args.command})


def act_console_log(client, args):
    return client.get(_dev_path(client, args, "console/log"))


def act_cpu_ipl_address(client, args):
    return client.post(_dev_path(client, args, "cpu/ipl_address"), {"address": args.address})


def act_cpu_ipl(client, args):
    body = {"address": args.address} if args.address is not None else {}
    return client.post(_dev_path(client, args, "cpu/ipl"), body)


def act_cpu_command(client, args):
    return client.post(_dev_path(client, args, "cpu/command"), {"command": args.command})


def act_cpu_state(client, args):
    return client.get(_dev_path(client, args, "cpu/state"))


def act_dsp_type(client, args):
    return client.post(_dev_path(client, args, "dsp3270/type_text"), {"text": args.text})


def act_dsp_aid(client, args):
    return client.post(_dev_path(client, args, "dsp3270/aid"), {"key": args.key})


def act_dsp_screen(client, args):
    return client.get(_dev_path(client, args, "dsp3270/screen"))


def act_dsp_setup(client, args):
    body = {"font_size": args.font_size}
    if args.model is not None:
        body["model"] = args.model
    return client.post(_dev_path(client, args, "dsp3270/setup"), body)


def act_dsp_connect(client, args):
    return client.post(_dev_path(client, args, "dsp3270/connect"))


def act_dsp_disconnect(client, args):
    return client.post(_dev_path(client, args, "dsp3270/disconnect"))


def act_printer_type(client, args):
    return client.post(_dev_path(client, args, "printer/type"), {"command": args.command})


def act_printer_output(client, args):
    return client.get(_dev_path(client, args, "printer/output"))


def act_printer_discard(client, args):
    return client.post(_dev_path(client, args, "printer/discard"))


def act_printer_save(client, args):
    body = {"path": args.path} if args.path else {}
    return client.post(_dev_path(client, args, "printer/save"), body)


def act_printer_paper_color(client, args):
    return client.post(_dev_path(client, args, "printer/paper_color"), {"color": args.color})


def act_printer_font_size(client, args):
    return client.post(_dev_path(client, args, "printer/font_size"), {"font_size": args.font_size})


def act_printer_print_command_output(client, args):
    return client.post(
        _dev_path(client, args, "printer/print_command_output"),
        {"enabled": _bool_flag(args.enabled)},
    )


def act_printer_test(client, args):
    return client.post(_dev_path(client, args, "printer/test"))


def act_printer_connect(client, args):
    return client.post(_dev_path(client, args, "printer/connect"))


def act_printer_disconnect(client, args):
    return client.post(_dev_path(client, args, "printer/disconnect"))


def act_reader_deck(client, args):
    return client.get(_dev_path(client, args, "reader/deck"))


def act_reader_load(client, args):
    lines = list(args.line or [])
    if args.file:
        with open(args.file, "r", encoding="latin-1") as fh:
            lines.extend(line.rstrip("\n") for line in fh)
    if not lines:
        raise ApiError(0, "reader load needs at least one --line or a --file")
    return client.post(_dev_path(client, args, "reader/load"), {"lines": lines})


def act_reader_new(client, args):
    return client.post(_dev_path(client, args, "reader/new"))


def act_reader_submit(client, args):
    return client.post(_dev_path(client, args, "reader/submit"))


def act_reader_setup(client, args):
    body = {}
    if args.color is not None:
        body["color"] = args.color
    if args.lang is not None:
        body["lang"] = args.lang
    if args.auto_number is not None:
        body["auto_number"] = _bool_flag(args.auto_number)
    return client.post(_dev_path(client, args, "reader/setup"), body)


def act_reader_toggle_view(client, args):
    return client.post(_dev_path(client, args, "reader/toggle_view"))


def act_reader_editor(client, args):
    return client.post(_dev_path(client, args, "reader/editor"), {"command": args.command})


def act_punch_deck(client, args):
    return client.get(_dev_path(client, args, "punch/deck"))


def act_punch_discard(client, args):
    return client.post(_dev_path(client, args, "punch/discard"))


def act_punch_save(client, args):
    return client.post(_dev_path(client, args, "punch/save"), {"path": args.path})


def act_punch_setup(client, args):
    body = {}
    if args.color is not None:
        body["color"] = args.color
    if args.lang is not None:
        body["lang"] = args.lang
    if args.auto_number is not None:
        body["auto_number"] = _bool_flag(args.auto_number)
    if args.skip_separator_cards is not None:
        body["skip_separator_cards"] = _bool_flag(args.skip_separator_cards)
    return client.post(_dev_path(client, args, "punch/setup"), body)


def act_punch_toggle_view(client, args):
    return client.post(_dev_path(client, args, "punch/toggle_view"))


def act_punch_connect(client, args):
    return client.post(_dev_path(client, args, "punch/connect"))


def act_punch_disconnect(client, args):
    return client.post(_dev_path(client, args, "punch/disconnect"))


def act_tape_files(client, args):
    return client.get(_dev_path(client, args, "tape/files"))


def act_tape_mount(client, args):
    return client.post(
        _dev_path(client, args, "tape/mount"),
        {"filename": args.filename, "readonly": args.readonly},
    )


def act_tape_unmount(client, args):
    return client.post(_dev_path(client, args, "tape/unmount"))


def act_tape_new(client, args):
    body = {"filename": args.filename, "volser": args.volser, "overwrite": args.overwrite}
    if args.owner is not None:
        body["owner"] = args.owner
    return client.post(_dev_path(client, args, "tape/new"), body)


def act_tape_status(client, args):
    return client.get(_dev_path(client, args, "tape/status"))


def act_preferences_get(client, args):
    return client.get("/preferences")


def act_preferences_set(client, args):
    body = _parse_kv_pairs(args.pair)
    return client.post("/preferences", body)


def act_shutdown(client, args):
    if not args.yes:
        raise ApiError(
            0,
            "This closes every device and quits Hera itself. Re-run with --yes to confirm.",
        )
    return client.post("/shutdown")


# ── argument parser ─────────────────────────────────────────────────────────

def build_parser():
    default_host, default_port = _env_defaults()

    parser = argparse.ArgumentParser(
        prog="heractl.py",
        description="Command-line client for Hera's scripting API.",
        add_help=False,
    )
    parser.add_argument("--help", action="help", help="Show this help message and exit")
    parser.add_argument(
        "-h", "--host", default=default_host,
        help=f"Hera API host (default: {default_host}, or $HERA_API_URL)",
    )
    parser.add_argument(
        "-p", "--port", type=int, default=default_port,
        help=f"Hera API port (default: {default_port}, or $HERA_API_URL)",
    )
    parser.add_argument(
        "-t", "--token", default=os.environ.get("HERA_API_TOKEN", ""),
        help="Bearer token, if one is set in Preferences > API (default: $HERA_API_TOKEN)",
    )
    parser.add_argument(
        "--raw", action="store_true", help="Print compact JSON instead of pretty-printed",
    )

    sub = parser.add_subparsers(dest="group", metavar="<command>")
    sub.required = True

    def leaf(parent_sub, name, func, help_text):
        p = parent_sub.add_parser(name, help=help_text, add_help=True)
        p.set_defaults(func=func)
        return p

    def with_device(p):
        p.add_argument("device", help="Device index, label, devnum, or unambiguous label substring")
        return p

    leaf(sub, "status", act_status, "Whether Hera sees Hercules as connected")
    leaf(sub, "devices", act_devices, "List every device currently shown in the room")
    leaf(sub, "capabilities", act_capabilities, "Describe every available API route")
    with_device(leaf(sub, "select", act_select, "Bring a device to the front"))

    p_console = sub.add_parser("console", help="CONSOLE device actions")
    console_sub = p_console.add_subparsers(dest="action", metavar="<action>")
    console_sub.required = True
    with_device(leaf(console_sub, "type", act_console_type, "Send a command to the console")) \
        .add_argument("command", help="Command text, as if typed and entered")
    with_device(leaf(console_sub, "log", act_console_log, "Read the current console log text"))

    p_cpu = sub.add_parser("cpu", help="CPU device actions")
    cpu_sub = p_cpu.add_subparsers(dest="action", metavar="<action>")
    cpu_sub.required = True
    with_device(leaf(cpu_sub, "ipl-address", act_cpu_ipl_address, "Set the IPL address dials")) \
        .add_argument("address", help="Hex address, e.g. 1D0 or 0x1D0")
    p = with_device(leaf(cpu_sub, "ipl", act_cpu_ipl, "IPL the CPU, optionally setting the address first"))
    p.add_argument("address", nargs="?", default=None, help="Hex address (optional)")
    with_device(leaf(cpu_sub, "command", act_cpu_command, "Press a CPU operator button")) \
        .add_argument("command", choices=_CPU_OPERATOR_COMMANDS)
    with_device(leaf(cpu_sub, "state", act_cpu_state, "Read CPU status and registers"))

    p_dsp = sub.add_parser("dsp", help="3270 terminal (DSP) device actions")
    dsp_sub = p_dsp.add_subparsers(dest="action", metavar="<action>")
    dsp_sub.required = True
    with_device(leaf(dsp_sub, "type", act_dsp_type, "Type text into the terminal")) \
        .add_argument("text", help=r"Text to type; end with \n to submit (Enter)")
    with_device(leaf(dsp_sub, "aid", act_dsp_aid, "Send a 3270 AID key or keyboard action")) \
        .add_argument("key", help="enter/pa1/pa2/pa3/clear, pf1..pf24, attn, reset, tab, ...")
    with_device(leaf(dsp_sub, "screen", act_dsp_screen, "Read the current screen text and cursor position"))
    p = with_device(leaf(dsp_sub, "setup", act_dsp_setup, "Change terminal font size and/or model"))
    p.add_argument("--font-size", type=int, required=True, help="Font size in px (10-32)")
    p.add_argument("--model", type=int, default=None, help="3270 model (2/3/4/5)")
    with_device(leaf(dsp_sub, "connect", act_dsp_connect, "Connect the terminal's socket"))
    with_device(leaf(dsp_sub, "disconnect", act_dsp_disconnect, "Disconnect the terminal's socket"))

    p_prt = sub.add_parser("printer", help="Printer (PRT) device actions")
    prt_sub = p_prt.add_subparsers(dest="action", metavar="<action>")
    prt_sub.required = True
    with_device(leaf(prt_sub, "type", act_printer_type,
                      "Send a command to a 3215 console printer (no-op for a 1403)")) \
        .add_argument("command")
    with_device(leaf(prt_sub, "output", act_printer_output, "Read the printer's buffered output"))
    with_device(leaf(prt_sub, "discard", act_printer_discard, "Discard the printer's buffered output"))
    p = with_device(leaf(prt_sub, "save", act_printer_save, "Save the buffered output as a PDF"))
    p.add_argument("--path", default=None, help="Output path (default: auto-named under spool/)")
    with_device(leaf(prt_sub, "paper-color", act_printer_paper_color, "Change the printer paper color")) \
        .add_argument("color")
    with_device(leaf(prt_sub, "font-size", act_printer_font_size, "Change the paper font size")) \
        .add_argument("font_size", type=int)
    with_device(leaf(prt_sub, "print-command-output", act_printer_print_command_output,
                      "Toggle echoing 3215 command output onto the console printer")) \
        .add_argument("enabled", choices=("true", "false"))
    with_device(leaf(prt_sub, "test", act_printer_test, "Trigger the printer's built-in test printout"))
    with_device(leaf(prt_sub, "connect", act_printer_connect, "Connect the printer's socket"))
    with_device(leaf(prt_sub, "disconnect", act_printer_disconnect, "Disconnect the printer's socket"))

    p_rdr = sub.add_parser("reader", help="Card reader (RDR) device actions")
    rdr_sub = p_rdr.add_subparsers(dest="action", metavar="<action>")
    rdr_sub.required = True
    with_device(leaf(rdr_sub, "deck", act_reader_deck, "Read the card reader deck content"))
    p = with_device(leaf(rdr_sub, "load", act_reader_load, "Load lines into the card reader deck"))
    p.add_argument("--line", action="append", help="One deck line; repeat for more")
    p.add_argument("--file", default=None, help="Load deck lines from a local file")
    with_device(leaf(rdr_sub, "new", act_reader_new, "Clear the card reader deck"))
    with_device(leaf(rdr_sub, "submit", act_reader_submit, "Submit the deck to Hercules"))
    p = with_device(leaf(rdr_sub, "setup", act_reader_setup, "Change color/language/auto-number settings"))
    p.add_argument("--color", default=None)
    p.add_argument("--lang", default=None)
    p.add_argument("--auto-number", choices=("true", "false"), default=None)
    with_device(leaf(rdr_sub, "toggle-view", act_reader_toggle_view, "Toggle editor/card deck view"))
    with_device(leaf(rdr_sub, "editor", act_reader_editor,
                      "Run one TSO-EDIT-style line command against the deck")) \
        .add_argument("command", help="e.g. TOP, DOWN 3, FIND 'JOB', CHANGE 'a' 'b', INSERT 'text', LIST +5")

    p_pch = sub.add_parser("punch", help="Card punch (PCH) device actions")
    pch_sub = p_pch.add_subparsers(dest="action", metavar="<action>")
    pch_sub.required = True
    with_device(leaf(pch_sub, "deck", act_punch_deck, "Read the card punch deck content"))
    with_device(leaf(pch_sub, "discard", act_punch_discard, "Discard the card punch deck"))
    with_device(leaf(pch_sub, "save", act_punch_save, "Save the card punch deck to a file")) \
        .add_argument("path")
    p = with_device(leaf(pch_sub, "setup", act_punch_setup,
                          "Change color/language/auto-number/separator settings"))
    p.add_argument("--color", default=None)
    p.add_argument("--lang", default=None)
    p.add_argument("--auto-number", choices=("true", "false"), default=None)
    p.add_argument("--skip-separator-cards", choices=("true", "false"), default=None)
    with_device(leaf(pch_sub, "toggle-view", act_punch_toggle_view, "Toggle editor/card deck view"))
    with_device(leaf(pch_sub, "connect", act_punch_connect, "Connect the card punch's socket"))
    with_device(leaf(pch_sub, "disconnect", act_punch_disconnect, "Disconnect the card punch's socket"))

    p_tape = sub.add_parser("tape", help="Tape drive (TAPE) device actions")
    tape_sub = p_tape.add_subparsers(dest="action", metavar="<action>")
    tape_sub.required = True
    with_device(leaf(tape_sub, "files", act_tape_files, "List tape files available to mount"))
    p = with_device(leaf(tape_sub, "mount", act_tape_mount, "Mount a tape file"))
    p.add_argument("filename")
    p.add_argument("--readonly", action="store_true")
    with_device(leaf(tape_sub, "unmount", act_tape_unmount, "Unmount the current tape"))
    p = with_device(leaf(tape_sub, "new", act_tape_new, "Create a new tape file and mount it"))
    p.add_argument("filename")
    p.add_argument("volser")
    p.add_argument("--owner", default=None)
    p.add_argument("--overwrite", action="store_true")
    with_device(leaf(tape_sub, "status", act_tape_status, "Read tape drive status"))

    p_prefs = sub.add_parser("preferences", help="Global Hera preferences")
    prefs_sub = p_prefs.add_subparsers(dest="action", metavar="<action>")
    prefs_sub.required = True
    leaf(prefs_sub, "get", act_preferences_get, "Read global preferences")
    p = leaf(prefs_sub, "set", act_preferences_set, "Change global preferences")
    p.add_argument("pair", nargs="+", help="KEY=VALUE, e.g. room_background=#3355aa")

    p = leaf(sub, "shutdown", act_shutdown,
             "Run each device's shutdown hook and quit Hera itself (requires --yes)")
    p.add_argument("--yes", action="store_true", help="Confirm this irreversible action")

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    client = Client(args.host, args.port, args.token)
    try:
        result = args.func(client, args)
    except ApiError as exc:
        sys.stderr.write(f"error: {exc.message}\n")
        return 1

    if args.raw:
        print(json.dumps(result))
    else:
        print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
