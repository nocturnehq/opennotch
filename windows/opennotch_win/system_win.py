"""Native Windows audio (CoreAudio/pycaw), brightness, and system stats (psutil)."""
from __future__ import annotations

import sys
import time


def _audio_endpoint():
    if sys.platform != "win32":
        return None
    try:
        from ctypes import POINTER, cast
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        devices = AudioUtilities.GetSpeakers()
        iface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(iface, POINTER(IAudioEndpointVolume))
    except Exception:
        return None


def get_volume() -> tuple[int, bool]:
    ep = _audio_endpoint()
    if ep is None:
        return 50, False
    try:
        pct = int(round(ep.GetMasterVolumeLevelScalar() * 100))
        muted = bool(ep.GetMute())
        return max(0, min(100, pct)), muted
    except Exception:
        return 50, False


def set_volume(percent: int) -> bool:
    ep = _audio_endpoint()
    if ep is None:
        return False
    try:
        ep.SetMasterVolumeLevelScalar(max(0.0, min(1.0, percent / 100.0)), None)
        return True
    except Exception:
        return False


def toggle_mute() -> bool:
    ep = _audio_endpoint()
    if ep is None:
        return False
    try:
        ep.SetMute(0 if ep.GetMute() else 1, None)
        return True
    except Exception:
        return False


def get_brightness() -> int | None:
    if sys.platform != "win32":
        return None
    try:
        import screen_brightness_control as sbc
        vals = sbc.get_brightness()
        return int(vals[0]) if vals else None
    except Exception:
        return None


def set_brightness(percent: int) -> bool:
    if sys.platform != "win32":
        return False
    try:
        import screen_brightness_control as sbc
        sbc.set_brightness(max(1, min(100, int(percent))))
        return True
    except Exception:
        return False


class SysStats:
    def __init__(self):
        self._last_net = None
        self._last_t = time.monotonic()

    def sample(self) -> dict:
        out = {"cpu": 0.0, "ram": 0.0, "battery": None, "plugged": False, "down_bps": 0.0, "up_bps": 0.0}
        try:
            import psutil
            out["cpu"] = psutil.cpu_percent(interval=None)
            out["ram"] = psutil.virtual_memory().percent
            batt = psutil.sensors_battery()
            if batt is not None:
                out["battery"] = round(batt.percent)
                out["plugged"] = bool(batt.power_plugged)
            now = time.monotonic()
            net = psutil.net_io_counters()
            if self._last_net is not None and now > self._last_t:
                dt = now - self._last_t
                out["down_bps"] = max(0.0, (net.bytes_recv - self._last_net.bytes_recv) / dt)
                out["up_bps"] = max(0.0, (net.bytes_sent - self._last_net.bytes_sent) / dt)
            self._last_net = net
            self._last_t = now
        except Exception:
            pass
        return out


def fmt_bps(bps: float) -> str:
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if bps < 1024 or unit == "GB/s":
            return f"{bps:.0f} {unit}" if unit == "B/s" else f"{bps:.1f} {unit}"
        bps /= 1024.0
    return "0 B/s"
