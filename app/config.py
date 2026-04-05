# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Hera configuration management.
Settings are loaded from ~/.config/hera/hera.conf (INI format).
Command-line arguments override config file values.
"""

import argparse
import configparser
import re
from pathlib import Path

VERSION_MAJOR = 1
VERSION_MINOR = 0

CONFIG_DIR = Path.home() / ".config" / "hera"
CONFIG_FILE = CONFIG_DIR / "hera.conf"
BITMAPS_DIR = Path(__file__).resolve().parent / "bitmaps"

DEFAULTS = {
    "host": "127.0.0.1",
    "port": "8081",
    "poll_interval": "0.25",
    "tapes_folder": "tapes",
    "window_x": "-1",
    "window_y": "-1",
    "window_width": "1024",
    "window_height": "768",
    "bitmap_theme": "blue",
    "room_background": "#9da89b",
}

_HEX_COLOR_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")


def available_bitmap_themes() -> list[str]:
    """Return bitmap theme directories that contain a full device set."""
    if BITMAPS_DIR.exists():
        themes = sorted(
            child.name
            for child in BITMAPS_DIR.iterdir()
            if child.is_dir() and (child / "unknown.png").exists()
        )
        if themes:
            return themes
    return [DEFAULTS["bitmap_theme"]]


def normalize_bitmap_theme(theme: str) -> str:
    """Return a valid bitmap theme name, falling back to the configured default."""
    candidate = theme.strip().lower()
    themes = available_bitmap_themes()
    if candidate in themes:
        return candidate
    default_theme = DEFAULTS["bitmap_theme"]
    return default_theme if default_theme in themes else themes[0]


def parse_device_order(raw_order: str) -> list[str]:
    """Parse a comma-separated device order into normalized devclass names."""
    return [token.upper() for token in (item.strip() for item in raw_order.split(",")) if token]


def format_device_order(device_order: list[str]) -> str:
    """Format normalized device classes for config persistence."""
    return ",".join(item.upper() for item in device_order if item.strip())


def is_valid_room_background(color: str) -> bool:
    """Return True if the room background is a valid 6-digit hex color."""
    return bool(_HEX_COLOR_RE.match(color.strip()))


def normalize_room_background(color: str) -> str:
    """Return a normalized #rrggbb color string for the room background."""
    candidate = color.strip()
    if not candidate:
        return DEFAULTS["room_background"]
    if not is_valid_room_background(candidate):
        return DEFAULTS["room_background"]
    if not candidate.startswith("#"):
        candidate = f"#{candidate}"
    return candidate.lower()


class Config:
    def __init__(self):
        self.host: str = DEFAULTS["host"]
        self.port: int = int(DEFAULTS["port"])
        self.poll_interval: float = float(DEFAULTS["poll_interval"])
        self.tapes_folder: str = DEFAULTS["tapes_folder"]
        self.window_x: int = int(DEFAULTS["window_x"])
        self.window_y: int = int(DEFAULTS["window_y"])
        self.window_width: int = int(DEFAULTS["window_width"])
        self.window_height: int = int(DEFAULTS["window_height"])
        self.bitmap_theme: str = DEFAULTS["bitmap_theme"]
        self.room_background: str = DEFAULTS["room_background"]
        self.device_order: list[str] = []  # e.g. ["CPU","CONSOLE","DSP","PRT"]

    @property
    def api_base_url(self) -> str:
        return f"http://{self.host}:{self.port}/cgi-bin/api/v1"

    @staticmethod
    def _parser() -> configparser.ConfigParser:
        parser = configparser.ConfigParser()
        parser.read(CONFIG_FILE)
        return parser

    @staticmethod
    def _int_value(section, key: str, default: int) -> int:
        return int(section.get(key, default))

    @staticmethod
    def _float_value(section, key: str, default: float) -> float:
        return float(section.get(key, default))

    def load(self):
        """Load settings from config file. Missing file uses defaults."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if not CONFIG_FILE.exists():
            return

        parser = self._parser()

        conn = parser["connection"] if "connection" in parser else {}
        self.host = conn.get("host", self.host)
        self.port = self._int_value(conn, "port", self.port)
        self.poll_interval = self._float_value(conn, "poll_interval", self.poll_interval)
        self.tapes_folder = conn.get("tapes_folder", self.tapes_folder)

        win = parser["window"] if "window" in parser else {}
        self.window_x = self._int_value(win, "x", self.window_x)
        self.window_y = self._int_value(win, "y", self.window_y)
        self.window_width = self._int_value(win, "width", self.window_width)
        self.window_height = self._int_value(win, "height", self.window_height)

        app = parser["appearance"] if "appearance" in parser else {}
        self.bitmap_theme = normalize_bitmap_theme(app.get("bitmap_theme", self.bitmap_theme))
        self.room_background = normalize_room_background(
            app.get("room_background", self.room_background)
        )
        raw_order = app.get("order", "")
        self.device_order = parse_device_order(raw_order)

    def save(self, include_connection: bool = True):
        """Persist current settings to config file.

        When include_connection is False, the existing [connection] section is left
        untouched so runtime-only CLI overrides do not become the next launch's
        persisted endpoint.
        """
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        parser = self._parser()

        if include_connection:
            parser["connection"] = {
                "host": self.host,
                "port": str(self.port),
                "poll_interval": str(self.poll_interval),
                "tapes_folder": self.tapes_folder,
            }
        parser["window"] = {
            "x": str(self.window_x),
            "y": str(self.window_y),
            "width": str(self.window_width),
            "height": str(self.window_height),
        }
        parser["appearance"] = {
            "bitmap_theme": normalize_bitmap_theme(self.bitmap_theme),
            "room_background": normalize_room_background(self.room_background),
            "order": format_device_order(self.device_order),
        }

        with open(CONFIG_FILE, "w") as f:
            parser.write(f)

    def get_setting(self, section: str, key: str, default: str = "") -> str:
        """Read an arbitrary setting from the config file."""
        parser = self._parser()
        return parser[section].get(key, default) if section in parser else default

    def set_setting(self, section: str, key: str, value: str) -> None:
        """Write an arbitrary setting to the config file."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        parser = self._parser()
        if section not in parser:
            parser[section] = {}
        parser[section][key] = value
        with open(CONFIG_FILE, "w") as f:
            parser.write(f)

    def apply_args(self, args: argparse.Namespace):
        """Override settings from parsed command-line arguments."""
        if getattr(args, "host", None):
            self.host = args.host
        if getattr(args, "port", None):
            self.port = args.port


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"Hera v{VERSION_MAJOR}.{VERSION_MINOR} — Hercules GUI"
    )
    parser.add_argument("--host", help="Hercules HTTP server host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, help="Hercules HTTP server port (default: 8081)")
    return parser.parse_args()
