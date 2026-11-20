"""Network and desktop helpers: weather, lyrics, quick toggles, brightness, Ask Claude. No GTK widgets here.

Network calls (weather, lyrics) run in threads and hand results back with GLib.idle_add.
"""
import json
import os
import re
import shutil
import subprocess
import threading
import urllib.parse
import urllib.request

from gi.repository import Gio, GLib

UA = {"User-Agent": "OpenNotch (https://github.com/ - local desktop notch)"}


def _get_json(url, timeout=8):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read(2_000_000).decode("utf-8"))


def in_thread(fn, callback, *args):
    """Run fn(*args) in a thread; callback(result_or_None) on the GTK main loop."""
    def run():
        try:
            res = fn(*args)
        except Exception as e:  # any network/parse failure just means "no data"
            print("opennotch:", fn.__name__, "failed:", e)
            res = None
        GLib.idle_add(lambda: callback(res) and False)
    threading.Thread(target=run, daemon=True).start()


# ---- weather (Open-Meteo: free, no key, no account) ----------------------------

WEATHER_CODES = {  # WMO code -> (text, symbolic icon)
    0: ("Clear", "weather-clear-symbolic"), 1: ("Mostly clear", "weather-few-clouds-symbolic"),
    2: ("Partly cloudy", "weather-few-clouds-symbolic"), 3: ("Cloudy", "weather-overcast-symbolic"),
    45: ("Fog", "weather-fog-symbolic"), 48: ("Fog", "weather-fog-symbolic"),
    51: ("Drizzle", "weather-showers-scattered-symbolic"), 53: ("Drizzle", "weather-showers-scattered-symbolic"),
    55: ("Drizzle", "weather-showers-scattered-symbolic"), 61: ("Rain", "weather-showers-symbolic"),
    63: ("Rain", "weather-showers-symbolic"), 65: ("Heavy rain", "weather-showers-symbolic"),
    71: ("Snow", "weather-snow-symbolic"), 73: ("Snow", "weather-snow-symbolic"), 75: ("Snow", "weather-snow-symbolic"),
    80: ("Showers", "weather-showers-scattered-symbolic"), 81: ("Showers", "weather-showers-symbolic"),
    82: ("Storms", "weather-storm-symbolic"), 95: ("Thunderstorm", "weather-storm-symbolic"),
    96: ("Thunderstorm", "weather-storm-symbolic"), 99: ("Thunderstorm", "weather-storm-symbolic"),
}


def fetch_weather(city, fahrenheit=False):
    """city -> {"temp", "high", "low", "text", "icon", "place"}; only the city name leaves this PC."""
    geo = _get_json("https://geocoding-api.open-meteo.com/v1/search?count=1&name=" + urllib.parse.quote(city))
    hit = (geo.get("results") or [None])[0]
    if not hit:
        return None
    q = urllib.parse.urlencode({"latitude": hit["latitude"], "longitude": hit["longitude"],
                                "current": "temperature_2m,weather_code", "timezone": "auto",
                                "daily": "temperature_2m_max,temperature_2m_min", "forecast_days": 1,
                                "temperature_unit": "fahrenheit" if fahrenheit else "celsius"})
    w = _get_json("https://api.open-meteo.com/v1/forecast?" + q)
    code = int(w["current"]["weather_code"])
    text, icon = WEATHER_CODES.get(code, ("", "weather-few-clouds-symbolic"))
    return {"temp": round(w["current"]["temperature_2m"]), "high": round(w["daily"]["temperature_2m_max"][0]),
            "low": round(w["daily"]["temperature_2m_min"][0]), "text": text, "icon": icon, "place": hit["name"]}


# ---- synced lyrics (LRCLIB: free community library) ----------------------------

_LRC = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")


def parse_lrc(text):
    """'[01:02.50] line' -> sorted [(62.5, 'line')]; lines with several stamps appear once per stamp."""
    out = []
    for raw in (text or "").splitlines():
        stamps = _LRC.findall(raw)
        words = _LRC.sub("", raw).strip()
        for m, s in stamps:
            out.append((int(m) * 60 + float(s), words))
    return sorted(out)


def line_at(lines, seconds):
    """Index of the line being sung at `seconds`, or -1 before the first line."""
    idx = -1
    for i, (t, _) in enumerate(lines):
        if t <= seconds:
            idx = i
        else:
            break
    return idx


def fetch_lyrics(title, artist, album, length_s):
    q = {"track_name": title, "artist_name": artist}
    if album:
        q["album_name"] = album
    if length_s:
        q["duration"] = int(length_s)
    try:
        data = _get_json("https://lrclib.net/api/get?" + urllib.parse.urlencode(q))
    except urllib.error.HTTPError:
        hits = _get_json("https://lrclib.net/api/search?" + urllib.parse.urlencode(
            {"track_name": title, "artist_name": artist}))
        data = next((h for h in hits if h.get("syncedLyrics")), None)
    return parse_lrc(data.get("syncedLyrics")) if data else []


# ---- brightness through Cinnamon's settings daemon (no root needed) ------------

_POWER = ("org.cinnamon.SettingsDaemon.Power", "/org/cinnamon/SettingsDaemon/Power",
          "org.cinnamon.SettingsDaemon.Power.Screen")


def _power_call(method, args=None):
    bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    return bus.call_sync(_POWER[0], _POWER[1], _POWER[2], method, args, None, 0, 1500, None).unpack()


