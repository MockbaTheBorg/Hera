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
from pathlib import Path

VERSION_MAJOR = 1
VERSION_MINOR = 0

CONFIG_DIR = Path.home() / ".config" / "hera"
CONFIG_FILE = CONFIG_DIR / "hera.conf"

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
}


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
        self.bitmap_theme = app.get("bitmap_theme", self.bitmap_theme)
        raw_order = app.get("order", "")
        self.device_order = [s.upper() for s in (t.strip() for t in raw_order.split(",")) if s]

    def save(self):
        """Persist current settings to config file (preserves other sections like [devices])."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        parser = self._parser()

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
            "bitmap_theme": self.bitmap_theme,
            "order": ",".join(self.device_order),
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
