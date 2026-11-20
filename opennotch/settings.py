"""OpenNotch Settings: every NotchPixel setting, grouped the same way, drawn as a dark liquid-glass window.

Settings are written straight into ~/.config/opennotch/config.json; the running notch watches that file and
restarts itself to apply them. A few settings change the desktop directly (autostart, the dock, the system
volume pop-up) and are applied here. Settings marked "Soon" are saved but do nothing yet.
"""
import json
import os
import re
import subprocess
import sys

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

from . import CONFIG_DIR, config, design, i18n  # noqa: E402

CFG_PATH = os.path.join(CONFIG_DIR, "config.json")
AUTOSTART = os.path.join(GLib.get_user_config_dir(), "autostart", "opennotch.desktop")

ACCENTS = ["#ffffff", "#0a84ff", "#3b82f6", "#a855f7", "#ec4899", "#f59e0b", "#22c55e", "#38bdf8",
           "#f9a8d4", "#c4b5fd", "#fdba74", "#f9a8d4"]


# ---- the catalogue: (section, icon, [(group, [setting])]) -----------------------------------------
# setting = dict(key, title, desc, kind, ...); kind: toggle | choice | slider | number | text | color | info
def T(key, title, desc="", soon=False):
    return dict(key=key, title=title, desc=desc, kind="toggle", soon=soon)


def C(key, title, desc, options, soon=False):
    return dict(key=key, title=title, desc=desc, kind="choice", options=options, soon=soon)


def S(key, title, desc, lo, hi, unit="", soon=False, step=1):
    return dict(key=key, title=title, desc=desc, kind="slider", lo=lo, hi=hi, unit=unit, soon=soon, step=step)


def N(key, title, desc, lo, hi, soon=False):
    return dict(key=key, title=title, desc=desc, kind="number", lo=lo, hi=hi, soon=soon)


def X(key, title, desc, placeholder="", soon=False, secret=False):
    return dict(key=key, title=title, desc=desc, kind="text", placeholder=placeholder, soon=soon, secret=secret)


def O(key, title, desc, items):
    return dict(key=key, title=title, desc=desc, kind="order", items=items)


def F(key, title, desc, patterns):
    return dict(key=key, title=title, desc=desc, kind="file", patterns=patterns)


