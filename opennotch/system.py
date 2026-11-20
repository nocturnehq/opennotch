"""Small readers for /proc, /sys and pactl. No GTK here."""
import glob
import os
import re
import subprocess
import time

_ENV = dict(os.environ, LC_ALL="C")


def pactl(*args, timeout=2):
    try:
        r = subprocess.run(["pactl", *args], capture_output=True, text=True, env=_ENV, timeout=timeout)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


# ---- CPU / RAM / GPU / battery -------------------------------------------------

class CpuMeter:
    def __init__(self):
        self.prev = self._read()

    @staticmethod
    def _read():
        with open("/proc/stat") as f:
            vals = [int(x) for x in f.readline().split()[1:9]]
        idle = vals[3] + vals[4]
        return sum(vals) - idle, sum(vals)

    def percent(self):
        busy, total = self._read()
        pb, pt = self.prev
        self.prev = (busy, total)
        return 100.0 * (busy - pb) / (total - pt) if total > pt else 0.0


def ram_percent():
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, v = line.split(":", 1)
            info[k] = int(v.split()[0])
    total = info.get("MemTotal", 1)
    return 100.0 * (total - info.get("MemAvailable", total)) / total


def gpu_percent():
    for p in sorted(glob.glob("/sys/class/drm/card*/device/gpu_busy_percent")):
        try:
            with open(p) as f:
                return float(f.read().strip())
        except (OSError, ValueError):
            continue
    return None


def battery():
    """Returns (percent, charging) or None when there is no battery."""
    for d in sorted(glob.glob("/sys/class/power_supply/BAT*")):
        try:
            with open(os.path.join(d, "capacity")) as f:
                cap = int(f.read().strip())
            with open(os.path.join(d, "status")) as f:
                status = f.read().strip()
            return cap, status in ("Charging", "Full")
        except (OSError, ValueError):
            continue
    return None


def _read_int(path):
    try:
        with open(path) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def format_duration_hm(hours):
    """Format positive hours as '2h 15m' or '42m'."""
    mins = max(1, round(hours * 60))
    h, m = divmod(mins, 60)
    return f"{h}h {m}m" if h else f"{m}m"


def battery_estimate():
    """Return a short remaining / to-full time string, or None when unavailable."""
    for d in sorted(glob.glob("/sys/class/power_supply/BAT*")):
        try:
            with open(os.path.join(d, "status")) as f:
                status = f.read().strip()
        except OSError:
            continue
        if status not in ("Discharging", "Charging"):
            return None
        now = _read_int(os.path.join(d, "energy_now")) or _read_int(os.path.join(d, "charge_now"))
        full = _read_int(os.path.join(d, "energy_full")) or _read_int(os.path.join(d, "charge_full"))
        rate = _read_int(os.path.join(d, "power_now")) or _read_int(os.path.join(d, "current_now"))
        if not now or not rate or rate <= 0:
            continue
        if status == "Discharging":
            hours = now / rate
            return f"{format_duration_hm(hours)} left" if 0.02 < hours < 48 else None
        if full and full > now:
            hours = (full - now) / rate
            return f"{format_duration_hm(hours)} to full" if 0.02 < hours < 24 else None
    return None


def cycle_audio_output():
    """Switch to the next PulseAudio/PipeWire output sink and return its friendly name, or None."""
    out = pactl("list", "sinks")
    if not out:
        return None
    sinks = []
    cur_name, cur_desc = None, None
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("Name:"):
            if cur_name:
                sinks.append((cur_name, cur_desc or cur_name))
            cur_name = s.split(":", 1)[1].strip()
            cur_desc = None
        elif s.startswith("Description:") and cur_name:
            cur_desc = s.split(":", 1)[1].strip()
    if cur_name:
        sinks.append((cur_name, cur_desc or cur_name))
    if len(sinks) < 2:
        return sinks[0][1] if sinks else None
    current = (pactl("get-default-sink") or "").strip()
    idx = next((i for i, (n, _d) in enumerate(sinks) if n == current), -1)
    nxt_name, nxt_desc = sinks[(idx + 1) % len(sinks)]
    pactl("set-default-sink", nxt_name)
    for line in (pactl("list", "short", "sink-inputs") or "").splitlines():
        parts = line.split()
        if parts and parts[0].isdigit():
            pactl("move-sink-input", parts[0], nxt_name)
    return nxt_desc