KDE = "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "")
_KPOWER = ("org.kde.Solid.PowerManagement", "/org/kde/Solid/PowerManagement/Actions/BrightnessControl",
           "org.kde.Solid.PowerManagement.Actions.BrightnessControl")


def _kpower_call(method, args=None):
    bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    return bus.call_sync(_KPOWER[0], _KPOWER[1], _KPOWER[2], method, args, None, 0, 1500, None).unpack()


def get_brightness():
    try:
        if KDE:  # Plasma: PowerDevil, in its own 0..max steps
            cur, mx = _kpower_call("brightness")[0], _kpower_call("brightnessMax")[0] or 1
            return round(100 * cur / mx)
        return int(_power_call("GetPercentage")[0])
    except GLib.Error:
        return None


def set_brightness(percent):
    percent = int(max(1, min(100, percent)))  # never 0: a black screen is hard to undo
    try:
        if KDE:  # Silent: the notch shows the change, not Plasma's own pop-up
            mx = _kpower_call("brightnessMax")[0] or 1
            _kpower_call("setBrightnessSilent", GLib.Variant("(i)", (max(1, round(mx * percent / 100)),)))
        else:
            _power_call("SetPercentage", GLib.Variant("(u)", (percent,)))
        return True
    except GLib.Error:
        return False


# ---- quick toggles ---------------------------------------------------------------

def _run(*argv, timeout=3):
    try:
        r = subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def wifi_on():
    return _run("nmcli", "radio", "wifi") == "enabled"


def wifi_name():
    out = _run("nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi") or ""
    return next((line.split(":", 1)[1] for line in out.splitlines() if line.startswith("yes:")), "")


def set_wifi(on):
    _run("nmcli", "radio", "wifi", "on" if on else "off")


def bluetooth_on():
    return "Powered: yes" in (_run("bluetoothctl", "show") or "")


def set_bluetooth(on):
    _run("bluetoothctl", "power", "on" if on else "off", timeout=5)


def _gs(schema, key):
    s = Gio.Settings.new(schema)
    return s, key


def night_light_on():
    if KDE:  # Plasma: KWin's Night Color
        return (_run("kreadconfig5", "--file", "kwinrc", "--group", "NightColor", "--key", "Active") or "") == "true"
    s, k = _gs("org.cinnamon.settings-daemon.plugins.color", "night-light-enabled")
    return s.get_boolean(k)


def set_night_light(on):
    if KDE:
        _run("kwriteconfig5", "--file", "kwinrc", "--group", "NightColor", "--key", "Active", "true" if on else "false")
        _run("qdbus", "org.kde.KWin", "/KWin", "reconfigure")
        return
    s, k = _gs("org.cinnamon.settings-daemon.plugins.color", "night-light-enabled")
    s.set_boolean(k, on)


_dnd_cookie = None  # Plasma: Do Not Disturb lasts while we hold an inhibition


def _notif_call(method, args, reply="(u)"):
    bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    return bus.call_sync("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                         "org.freedesktop.Notifications", method, args, GLib.VariantType(reply) if reply else None,
                         0, 1500, None)


def dnd_on():
    if KDE:
        return _dnd_cookie is not None
    s, k = _gs("org.cinnamon.desktop.notifications", "display-notifications")
    return not s.get_boolean(k)


def set_dnd(on):
    global _dnd_cookie
    if KDE:
        try:
            if on and _dnd_cookie is None:
                _dnd_cookie = _notif_call("Inhibit", GLib.Variant("(ssa{sv})", ("opennotch", "Focus", {}))).unpack()[0]
            elif not on and _dnd_cookie is not None:
                _notif_call("UnInhibit", GLib.Variant("(u)", (_dnd_cookie,)), reply=None)
                _dnd_cookie = None
        except GLib.Error as e:
            print("opennotch: focus mode unavailable:", e.message)
        return
    s, k = _gs("org.cinnamon.desktop.notifications", "display-notifications")
    s.set_boolean(k, not on)


def power_profile():
    return _run("powerprofilesctl", "get") or ""


def set_power_profile(name):
    _run("powerprofilesctl", "set", name)


# ---- Ask Claude (the Claude Code CLI the user already has signed in) -----------

def claude_path():
    return shutil.which("claude") or next(
        (p for p in (GLib.get_home_dir() + "/.local/bin/claude",) if GLib.file_test(p, GLib.FileTest.IS_EXECUTABLE)),
        None)


def ask_claude(question, on_done):
    """Runs `claude -p` with no tools; on_done(answer_text, error_text). Returns the subprocess (to cancel)."""
    exe = claude_path()
    if not exe:
        on_done(None, "Claude Code isn't installed (no `claude` command found).")
        return None
    prompt = ("You are answering inside a small desktop notch. Reply in plain text, no markdown, "
              "at most about 120 words.\n\nQuestion: " + question)
    proc = Gio.Subprocess.new([exe, "-p", "--tools", "", "--", prompt],
                              Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE)

    def done(p, res):
        try:
            _ok, out, err = p.communicate_utf8_finish(res)
        except GLib.Error as e:
            on_done(None, e.message)
            return
        if p.get_exit_status() == 0 and out.strip():
            on_done(out.strip(), None)
        else:
            on_done(None, (err or out or "Claude didn't answer.").strip()[:400])
    proc.communicate_utf8_async(None, None, done)
    return proc
