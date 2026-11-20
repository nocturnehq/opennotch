"""Settings in ~/.config/opennotch/config.json. Unknown keys are ignored, bad values fall back to defaults."""
import json
import os
import re
import tempfile

from . import CONFIG_DIR

LEGACY_TIMER_KEY = "<Ctrl><Alt>T"

TABS = ["music", "web", "notifications", "shelf", "clipboard", "overview", "controls", "launcher", "camera", "claude"]
# tab names from the first version, mapped to the pages that replaced them
OLD_TABS = {"home": ["music", "overview", "controls"], "timer": ["overview"]}

DEFAULTS = {
    "pill_width": 128,
    "pill_height": 34,
    "corner_radius": 22,
    "card_width": 680,
    "card_height": 340,
    "accent": "#ffffff",
    "hover_delay_ms": 150,
    "tabs": list(TABS),
    "focus_minutes": 25,
    "break_minutes": 5,
    "weather_city": "",   # empty: guessed from the system time zone
    "lyrics": True,
    "volume_popups": True,
    "ask_claude": True,
    "web_panel": True,
    "launcher_panel": False,
    "camera_panel": False,
    "launch_apps": "",
    "media_info_on_drop": True,
    "chat_overlay": False,
    "app_rules": "",
    "lock_desktop_widgets": False,
    "desktop_widgets": False,
    "surface": "glass",        # black | glass (user: black pill, liquid-glass card)
    "resting": "empty",        # what the closed pill shows when nothing is going on
    "pet": "cat",
    "progress": "comet",       # comet | wave
    "clipboard_layout": "cards",
    "clipboard_size": 12,
    "clipboard_hours": 10,
    # mirrored from NotchPixel's settings (Settings window)
    "shape": "notch",
    "all_monitors": False,
    "higher_contrast": False,
    "window_text_size": 0,
    "reduce_motion": False,
    "longer_notices": False,
    "hidden_until_hover": False,
    "show_download_activity": True,
    "slim_strip": True,
    "language": "auto",
    "game_strip_fullscreen": False,
    "hide_in_fullscreen": False,
    "motion": "balanced",
    "color_pick": False,
    "position": "center",
    "edge_margin": 24,
    "side_position": 50,
    "top_gap": 6,
    "size": 100,
    "open_size": 100,
    "open_on": "last",
    "visualizer": "pixels",
    "font": "SF Pro Text",
    "music_background": "album",
    "anim_speed": "normal",
    "corner_pct": 100,
    "notification_seconds": 5,
    "reverse_scroll": False,
    "show_volume_hud": True,
    "show_brightness_hud": True,
    "show_battery_hud": True,
    "show_battery_estimate": True,
    "show_mic_hud": True,
    "title_in_pill": False,
    "media_source_mode": "all",
    "media_source_apps": "",
    "record_pc_sound": True,
    "game_strip_everywhere": False,
    "overlay_cpu": True,
    "overlay_gpu": True,
    "overlay_ram": True,
    "overlay_network": True,
    "overlay_upload": False,
    "overlay_clock": True,
    "network_in_bits": False,
    "time_format": "system",
    "day_clock_size": 100,
    "day_clock_color": "auto",
    "privacy_ignored_apps": "",
    "chat_opacity": 86,
    "chat_text_size": 11,
    "chat_popups": True,
    "reminder_sound": "once",
    "sites_watch": "",
    "show_bluetooth_hud": True,
    "show_lock_keys_hud": True,
    "show_call_activity": True,
    "mirror_notifications": True,
    "notifications_panel": True,
    "notice_clock_time": False,
    "shelf_enabled": True,
    "phone_share": True,
    "clipboard_enabled": True,
    "controls_panel": True,
    "show_date_widget": True,
    "show_timer_widget": True,
    "show_weather_widget": True,
    "show_stats_widget": True,
    "show_battery_widget": False,
    "show_storage_widget": False,
    "show_upnext_widget": False,
    "show_clock_widget": False,
    "show_nowplaying_widget": False,
    "show_notes_widget": False,
    "show_todo_widget": False,
    "show_calc_widget": False,
    "show_countdown_widget": False,
    "show_reminders_widget": False,
    "show_ping_widget": False,
    "show_currency_widget": False,
    "show_photos_widget": False,
    "world_clock_zone": "America/New_York",
    "world_clock_zone2": "",
    "world_clock_zone3": "",
    "countdown_title": "",
    "countdown_date": "",
    "ping_host": "1.1.1.1",
    "currency_watch": "USD: EUR, GBP",
    "photos_folder": "",
    "widget_order": ["date", "timer", "weather", "stats", "battery", "storage", "upnext", "clock", "nowplaying", "notes",
                     "todo", "calc", "countdown", "reminders", "ping", "currency", "photos"],
    "weather_fahrenheit": False,
    "notify_endpoint": True,
    "agents_notify_done": True,
    "captures_to_shelf": True,
    "screen_record": False,
    "record_microphone": False,
    "meeting_countdown": True,
    "calendar_file": "",
    "live_wallpaper": False,
    "live_wallpaper_file": "",
    "obs_enabled": False,
    "obs_password": "",
    "obs_port": 4455,
    "chat_twitch": "",
    "chat_youtube": "",
    "show_privacy_indicator": True,
    "custom_taskbar": True,
    "taskbar_auto_hide": True,
    "taskbar_status": True,
    "taskbar_number_keys": False,
    "taskbar_previews": False,
    "alt_tab_animation": False,
    "alt_tab_style": "ring",
    "key_toggle": "<Ctrl><Alt>N",
    "key_play": "<Ctrl><Alt>P",
    "key_timer": "<Ctrl><Alt>Y",
    "key_hide": "<Ctrl><Alt>H",
    "key_mic": "<Ctrl><Alt>M",
    "key_output": "<Ctrl><Alt>O",
    "key_chat_drawer": "<Ctrl><Alt><Shift>C",
}
CHOICES = {"language": ("auto", "en", "el"), "alt_tab_style": ("ring", "fan", "flip"), "surface": ("black", "glass"), "resting": ("empty", "clock", "pet"), "pet": ("cat", "dog", "bunny"), "progress": ("comet", "wave"),
           "shape": ("notch", "island"), "position": ("left", "center", "right", "left_side", "right_side"),
           "clipboard_layout": ("cards", "list"), "motion": ("fluid", "balanced", "battery"), "open_on": ("last", "music"), "visualizer": ("pixels", "bars"),
           "font": ("Nunito", "Geist", "Inter", "Roboto", "Noto Sans", "Ubuntu", "SF Pro Text"),
           "music_background": ("album", "black"), "anim_speed": ("relaxed", "normal", "quick"),
           "media_source_mode": ("all", "allow", "ignore"),
           "time_format": ("system", "24h", "12h"),
           "day_clock_color": ("auto", "white", "black"),
           "reminder_sound": ("once", "repeat", "off")}