def battery_alert_state():
    """Return (percent, plugged in) using mains state when the kernel exposes it."""
    status = battery()
    if status is None:
        return None
    percent, charging = status
    adapters = []
    for path in glob.glob("/sys/class/power_supply/*"):
        try:
            with open(os.path.join(path, "type")) as f:
                if f.read().strip() not in ("Mains", "USB", "USB_C", "USB_PD"):
                    continue
            with open(os.path.join(path, "online")) as f:
                adapters.append(f.read().strip() == "1")
        except OSError:
            continue
    return percent, any(adapters) if adapters else charging


# ---- brightness ----------------------------------------------------------------

def backlight_dir():
    dirs = sorted(glob.glob("/sys/class/backlight/*"))
    return dirs[0] if dirs else None


def brightness():
    """Returns (percent, writable) or None if the machine has no backlight."""
    d = backlight_dir()
    if not d:
        return None
    try:
        with open(os.path.join(d, "brightness")) as f:
            cur = int(f.read())
        with open(os.path.join(d, "max_brightness")) as f:
            mx = int(f.read()) or 1
    except (OSError, ValueError):
        return None
    return 100.0 * cur / mx, os.access(os.path.join(d, "brightness"), os.W_OK)


def set_brightness(percent):
    d = backlight_dir()
    if not d:
        return False
    try:
        with open(os.path.join(d, "max_brightness")) as f:
            mx = int(f.read())
        value = max(1, round(mx * min(100, max(1, percent)) / 100))  # never 0: a black screen is hard to undo
        with open(os.path.join(d, "brightness"), "w") as f:
            f.write(str(value))
        return True
    except (OSError, ValueError):
        return False


# ---- audio (pactl) -------------------------------------------------------------

def sink_volume():
    m = re.search(r"(\d+)%", pactl("get-sink-volume", "@DEFAULT_SINK@"))
    return int(m.group(1)) if m else None


def sink_muted():
    return "yes" in pactl("get-sink-mute", "@DEFAULT_SINK@")


def mic_muted():
    return "yes" in pactl("get-source-mute", "@DEFAULT_SOURCE@")


def parse_source_outputs(text, monitor_indexes):
    """App names that are really recording from a microphone (not monitors, not level meters, not corked)."""
    apps = []
    for block in re.split(r"^Source Output #", text, flags=re.M)[1:]:
        src = re.search(r"^\s*Source: (\d+)", block, re.M)
        if not src or src.group(1) in monitor_indexes:
            continue
        if re.search(r"^\s*Corked: yes", block, re.M):
            continue
        media = re.search(r'media\.name = "(.*)"', block)
        if media and "peak detect" in media.group(1).lower():
            continue
        app = re.search(r'application\.name = "(.*)"', block)
        apps.append(app.group(1) if app else "app")
    return apps


def recording_apps():
    monitors = {line.split("\t")[0] for line in pactl("list", "short", "sources").splitlines()
                if "\t" in line and line.split("\t")[1].endswith(".monitor")}
    return parse_source_outputs(pactl("list", "source-outputs"), monitors)


# ---- network ---------------------------------------------------------------------

class NetMeter:
    """Bytes per second in/out over all non-loopback interfaces, since the previous call."""

    def __init__(self):
        self.prev = (self._read(), time.monotonic())

    @staticmethod
    def _read():
        rx = tx = 0
        try:
            with open("/proc/net/dev") as f:
                for line in f.readlines()[2:]:
                    name, data = line.split(":", 1)
                    if name.strip() == "lo":
                        continue
                    v = data.split()
                    rx, tx = rx + int(v[0]), tx + int(v[8])
        except (OSError, ValueError, IndexError):
            pass
        return rx, tx

    def rates(self):
        (prx, ptx), pt = self.prev
        (rx, tx), t = self._read(), time.monotonic()
        self.prev = ((rx, tx), t)
        dt = max(1e-3, t - pt)
        return max(0, rx - prx) / dt, max(0, tx - ptx) / dt


def human_rate(bps, bits=False):
    if bits:
        bps = bps * 8
        for unit in ("b/s", "kb/s", "Mb/s"):
            if bps < 1000 or unit == "Mb/s":
                return f"{bps:.0f} {unit}" if unit == "b/s" else f"{bps:.1f} {unit}"
            bps /= 1000
    for unit in ("B/s", "KB/s", "MB/s"):
        if bps < 1000 or unit == "MB/s":
            return f"{bps:.0f} {unit}" if unit == "B/s" else f"{bps:.1f} {unit}"
        bps /= 1000


def format_clock(fmt="system", lt=None):
    """Format local time according to 'system' | '24h' | '12h'."""
    lt = lt or time.localtime()
    if fmt == "12h":
        return time.strftime("%-I:%M %p", lt)
    return time.strftime("%H:%M", lt)
