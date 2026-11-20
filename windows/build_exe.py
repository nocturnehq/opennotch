#!/usr/bin/env python3
"""Builds standalone dist/OpenNotch.exe on Windows using PyInstaller."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onefile",
        "--name", "OpenNotch",
        "--paths", str(ROOT),
        "--hidden-import", "winsdk.windows.media.control",
        "--hidden-import", "winsdk.windows.storage.streams",
        "--hidden-import", "pycaw.pycaw",
        "--hidden-import", "screen_brightness_control",
        str(ROOT / "opennotch_win" / "__main__.py"),
    ]
    print("Running:", " ".join(cmd))
    return subprocess.call(cmd, cwd=str(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