BOOLS = ("lyrics", "volume_popups", "ask_claude", "desktop_widgets", "reverse_scroll", "show_volume_hud",
         "show_brightness_hud", "show_battery_hud", "show_battery_estimate", "show_mic_hud", "title_in_pill",
         "record_pc_sound", "game_strip_everywhere", "overlay_cpu", "overlay_gpu", "overlay_ram",
         "overlay_network", "overlay_upload", "overlay_clock", "network_in_bits", "chat_popups",
         "show_bluetooth_hud", "show_lock_keys_hud",
         "show_call_activity", "mirror_notifications", "notifications_panel",
         "notice_clock_time", "shelf_enabled", "clipboard_enabled", "controls_panel", "show_date_widget",
         "show_timer_widget", "show_weather_widget", "show_stats_widget", "show_battery_widget", "show_storage_widget", "show_upnext_widget", "show_clock_widget", "show_nowplaying_widget", "show_notes_widget",
         "show_todo_widget", "show_calc_widget", "show_countdown_widget", "show_reminders_widget", "show_ping_widget", "show_currency_widget", "show_photos_widget", "weather_fahrenheit", "notify_endpoint",
         "custom_taskbar", "taskbar_auto_hide", "taskbar_status", "higher_contrast", "reduce_motion",
         "longer_notices", "hidden_until_hover", "show_download_activity", "slim_strip", "game_strip_fullscreen", "taskbar_number_keys", "taskbar_previews", "alt_tab_animation",
         "hide_in_fullscreen", "color_pick", "agents_notify_done", "captures_to_shelf",
         "screen_record", "record_microphone", "show_privacy_indicator", "web_panel", "launcher_panel", "camera_panel", "media_info_on_drop", "chat_overlay", "lock_desktop_widgets", "all_monitors", "phone_share", "meeting_countdown", "obs_enabled", "live_wallpaper")
KEYS = ("key_toggle", "key_play", "key_timer", "key_hide", "key_mic", "key_output", "key_chat_drawer")

# key -> (min, max) for integers
RANGES = {
    "pill_width": (120, 600),
    "pill_height": (24, 60),
    "corner_radius": (0, 60),
    "card_width": (560, 1200),
    "card_height": (240, 800),
    "hover_delay_ms": (0, 3000),
    "focus_minutes": (1, 180),
    "break_minutes": (1, 60),
    "clipboard_size": (1, 500),
    "clipboard_hours": (1, 8760),
    "corner_pct": (0, 100),
    "edge_margin": (0, 120),
    "side_position": (0, 100),
    "window_text_size": (-2, 4),
    "top_gap": (0, 40),
    "size": (80, 140),
    "open_size": (80, 140),
    "notification_seconds": (1, 15),
    "obs_port": (1, 65535),
    "day_clock_size": (60, 160),
    "chat_opacity": (40, 100),
    "chat_text_size": (10, 20),
}


