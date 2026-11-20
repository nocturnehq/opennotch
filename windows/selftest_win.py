#!/usr/bin/env python3
"""Self-test for the Windows OpenNotch package (runs on both Linux and Windows)."""
from __future__ import annotations

import py_compile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from opennotch_win import config_win, media_smtc, system_win, win32_glass  # noqa: E402


def test_syntax():
    for py in sorted((ROOT / "opennotch_win").glob("*.py")):
        py_compile.compile(str(py), doraise=True)
    py_compile.compile(str(ROOT / "build_exe.py"), doraise=True)
    print("ok    windows syntax check")


def test_config():
    clean = config_win.sanitize({
        "shape": "notch",
        "progress": "wave",
        "visualizer": "dots",
        "music_volume": True,
        "top_gap": 999,
        "accent": "bad",
    })
    assert clean["shape"] == "notch"
    assert clean["progress"] == "wave"
    assert clean["visualizer"] == "dots"
    assert clean["music_volume"] is True
    assert clean["top_gap"] == 40
    assert clean["accent"] == "#ffffff"
    print("ok    windows config sanitizer")


def test_system_and_smtc():
    assert system_win.fmt_bps(512) == "512 B/s"
    assert system_win.fmt_bps(2048) == "2.0 KB/s"
    t = media_smtc.TrackInfo(title="Neon Harbor", artist="Kavi Rao", status="Playing", duration_s=213.0)
    assert t.title == "Neon Harbor"
    # Non-win32 graceful no-op check
    if sys.platform != "win32":
        assert win32_glass.apply_island_win32(0) is False
    print("ok    windows system & smtc models")


if __name__ == "__main__":
    test_syntax()
    test_config()
    test_system_and_smtc()
    print("all windows tests passed")
