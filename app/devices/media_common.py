# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Shared helpers for mounted-media devices.
"""

import os

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget

from ..theme import (
    WORKSPACE_BG,
    WORKSPACE_BORDER,
    WORKSPACE_FG,
    WORKSPACE_FONT_FAMILY,
    WORKSPACE_FONT_SIZE,
)


def run_command_output(client, cmd: str) -> list:
    """Run one Hercules command and return the response lines."""
    return client.syslog_feed.send_command(cmd)


def label_from_path(path: str) -> str:
    """Return the filename without extension, uppercased, truncated to 6 chars."""
    return os.path.splitext(os.path.basename(path))[0].upper()[:6]


def create_command_output_workspace(parent: QWidget) -> tuple[QWidget, QPlainTextEdit]:
    """Create the standard read-only text workspace used by media devices."""
    widget = QWidget(parent)
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(4, 4, 4, 4)

    output = QPlainTextEdit(widget)
    output.setReadOnly(True)
    output.setStyleSheet(_workspace_stylesheet())
    font = QFont(WORKSPACE_FONT_FAMILY)
    font.setStyleHint(QFont.TypeWriter)
    font.setPointSize(WORKSPACE_FONT_SIZE)
    output.setFont(font)
    output.setPlainText("Select device to load information.")
    layout.addWidget(output)

    return widget, output


def render_command_output(client, commands: list[str], *, devnum: str) -> list[str]:
    """Run workspace commands and return the combined output lines."""
    lines: list[str] = []
    for cmd_template in commands:
        cmd = cmd_template.format(devnum=devnum)
        extracted = run_command_output(client, cmd)
        if extracted:
            lines.extend(extracted)
        else:
            lines.append(f"({cmd}: no output)")
    return lines


def _workspace_stylesheet() -> str:
    return (
        f"QPlainTextEdit {{ background-color: {WORKSPACE_BG}; color: {WORKSPACE_FG}; "
        f"border: {WORKSPACE_BORDER}; }}"
    )


def render_workspace_commands(output: QPlainTextEdit, client, commands: list[str], *, devnum: str) -> None:
    """Run workspace commands and render the resulting output to the text area."""
    output.setPlainText("\n".join(render_command_output(client, commands, devnum=devnum)))
