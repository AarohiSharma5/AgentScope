"""Cross-platform colored console output and interactive prompts.

Colors are emitted only when the stream is a TTY, ``NO_COLOR`` is unset and the
user hasn't opted out. On Windows the ANSI/VT terminal mode is enabled so the
same escape codes work in modern terminals and PowerShell. Everything degrades
gracefully to plain text.
"""
from __future__ import annotations

import getpass
import json
import os
import sys
from typing import List, Optional, Sequence

_CODES = {
    "reset": "0",
    "bold": "1",
    "dim": "2",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
    "gray": "90",
}


def _enable_windows_vt() -> None:
    """Best-effort enable of ANSI escape processing on Windows terminals."""
    if os.name != "nt":  # pragma: no cover - non-Windows
        return
    try:  # pragma: no cover - platform specific
        import ctypes

        kernel32 = ctypes.windll.kernel32
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004 on STD_OUTPUT_HANDLE (-11)
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass


class Console:
    """A small, dependency-free colored console."""

    def __init__(self, color: Optional[bool] = None, stream=None):
        self.stream = stream or sys.stdout
        if color is None:
            color = (
                self.stream.isatty()
                and os.environ.get("NO_COLOR") is None
                and os.environ.get("TERM") != "dumb"
            )
        if color:
            _enable_windows_vt()
        self.color = bool(color)

    # -- styling ------------------------------------------------------------

    def style(self, text: str, *styles: str) -> str:
        if not self.color or not styles:
            return text
        codes = ";".join(_CODES[s] for s in styles if s in _CODES)
        if not codes:
            return text
        return f"\033[{codes}m{text}\033[0m"

    def write(self, text: str = "") -> None:
        self.stream.write(text + "\n")

    # -- semantic helpers ---------------------------------------------------

    def heading(self, text: str) -> None:
        self.write(self.style(text, "bold", "cyan"))

    def success(self, text: str) -> None:
        self.write(f"{self.style('✓', 'green')} {text}")

    def error(self, text: str) -> None:
        # Errors go to stderr so piping stdout stays clean.
        sys.stderr.write(f"{self.style('✗', 'red')} {text}\n")

    def warn(self, text: str) -> None:
        self.write(f"{self.style('!', 'yellow')} {text}")

    def info(self, text: str) -> None:
        self.write(f"{self.style('•', 'blue')} {text}")

    def dim(self, text: str) -> None:
        self.write(self.style(text, "dim"))

    def kv(self, key: str, value, width: int = 16) -> None:
        label = self.style(f"{key:<{width}}", "gray")
        self.write(f"{label} {value}")

    def json(self, obj) -> None:
        text = json.dumps(obj, indent=2, default=str)
        self.write(text)

    def table(self, headers: Sequence[str], rows: Sequence[Sequence]) -> None:
        """Render a simple, aligned text table."""
        cols = len(headers)
        cells = [[_cell(c) for c in row] for row in rows]
        widths = [len(str(h)) for h in headers]
        for row in cells:
            for i in range(cols):
                widths[i] = max(widths[i], len(row[i]) if i < len(row) else 0)

        header_line = "  ".join(
            self.style(str(h).ljust(widths[i]), "bold") for i, h in enumerate(headers)
        )
        self.write(header_line)
        self.write(self.style("  ".join("-" * w for w in widths), "gray"))
        for row in cells:
            self.write("  ".join(str(row[i] if i < len(row) else "").ljust(widths[i]) for i in range(cols)))

    # -- prompts ------------------------------------------------------------

    def ask(self, prompt: str, default: Optional[str] = None) -> str:
        suffix = f" [{default}]" if default not in (None, "") else ""
        raw = input(f"{self.style('?', 'cyan')} {prompt}{suffix}: ").strip()
        return raw or (default or "")

    def ask_secret(self, prompt: str, default: Optional[str] = None) -> str:
        hint = " [keep current]" if default else ""
        raw = getpass.getpass(f"? {prompt}{hint}: ").strip()
        return raw or (default or "")

    def confirm(self, prompt: str, default: bool = True) -> bool:
        options = "Y/n" if default else "y/N"
        raw = input(f"{self.style('?', 'cyan')} {prompt} [{options}]: ").strip().lower()
        if not raw:
            return default
        return raw in {"y", "yes"}

    def choose(self, prompt: str, options: List[str], default: Optional[str] = None) -> str:
        self.write(self.style(prompt, "bold"))
        for i, opt in enumerate(options, 1):
            self.write(f"  {i}) {opt}")
        raw = self.ask("Select", default=default)
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        return raw


def _cell(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)