SECTIONS = [
    ("General", "preferences-system-symbolic", [
        ("Language", [C("language", "Language", "The island, its notices and this window.",
                        [("auto", "Same as system"), ("en", "English")])]),
        ("General", [
            T("autostart", "Run at startup", "Start OpenNotch when you log in."),
            T("slim_strip", "Slim strip under maximized windows",
              "Collapse to a thin line so the island never covers browser tabs. Rest the cursor on it to open."),
            C("open_on", "When the island opens", "Last tab opens the card you were on when it closed. Music always "
              "opens the music card while something plays.", [("last", "Last tab"), ("music", "Music")]),
        ]),
    ]),
    ("Accessibility", "preferences-desktop-accessibility-symbolic", [
        ("Reading", [T("higher_contrast", "Higher contrast", "Brighter secondary text and stronger edges."),
                     S("window_text_size", "Text size", "Text in this window.", -2, 4, " pt")]),
        ("Motion", [T("reduce_motion", "Reduce motion", "Cards fade instead of growing and bouncing."),
                    T("longer_notices", "Longer notices", "Notices stay twice as long.")]),
    ]),
    ("Appearance", "applications-graphics-symbolic", [
        ("Appearance", [
            C("shape", "Shape", "Island floats just below the top edge, round all over. Notch hangs from the edge and "
              "curves into it, like a MacBook's.", [("island", "Island"), ("notch", "Notch")]),
            S("top_gap", "Distance from top", "Space between the top of the screen and the island. The Notch shape "
              "always hangs from the edge.", 0, 40, " px"),
            C("resting", "When resting, show", "What the island shows while nothing plays and nothing is going on.",
              [("empty", "Nothing"), ("clock", "Time, weather and battery"), ("pet", "Pet")]),
            C("pet", "Pet", "Who lives on the resting island.", [("cat", "Cat"), ("dog", "Dog"), ("bunny", "Bunny")]),
            S("size", "Size", "The pill, the card and their text scale together.", 80, 140, "%"),
            S("open_size", "Open size", "How big the island grows when it opens.", 80, 140, "%"),
            C("motion", "Motion", "Fluid moves at the screen's full refresh rate; Battery saver keeps it under 60 "
              "frames a second.", [("fluid", "Fluid"), ("balanced", "Balanced"), ("battery", "Battery saver")]),
            C("visualizer", "Visualizer", "What plays beside the artwork on the pill while music plays.",
              [("pixels", "Pixels"), ("bars", "Bars")]),
            C("font", "Font", "The letters the island, the taskbar and this window write in.",
              [("Nunito", "Nunito"), ("Geist", "Geist"), ("Inter", "Inter"), ("Roboto", "Roboto"), ("Noto Sans", "Noto Sans"),
               ("Ubuntu", "Ubuntu"), ("SF Pro Text", "SF Pro")]),
            S("corner_pct", "Corners", "How round the corners are, from square to fully round.", 0, 100, "%"),
            C("surface", "Surface", "Glass softly blurs what's behind the island, like liquid glass. Black is a "
              "near-black island with a faint rim.", [("black", "Black"), ("glass", "Glass")]),
            dict(key="accent", title="Accent", desc="Colours the visualizer, progress and level bars.", kind="color"),
            C("music_background", "Music background", "The music card takes the artwork's colours, or stays black.",
              [("album", "Album"), ("black", "Black")]),
            C("progress", "Progress bar", "How the song's progress is drawn.", [("comet", "Comet"), ("wave", "Wave")]),
        ]),
    ]),
    ("Island", "view-app-grid-symbolic", [
        ("Placement", [
            C("position", "Position", "Where the island sits along the top or side edges of the screen.",
              [("left", "Left"), ("center", "Center"), ("right", "Right"),
               ("left_side", "Left side"), ("right_side", "Right side")]),
            S("edge_margin", "Edge margin", "Distance from the side when the island sits at the left or right of the top edge.",
              0, 120, " px"),
            S("side_position", "Height on the side", "Position down the left or right side.", 0, 100, "%"),
            T("all_monitors", "Every screen", "Open the same island and controls from each screen."),
            T("hidden_until_hover", "Hidden until hover", "Nothing on screen until you rest the pointer on the edge."),
            S("hover_delay_ms", "Open delay", "How long the pointer rests on the island before it opens.", 0, 1000,
              " ms", step=10),
            T("reverse_scroll", "Reverse scrolling on the island", "The wheel turns tabs and volume the other way."),
            C("anim_speed", "Animation speed", "How fast the island opens, closes and changes shape.",
              [("relaxed", "Relaxed"), ("normal", "Normal"), ("quick", "Quick")]),
        ]),
        ("HUDs", [
            T("show_volume_hud", "Volume", "Show volume changes in the island."),
            T("replace_volume_flyout", "Hide the system volume pop-up", "The island is the only readout."),
            T("show_mic_hud", "Microphone mute", "Show an indicator when muting or unmuting the mic."),
            T("show_brightness_hud", "Brightness", "Show screen brightness changes."),
            T("show_battery_hud", "Battery", "Charging, unplugged and low battery."),
            T("show_battery_estimate", "Battery time estimate", "Show estimated time remaining or to full."),
            T("show_bluetooth_hud", "Bluetooth devices", "Connect and disconnect, with battery level."),
            T("show_lock_keys_hud", "Caps Lock and Num Lock", "Show when a lock key is turned on or off."),
        ]),
        ("Live activities", [
            T("title_in_pill", "Track title in closed pill", "Show the playing song's title beside the equalizer."),
            C("media_source_mode", "Media players", "Which media players the island listens to.",
              [("all", "All"), ("allow", "Only listed"), ("ignore", "Ignore listed")]),
            X("media_source_apps", "Player filter list", "Comma-separated player names (e.g. spotify, firefox).", "spotify, brave"),
            T("show_download_activity", "Downloads", "Files arriving in your Downloads folder."),
            T("show_call_activity", "Calls", "A red dot and a timer while an app uses the microphone."),
            T("show_privacy_indicator", "Privacy dot", "Show when PipeWire reports an active camera or screen share. OpenNotch always shows its own recording indicator."),
            T("lyrics", "Lyrics", "A button on the music card opens synced lyrics (LRCLIB)."),
        ]),
    ]),
    ("Taskbar", "user-desktop-symbolic", [
        ("OpenNotch taskbar", [
            T("custom_taskbar", "OpenNotch taskbar", "A black notch along the bottom of the screen for your apps (Plank)."),
            T("taskbar_status", "Tray and clock", "Show system status icons, time and date beside the dock."),
            T("taskbar_auto_hide", "Hide over maximized windows", "Maximized windows get the whole screen; push the "
              "pointer to the bottom edge to bring it back."),
            T("taskbar_dock", "Dock effect", "Icons grow as the pointer passes over them."),
            S("taskbar_dock_size", "Dock size", "How big the icon under the pointer grows.", 100, 200, "%"),
            T("taskbar_previews", "Window previews", "Rest the pointer on an app to see its windows."),
            T("taskbar_number_keys", "Super + number opens the taskbar's apps", "Super+1 to 9 open or switch to the dock's apps in order."),
        ]),
        ("Alt+Tab", [T("alt_tab_animation", "Custom Alt+Tab animation",
                       "OpenNotch draws the window switcher. Hold Alt, press Tab to move, let go to switch."),
                     C("alt_tab_style", "Style", "", [("ring", "Ring"), ("fan", "Fan"), ("flip", "Flip 3D")])]),
    ]),
    ("Panels", "view-grid-symbolic", [
        ("Notifications", [
            T("mirror_notifications", "Mirror notifications", "New notifications appear in the island."),
            S("notification_seconds", "Notification time", "How long a new notification shows on the closed island.",
              1, 15, " s"),
            T("notifications_panel", "Notifications tab", "A tab that keeps the latest notices."),
            T("notice_clock_time", "Clock times", "Show when each notification came, like 14:32, instead of 22m."),
        ]),
        ("Files and clipboard", [
            T("shelf_enabled", "Files tab", "Drop files on the island to park them; drag them out into any app."),
            T("captures_to_shelf", "Captures on the shelf", "Ctrl+Alt+S saves a screenshot and adds it to the shelf."),
            T("phone_share", "Send to phone", "Share a shelf file to your phone using a QR code that expires."),
            T("clipboard_enabled", "Clipboard history", "Keeps copied text in the island. Password managers' "
              "copies are skipped."),
            C("clipboard_layout", "Clipboard layout", "Cards in a strip, or a list.", [("cards", "Cards"),
                                                                                     ("list", "List")]),
            N("clipboard_size", "Entries to keep", "Pinned entries don't count.", 1, 500),
            N("clipboard_hours", "Hours to keep them", "Copied text is kept this long, even across a restart.", 1, 8760),
        ]),
        ("Controls and web", [
            T("controls_panel", "Controls tab", "Brightness and volume sliders, Wi-Fi, Bluetooth, night light, focus, mute."),
            T("web_panel", "Web tab", "Open music sites in a browser inside the island."),
            T("ask_claude", "Ask Claude tab", "Questions answered by your Claude Code sign-in."),
        ]),
    ]),
    ("Widgets", "view-dual-symbolic", [
        ("Overview widgets", [
            T("show_date_widget", "Today", "The date and this week."),
            T("show_timer_widget", "Focus timer", "A Pomodoro timer you start on the island."),
            T("show_weather_widget", "Weather", "Now, and today's high and low."),
            T("show_stats_widget", "System stats", "CPU, GPU, memory and network as they move."),
            T("show_battery_widget", "Battery", "Charge, and whether it's charging."),
            T("show_storage_widget", "Storage", "Free space on your home drive."),
            T("show_upnext_widget", "Up next", "The next meeting from your calendar file (Settings › Calls)."),
            T("show_clock_widget", "World clock", "The time in a second city."),
            T("show_nowplaying_widget", "Now playing", "A compact player for what's playing."),
            T("show_notes_widget", "Notes", "A scratchpad that saves as you type."),
            O("widget_order", "Order", "Move widgets up or down; the overview fills two columns in this order.",
              [("date", "Today"), ("timer", "Focus timer"), ("weather", "Weather"), ("stats", "System stats"),
               ("battery", "Battery"), ("storage", "Storage"), ("upnext", "Up next"), ("clock", "World clock"),
               ("nowplaying", "Now playing"), ("notes", "Notes")]),
            X("world_clock_zone", "World clock city", "A time zone, like America/New_York or Asia/Tokyo.", "Area/City"),
            N("focus_minutes", "Focus minutes", "", 1, 180),
            N("break_minutes", "Break minutes", "", 1, 60),
        ]),
        ("Weather", [X("weather_city", "Weather location", "Empty: guessed from your time zone.", "e.g. Athens"),
                     T("weather_fahrenheit", "Fahrenheit", "")]),
        ("Day clock", [T("desktop_widgets", "Day clock on the desktop", "The day, date and time in big spaced "
                         "letters on your wallpaper.")]),
    ]),
    ("Wallpaper", "preferences-desktop-wallpaper-symbolic", [
        ("Live wallpaper", [T("live_wallpaper", "Play a live wallpaper", "Loop a local video behind desktop icons and panels."),
                            F("live_wallpaper_file", "Video", "Choose a local video to loop.",
                              ["*.mp4", "*.mkv", "*.webm", "*.mov", "*.avi", "*.MP4", "*.MKV", "*.WEBM"])]),
    ]),
    ("Calls", "call-start-symbolic", [
        ("Calls", [T("meeting_countdown", "Meeting countdown", "Show the next timed meeting in the hour before it starts."),
                   F("calendar_file", "Calendar file", "Choose a local iCalendar export for the countdown.", ["*.ics", "*.ICS"]),
                   T("record_microphone", "Record microphone", "Your voice in screen recordings."),
                   T("record_pc_sound", "Record desktop audio", "Include PC sound in screen recordings.")]),
    ]),
    ("Streaming", "camera-video-symbolic", [
        ("Streaming", [T("obs_enabled", "OBS", "Show recording and streaming status from local OBS. Ctrl+Alt+R toggles recording."),
                       N("obs_port", "OBS WebSocket port", "The port set in OBS WebSocket Server Settings.", 1, 65535),
                       X("obs_password", "OBS WebSocket password", "Used only to connect to OBS on this computer.", secret=True),
                       X("chat_twitch", "Twitch chat", "Show messages from this channel. Leave blank to turn it off.", "channel"),
                       X("chat_youtube", "YouTube chat", "A channel (@name) or live video link. Leave blank to turn it off.", "@channel or link")]),
    ]),
    ("Gaming", "input-gaming-symbolic", [
        ("Game strip", [T("game_strip_fullscreen", "Game strip", "In fullscreen apps and games, a CPU, GPU and RAM "
                          "strip instead of hiding."),
                        T("game_strip_everywhere", "Show game strip everywhere", "Keep the stats strip on the pill even outside fullscreen."),
                        T("overlay_network", "Show network speed", "Include live download rate in the game strip."),
                        T("overlay_clock", "Show clock", "Include the time in the game strip."),
                        T("hide_in_fullscreen", "Hide in fullscreen", "")]),
    ]),
    ("AI agents", "user-available-symbolic", [
        ("Agents", [T("agents_notify_done", "Tell me when an agent is done", "Coding agents can pop a message out "
                      "of the island with `opennotch done`."),
                    T("notify_endpoint", "Local message endpoint", "Programs on this PC can put a line on the island "
                      "through a socket only this PC can reach.")]),
    ]),
    ("Tools", "applications-utilities-symbolic", [
        ("Tools", [T("color_pick", "Colour picker", "Ctrl+Alt+C copies the colour under the pointer."),
                   T("screen_record", "Screen recording", "Start or stop recording the current screen with Ctrl+Alt+Shift+R.")]),
    ]),
    ("Keys", "input-keyboard-symbolic", [
        ("Shortcuts", [X("key_toggle", "Open or close the island", "", "<Ctrl><Alt>N"),
                       X("key_play", "Play / pause", "", "<Ctrl><Alt>P"),
                       X("key_timer", "Focus timer", "", config.DEFAULTS["key_timer"]),
                       X("key_hide", "Hide the island", "", "<Ctrl><Alt>H"),
                       X("key_mic", "Mute the microphone everywhere", "", "<Ctrl><Alt>M"),
                       X("key_output", "Switch audio output", "", "<Ctrl><Alt>O")]),
    ]),
    ("About", "help-about-symbolic", [
        ("About", [dict(key="", title="OpenNotch", desc="A free Dynamic-Island-style notch for Linux. Settings mirror "
                        "NotchPixel's; motion timings and gestures follow NotchX (MIT).", kind="info")]),
    ]),
]