def validate(raw):
    """Return a full config dict built from DEFAULTS plus the valid parts of raw."""
    cfg = json.loads(json.dumps(DEFAULTS))
    if not isinstance(raw, dict):
        return cfg
    for key, (lo, hi) in RANGES.items():
        v = raw.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            cfg[key] = int(min(hi, max(lo, v)))
    accent = raw.get("accent")
    if isinstance(accent, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", accent):
        cfg["accent"] = accent.lower()
    for key in BOOLS:
        if isinstance(raw.get(key), bool):
            cfg[key] = raw[key]
    for key in KEYS:  # Keybinder accelerators like <Ctrl><Alt>N
        v = raw.get(key)
        if isinstance(v, str) and re.fullmatch(r"(<\w+>)*\w+", v.strip()):
            cfg[key] = v.strip()
    for key, allowed in CHOICES.items():
        if raw.get(key) in allowed:
            cfg[key] = raw[key]
    for key, limit in (("calendar_file", 4096), ("live_wallpaper_file", 4096), ("obs_password", 500),
                       ("media_source_apps", 500), ("countdown_title", 80), ("countdown_date", 32),
                       ("ping_host", 120), ("sites_watch", 200), ("currency_watch", 64), ("photos_folder", 4096),
                       ("launch_apps", 500), ("app_rules", 500), ("privacy_ignored_apps", 500)):
        value = raw.get(key)
        if isinstance(value, str) and len(value) <= limit and "\x00" not in value:
            cfg[key] = value
    for zk in ("world_clock_zone2", "world_clock_zone3"):
        z = raw.get(zk)
        if isinstance(z, str):
            z = z.strip()
            if not z:
                cfg[zk] = ""
            elif len(z) <= 64:
                try:
                    from zoneinfo import ZoneInfo

                    ZoneInfo(z)
                    cfg[zk] = z
                except (ValueError, KeyError, OSError):
                    pass
    twitch = raw.get("chat_twitch")
    if isinstance(twitch, str):
        from .twitchchat import channel_name
        cfg["chat_twitch"] = channel_name(twitch) or ""  # blank or unusable value = off
    youtube = raw.get("chat_youtube")
    if isinstance(youtube, str):
        from .youtubechat import target
        cfg["chat_youtube"] = youtube.strip() if len(youtube) <= 200 and target(youtube) else ""
    zone = raw.get("world_clock_zone")
    if isinstance(zone, str) and 0 < len(zone) <= 64:
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(zone.strip())
            cfg["world_clock_zone"] = zone.strip()
        except (ValueError, KeyError, OSError):
            pass  # unknown zone: keep the default
    order = raw.get("widget_order")
    if isinstance(order, list):
        known = DEFAULTS["widget_order"]
        wanted = [w for w in dict.fromkeys(order) if w in known]
        cfg["widget_order"] = wanted + [w for w in known if w not in wanted]  # new widgets join at the end
    city = raw.get("weather_city")
    if isinstance(city, str) and len(city) <= 80:
        cfg["weather_city"] = city.strip()
    tabs = raw.get("tabs")
    if isinstance(tabs, list):
        tabs = [n for t in tabs for n in OLD_TABS.get(t, [t])]
        wanted = [t for t in TABS if t in tabs]  # keep the built-in order, drop unknown names
        if wanted:
            cfg["tabs"] = wanted
    return cfg


def load(path=None):
    path = path or os.path.join(CONFIG_DIR, "config.json")
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        raw = {}
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(DEFAULTS, f, indent=2)
        except OSError:
            pass
    except (OSError, ValueError) as e:
        print(f"opennotch: ignoring unreadable config {path}: {e}")
        raw = {}
    return validate(raw)


def set_value(key, value):
    """Update one key without discarding unknown or desktop-only options."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    path = os.path.join(CONFIG_DIR, "config.json")
    try:
        with open(path, encoding="utf-8") as original:
            raw = json.load(original)
    except FileNotFoundError:
        raw = {}
    except ValueError as error:
        raise OSError(f"invalid configuration in {path}") from error
    if not isinstance(raw, dict):
        raw = {}
    raw[key] = value
    fd, temp_path = tempfile.mkstemp(prefix=".config-", dir=CONFIG_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            json.dump(raw, target, indent=2)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    return validate(raw)
