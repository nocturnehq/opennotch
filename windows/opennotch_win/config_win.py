"""Configuration loader/saver and Windows startup registry helper."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

DEFAULTS = {
    "shape": "island",            # island | notch
    "top_gap": 8,
    "progress": "comet",          # pill | comet | wave
    "visualizer": "bars",         # bars | pixels | dots
    "music_background": "album",  # album | black
    "music_volume": False,
    "music_art_badge": True,
    "accent": "#ffffff",
    "focus_minutes": 25,
    "autostart": False,
    "hover_delay_ms": 180,
}

CHOICES = {
    "shape": ("island", "notch"),
    "progress": ("pill", "comet", "wave"),
    "visualizer": ("bars", "pixels", "dots"),
    "music_background": ("album", "black"),
}


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    p = Path(base) / "OpenNotch"
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_path() -> Path:
    return config_dir() / "config.json"


def sanitize(raw: dict | None) -> dict:
    cfg = dict(DEFAULTS)
    if not isinstance(raw, dict):
        return cfg
    for k, allowed in CHOICES.items():
        if raw.get(k) in allowed:
            cfg[k] = raw[k]
    for k in ("music_volume", "music_art_badge", "autostart"):
        if isinstance(raw.get(k), bool):
            cfg[k] = raw[k]
    for k, lo, hi in (("top_gap", 0, 40), ("focus_minutes", 5, 180), ("hover_delay_ms", 0, 1000)):
        if isinstance(raw.get(k), (int, float)):
            cfg[k] = max(lo, min(hi, int(raw[k])))
    acc = raw.get("accent")
    if isinstance(acc, str) and len(acc) == 7 and acc.startswith("#"):
        cfg["accent"] = acc
    return cfg


def load() -> dict:
    p = config_path()
    try:
        return sanitize(json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        return dict(DEFAULTS)


def save(cfg: dict) -> dict:
    clean = sanitize(cfg)
    config_path().write_text(json.dumps(clean, indent=2), encoding="utf-8")
    return clean


def set_windows_autostart(enabled: bool) -> bool:
    """Register or remove OpenNotch in HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        exe = sys.executable
        cmd = f'"{exe}"' if getattr(sys, "frozen", False) else f'"{exe}" -m opennotch_win'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, "OpenNotch", 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, "OpenNotch")
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        return False