CSS = b"""
#glass * { color: #f5f5f7; font-family: "Geist", "SF Pro Text", sans-serif; }
#glass .dim { color: rgba(255,255,255,0.55); font-size: 11px; }
#glass .h1 { font-size: 26px; font-weight: 700; }
#glass .eyebrow { color: rgba(255,255,255,0.45); font-size: 10px; font-weight: 600; letter-spacing: 1px; }
#glass .stitle { font-size: 13px; font-weight: 600; }
#glass .soon { background: rgba(255,255,255,0.10); border-radius: 8px; padding: 1px 7px; font-size: 10px;
  color: rgba(255,255,255,0.6); }
#glass .row { border-bottom: 1px solid rgba(255,255,255,0.07); padding: 12px 0; }
#glass list, #glass row, #glass scrolledwindow, #glass viewport { background: transparent; border: none; }
#glass row.side { border-radius: 10px; padding: 7px 10px; transition: background-color 160ms ease-out; }
#glass row.side:selected, #glass row.side:hover { background: rgba(255,255,255,0.10); }
#glass entry { background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.08); border-radius: 10px;
  padding: 5px 10px; box-shadow: none; caret-color: #fff; }
#glass button { background: rgba(255,255,255,0.08); background-image: none; border: none; box-shadow: none;
  border-radius: 10px; padding: 4px 12px; transition: background-color 160ms ease-out; text-shadow: none; }
#glass button:hover { background: rgba(255,255,255,0.16); }
#glass button.seg { background: transparent; border-radius: 99px; padding: 4px 12px; }
#glass button.seg.active { background: #f5f5f7; }
#glass button.seg.active label { color: #0b0b0c; }
#glass .segbar { background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.07); border-radius: 99px;
  padding: 2px; }
#glass button.swatch { border-radius: 99px; min-width: 20px; min-height: 20px; padding: 0; }
#glass button.swatch.active { box-shadow: 0 0 0 2px #0b0b0c, 0 0 0 4px #f5f5f7; }
#glass switch { background: rgba(255,255,255,0.14); border: none; border-radius: 99px; }
#glass switch:checked { background: #f5f5f7; }
#glass switch slider { background: #0b0b0c; border: none; border-radius: 99px; min-width: 20px; min-height: 20px;
  margin: 2px; box-shadow: none; }
#glass switch:checked slider { background: #0b0b0c; }
#glass scale trough { background: rgba(255,255,255,0.12); border-radius: 3px; min-height: 4px; border: none; }
#glass scale highlight { background: #f5f5f7; border-radius: 3px; border: none; }
#glass scale slider { background: #f5f5f7; border: none; border-radius: 99px; min-width: 14px; min-height: 14px;
  box-shadow: none; }
#glass spinbutton { background: rgba(255,255,255,0.08); border: none; border-radius: 10px; }
"""


def rounded(cr, x, y, w, h, r):
    cr.new_path()
    cr.arc(x + w - r, y + r, r, -1.5708, 0)
    cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
    cr.arc(x + r, y + h - r, r, 1.5708, 3.1416)
    cr.arc(x + r, y + r, r, 3.1416, 4.7124)
    cr.close_path()


def load_raw():
    try:
        with open(CFG_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def mark_choice(buttons, value):
    for v, b in buttons:
        (b.get_style_context().add_class if v == value else b.get_style_context().remove_class)("active")


class Settings(Gtk.Window):
    W, H = 980, 680

    def __init__(self):
        super().__init__(title="OpenNotch Settings")
        self.set_name("glass")
        self.raw = load_raw()
        self.cfg = config.validate(self.raw)
        i18n.setup(self.cfg["language"])
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.set_decorated(False)
        self.set_default_size(self.W, self.H)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.glass = None
        self.connect("draw", self._draw)
        self.connect("map-event", lambda *_: GLib.timeout_add(60, self._capture))
        self.connect("configure-event", lambda *_: self._capture_soon())
        self.style = Gtk.CssProvider()
        self._apply_style()
        Gtk.StyleContext.add_provider_for_screen(self.get_screen(), self.style, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        outer = Gtk.Box(spacing=0)
        for side in ("top", "bottom", "start", "end"):
            getattr(outer, f"set_margin_{side}")(14)
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        side.set_size_request(220, -1)
        head = Gtk.EventBox()
        head.connect("button-press-event", self._drag)
        hb = Gtk.Box(spacing=8)
        hb.set_margin_start(8)
        hb.set_margin_top(6)
        hb.set_margin_bottom(6)
        hb.pack_start(self._lbl("OpenNotch", "stitle"), False, False, 0)
        head.add(hb)
        side.pack_start(head, False, False, 0)
        self.search = Gtk.SearchEntry(placeholder_text=i18n.tr("Search settings"))
        self.search.connect("search-changed", lambda *_: self._filter())
        side.pack_start(self.search, False, False, 0)
        self.nav = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.nav.connect("row-selected", lambda _l, row: row and self._show(row.section))
        for name, icon, _groups in SECTIONS:
            row = Gtk.ListBoxRow()
            row.section = name
            row.get_style_context().add_class("side")
            b = Gtk.Box(spacing=10)
            b.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU), False, False, 0)
            b.pack_start(self._lbl(name), False, False, 0)
            row.add(b)
            self.nav.add(row)
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        sw.add(self.nav)
        side.pack_start(sw, True, True, 0)
        outer.pack_start(side, False, False, 0)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        top = Gtk.EventBox()
        top.connect("button-press-event", self._drag)
        tb = Gtk.Box()
        close = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.MENU)
        close.connect("clicked", lambda *_: self.destroy())
        tb.pack_end(close, False, False, 0)
        top.add(tb)
        right.pack_start(top, False, False, 0)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_UP_DOWN, transition_duration=220)
        self.rows = []  # (section, row widget, searchable text)
        self.choices = {}  # key → [(value, button)] of each segmented choice
        for name, _icon, groups in SECTIONS:
            self.stack.add_named(self._page(name, groups), name)
        right.pack_start(self.stack, True, True, 0)
        outer.pack_start(right, True, True, 24)
        self.add(outer)
        self.nav.select_row(self.nav.get_row_at_index(0))

    def _apply_style(self):
        css = CSS.decode() + design.settings_css(self.cfg["font"])
        if self.cfg["higher_contrast"]:
            css = css.replace("255,255,255,0.55", "255,255,255,0.82")
            css = css.replace("255,255,255,0.45", "255,255,255,0.78")
        delta = self.cfg["window_text_size"]
        css = re.sub(r"font-size: (\d+)px", lambda m: f"font-size: {int(m[1]) + delta}px", css)
        css = f"#glass * {{ font-size: {13 + delta}px; }}\n" + css if delta else css
        self.style.load_from_data(css.encode())

    # ---- glass background: blurred snapshot of what's behind, a dark tint, a bright rim
    def _capture_soon(self):
        if getattr(self, "_cap_pending", 0):
            GLib.source_remove(self._cap_pending)
        self._cap_pending = GLib.timeout_add(250, self._capture)
        return False

    def _capture(self):
        self._cap_pending = 0
        win = self.get_window()
        if not win:
            return False
        _, x, y = win.get_origin()
        w, h = self.get_allocated_width(), self.get_allocated_height()
        self.set_opacity(0)  # look behind ourselves for one frame
        GLib.timeout_add(40, self._grab, x, y, w, h)
        return False

    def _grab(self, x, y, w, h):
        try:
            pb = Gdk.pixbuf_get_from_window(Gdk.get_default_root_window(), x, y, w, h)
            if pb is not None:
                small = pb.scale_simple(max(1, w // 16), max(1, h // 16), GdkPixbuf.InterpType.BILINEAR)
                self.glass = small.scale_simple(w, h, GdkPixbuf.InterpType.BILINEAR)
            else:
                self.glass = None
        except (GLib.Error, TypeError):
            self.glass = None
        self.set_opacity(1)
        self.queue_draw()
        return False

    def _draw(self, _w, cr):
        w, h = self.get_allocated_width(), self.get_allocated_height()
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        rounded(cr, 0.5, 0.5, w - 1, h - 1, 22)
        cr.save()
        cr.clip_preserve()
        if self.glass:
            Gdk.cairo_set_source_pixbuf(cr, self.glass, 0, 0)
            cr.paint()
        g = cairo.LinearGradient(0, 0, w, h)
        g.add_color_stop_rgba(0, 0.09, 0.09, 0.11, 0.72)
        g.add_color_stop_rgba(1, 0.03, 0.03, 0.04, 0.84)
        cr.set_source(g)
        cr.paint()
        sheen = cairo.LinearGradient(0, 0, 0, h * 0.4)
        sheen.add_color_stop_rgba(0, 1, 1, 1, 0.06)
        sheen.add_color_stop_rgba(1, 1, 1, 1, 0)
        cr.set_source(sheen)
        cr.paint()
        cr.set_source_rgba(1, 1, 1, 0.06)  # sidebar panel
        rounded(cr, 10, 10, 236, h - 20, 16)
        cr.fill()
        cr.restore()
        rim = cairo.LinearGradient(0, 0, w, h)
        rim.add_color_stop_rgba(0, 1, 1, 1, 0.30)
        rim.add_color_stop_rgba(0.5, 1, 1, 1, 0.06)
        rim.add_color_stop_rgba(1, 1, 1, 1, 0.18)
        cr.set_source(rim)
        cr.set_line_width(1)
        cr.stroke()
        return False

    def _drag(self, _w, ev):
        if ev.button == 1:
            self.begin_move_drag(ev.button, int(ev.x_root), int(ev.y_root), ev.time)
        return False

    # ---- pages
    @staticmethod
    def _lbl(text, css=None, xalign=0.0, wrap=False):
        lb = Gtk.Label(label=i18n.tr(text), xalign=xalign)
        if wrap:
            lb.set_line_wrap(True)
            lb.set_max_width_chars(60)
        for c in (css or "").split():
            lb.get_style_context().add_class(c)
        return lb

    def _page(self, name, groups):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_end(8)
        box.pack_start(self._lbl(i18n.caps(i18n.tr("Settings")), "eyebrow"), False, False, 0)
        box.pack_start(self._lbl(name, "h1"), False, False, 6)
        for group, items in groups:
            g = self._lbl(i18n.caps(i18n.tr(group)), "eyebrow")
            g.set_margin_top(14)
            box.pack_start(g, False, False, 0)
            for spec in items:
                row = self._row(spec)
                box.pack_start(row, False, False, 0)
                self.rows.append((name, row, " ".join((spec["title"], spec["desc"], i18n.tr(spec["title"]),
                                                       i18n.tr(spec["desc"]))).lower()))
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        sw.add(box)
        return sw

    def _row(self, spec):
        row = Gtk.Box(spacing=16)
        row.get_style_context().add_class("row")
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER)
        tl = Gtk.Box(spacing=8)
        tl.pack_start(self._lbl(spec["title"], "stitle"), False, False, 0)
        if spec.get("soon"):
            tl.pack_start(self._lbl("Soon", "soon"), False, False, 0)
        text.pack_start(tl, False, False, 0)
        if spec["desc"]:
            text.pack_start(self._lbl(spec["desc"], "dim", wrap=True), False, False, 0)
        row.pack_start(text, True, True, 0)
        ctl = self._control(spec)
        if ctl:
            ctl.set_valign(Gtk.Align.CENTER)
            row.pack_end(ctl, False, False, 0)
        if spec.get("soon"):
            row.set_opacity(0.55)
        return row

    def _value(self, key):
        if key in self.cfg:
            return self.cfg[key]
        return self.raw.get(key, EXTRA_DEFAULTS.get(key))

    def _control(self, spec):
        key, kind = spec["key"], spec["kind"]
        if kind == "toggle":
            sw = Gtk.Switch(active=bool(self._value(key)))
            sw.connect("notify::active", lambda s, _p: self._set(key, s.get_active()))
            return sw
        if kind == "choice":
            bar = Gtk.Box(spacing=2)
            bar.get_style_context().add_class("segbar")
            buttons = []
            cur = self._value(key)

            def pick(_b, v, btns):
                mark_choice(btns, v)
                self._set(key, v)
            for v, title in spec["options"]:
                b = Gtk.Button(label=i18n.tr(title))
                b.get_style_context().add_class("seg")
                if v == cur:
                    b.get_style_context().add_class("active")
                buttons.append((v, b))
                bar.pack_start(b, False, False, 0)
            for v, b in buttons:
                b.connect("clicked", pick, v, buttons)
            self.choices[key] = buttons
            return bar
        if kind == "order":
            names = dict(spec["items"])
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            col.get_style_context().add_class("orderlist")

            def fill():
                for child in col.get_children():
                    child.destroy()
                order = list(self._value(key))
                for i, name in enumerate(order):
                    row = Gtk.Box(spacing=6)
                    row.pack_start(self._lbl(names.get(name, name), "stitle"), True, True, 0)
                    for icon, step in (("go-up-symbolic", -1), ("go-down-symbolic", 1)):
                        b = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
                        b.get_style_context().add_class("seg")
                        b.set_sensitive(0 <= i + step < len(order))
                        b.connect("clicked", lambda _b, i=i, step=step: move(i, step))
                        row.pack_end(b, False, False, 0)
                    col.pack_start(row, False, False, 0)
                col.show_all()

            def move(i, step):
                order = list(self._value(key))
                order[i], order[i + step] = order[i + step], order[i]
                self._set(key, order)
                fill()
            fill()
            return col
        if kind == "slider":
            box = Gtk.Box(spacing=10)
            sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, spec["lo"], spec["hi"], spec["step"])
            sc.set_draw_value(False)
            sc.set_size_request(170, -1)
            sc.set_value(float(self._value(key) or spec["lo"]))
            val = self._lbl(f"{int(sc.get_value())}{spec['unit']}", "dim", xalign=1)
            val.set_width_chars(7)
            sc.connect("value-changed", lambda s: (val.set_text(f"{int(s.get_value())}{spec['unit']}"),
                                                   self._set_later(key, int(s.get_value()))))
            box.pack_start(sc, False, False, 0)
            box.pack_start(val, False, False, 0)
            return box
        if kind == "number":
            sb = Gtk.SpinButton.new_with_range(spec["lo"], spec["hi"], 1)
            sb.set_value(float(self._value(key) or spec["lo"]))
            sb.connect("value-changed", lambda s: self._set_later(key, int(s.get_value())))
            return sb
        if kind == "text":
            secret = spec.get("secret", False)
            en = Gtk.Entry(placeholder_text=i18n.tr(spec.get("placeholder", "")), visibility=not secret)
            en.set_text(str(self._value(key) or ""))
            en.set_width_chars(18)
            en.connect("changed", lambda e: self._set_later(key, e.get_text() if secret else e.get_text().strip()))
            return en
        if kind == "file":
            chooser = Gtk.FileChooserButton(title=spec["title"], action=Gtk.FileChooserAction.OPEN)
            chooser.set_local_only(True)
            chooser.set_width_chars(18)
            file_filter = Gtk.FileFilter()
            file_filter.set_name(spec["title"])
            for pattern in spec["patterns"]:
                file_filter.add_pattern(pattern)
            chooser.add_filter(file_filter)
            path = self._value(key)
            if path:
                chooser.set_filename(os.path.expanduser(path))
            chooser.connect("file-set", lambda button: self._set(key, button.get_filename() or ""))
            return chooser
        if kind == "color":
            grid = Gtk.FlowBox(max_children_per_line=6, selection_mode=Gtk.SelectionMode.NONE)
            cur = self._value(key)
            sw = []

            def pick(_b, c):
                for cc, bb in sw:
                    (bb.get_style_context().add_class if cc == c else bb.get_style_context().remove_class)("active")
                self._set(key, c)
            for c in dict.fromkeys(ACCENTS):
                b = Gtk.Button()
                b.get_style_context().add_class("swatch")
                prov = Gtk.CssProvider()
                prov.load_from_data(f"button {{ background: {c}; }}".encode())
                b.get_style_context().add_provider(prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
                if c == cur:
                    b.get_style_context().add_class("active")
                sw.append((c, b))
                b.connect("clicked", pick, c)
                grid.add(b)
            return grid
        return None

    def _show(self, name):
        self.stack.set_visible_child_name(name)

    def _filter(self):
        q = self.search.get_text().strip().lower()
        hits = set()
        for section, row, text in self.rows:
            ok = not q or q in text
            row.set_visible(ok)
            if ok and q:
                hits.add(section)
        if q and hits:
            for r in self.nav.get_children():
                if r.section in hits:
                    self.nav.select_row(r)
                    break

    # ---- saving
    def _set_later(self, key, value):
        self.pending = getattr(self, "pending", {})
        self.pending[key] = value
        if getattr(self, "_save_timer", 0):
            GLib.source_remove(self._save_timer)
        self._save_timer = GLib.timeout_add(500, self._flush)

    def _flush(self):
        self._save_timer = 0
        for k, v in self.pending.items():
            self._set(k, v)
        self.pending = {}
        return False

    def _set(self, key, value):
        try:
            self.cfg = config.set_value(key, value)
        except OSError as error:
            print(f"opennotch: could not save {key}: {error}")
            return
        self.raw = load_raw()
        apply_system(key, value)
        if key in ("higher_contrast", "window_text_size"):
            self._apply_style()
        if key == "pet" and self.cfg["resting"] != "pet":  # picking a pet with "Nothing" resting would show nothing
            mark_choice(self.choices.get("resting", []), "pet")
            self._set("resting", "pet")
        if key == "language":  # every label is built once, so start the window again in the new language
            os.execv(sys.executable, [sys.executable, "-m", "opennotch", "settings"])


# settings that are not notch config but desktop state; their current value is read from the system
EXTRA_DEFAULTS = {"autostart": os.path.exists(AUTOSTART), "replace_volume_flyout": True,
                  "taskbar_dock": True, "taskbar_dock_size": 150,
                  "notify_endpoint": True, "language": "auto",
                  "alt_tab_style": "ring"}


def _dconf(path, value):
    subprocess.run(["dconf", "write", path, value], capture_output=True)


def apply_system(key, value):
    """The few settings that change the desktop rather than the notch."""
    plank = "/net/launchpad/plank/docks/dock1/"
    if key == "autostart":
        if value:
            src = os.path.join(GLib.get_user_data_dir(), "applications", "opennotch.desktop")
            if os.path.exists(src) and not os.path.exists(AUTOSTART):
                os.makedirs(os.path.dirname(AUTOSTART), exist_ok=True)
                with open(src) as f, open(AUTOSTART, "w") as g:
                    g.write(f.read())
        elif os.path.exists(AUTOSTART):
            os.remove(AUTOSTART)
    elif key == "replace_volume_flyout":
        if "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", ""):  # Plasma's own volume/brightness pop-ups
            subprocess.run(["kwriteconfig5", "--file", "plasmarc", "--group", "OSD", "--key", "Enabled",
                            "false" if value else "true"], capture_output=True)
        else:
            Gio.Settings.new("org.cinnamon").set_boolean("show-media-keys-osd", not value)
    elif key == "custom_taskbar":
        if value:
            subprocess.Popen(["plank"], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.run(["pkill", "-x", "plank"])
    elif key == "taskbar_auto_hide":
        _dconf(plank + "hide-mode", "'dodge-maximized'" if value else "'none'")
    elif key == "taskbar_dock":
        _dconf(plank + "zoom-enabled", "true" if value else "false")
    elif key == "taskbar_dock_size":
        _dconf(plank + "zoom-percent", str(int(value)))


def main():
    Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
    win = Settings()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
    return 0
