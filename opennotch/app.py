"""The notch window: a black pill at the top centre that grows into a card on hover."""
from datetime import datetime, timezone
import json
import math
import os
import shutil
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.request

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango  # noqa: E402

import cairo  # noqa: E402

from . import DATA_DIR, config, design, extras, i18n, protocol, socket_path, system  # noqa: E402
from .activity import ActivityWatch
from .capture import RECORDER_APP, ScreenRecorder, screenshot
from .clipstore import ClipStore  # noqa: E402
from .dbuswatch import Mpris, NotificationMirror
from .privacy import VideoPrivacyWatch
from .windowstate import coverage  # noqa: E402

try:
    gi.require_version("Keybinder", "3.0")
    from gi.repository import Keybinder
except (ValueError, ImportError):
    Keybinder = None

SHOULDER = 8          # concave "ear" radius where the notch meets the top edge
TOAST_W, TOAST_H = 460, 64
HUD_W, HUD_H = 235, 36
ANIM_SECONDS = design.SETTLE_SECONDS  # closing / morphing; growing uses GROW_SECONDS
GROW_SECONDS = design.GROW_SECONDS
CLOSE_DELAY_MS = 260
PASSWORD_HINT = "x-kde-passwordManagerHint"
ICON_GLYPHS = {"ok": "✓", "fail": "✕", "info": "i"}
TAB_TITLES = {"music": "Music", "web": "Web", "overview": "Overview", "controls": "Controls", "clipboard": "Clipboard",
              "shelf": "Shelf", "notifications": "Notifications", "claude": "Ask Claude"}
# each tab gets a card sized to its content, so there is no dead space; the card morphs between them
TAB_SIZES = {"music": (540, 196), "web": (670, 430), "overview": (560, 250), "controls": (580, 282), "clipboard": (400, 196),
             "shelf": (480, 150), "notifications": (480, 150), "claude": (520, 230)}
TAB_ICONS = {"music": "audio-x-generic-symbolic", "web": "web-browser-symbolic", "overview": "x-office-calendar-symbolic",
             "controls": "emblem-system-symbolic", "clipboard": "edit-paste-symbolic",
             "shelf": "folder-symbolic", "notifications": "preferences-system-notifications-symbolic",
             "claude": "user-available-symbolic"}

CSS = """
#notch {{ background: transparent; }}
#notch * {{ color: #f5f5f7; font-size: 12px; font-family: "{font}", "SF Pro Text", sans-serif; font-feature-settings: "tnum"; }}
#notch .card {{ background: #1b1b1d; border-radius: 14px; }}
#notch .bignum {{ font-size: 30px; font-weight: 700; }}
#notch .bigtemp {{ font-size: 30px; font-weight: 500; }}
#notch .small {{ font-size: 10px; font-weight: 600; }}
#notch .mono {{ font-family: "Geist Mono", "Ubuntu Mono", monospace; font-size: 10px; color: rgba(255,255,255,0.75); }}
#notch .today {{ background: rgba(255,255,255,0.22); border-radius: 7px; }}
#notch button.round {{ border-radius: 99px; padding: 3px; min-width: 22px; min-height: 22px; }}
#notch button.round.play {{ background-color: #f5f5f7; background-image: none; }}
#notch button.round.play image {{ color: #0b0b0c; }}
#notch .notefoot {{ color: rgba(255,255,255,0.5); font-size: 11px; }}
#notch frame.tile {{ background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.08); border-radius: 18px; }}
#notch .clipcard {{ background: #1c1c1c; border: 1px solid #777; border-radius: 13px; }}
#notch .clipcard:hover, #notch .clipcard.pinned {{ border-color: #e8e8e8; }}
#notch .cliprow {{ background: #1c1c1c; border-radius: 10px; }}
#notch .cliphead {{ background: #323232; border-radius: 12px 12px 0 0; padding: 3px 7px; }}
#notch .clipfoot {{ padding: 0 5px 3px 7px; }}
#notch button.clipfilter {{ padding: 2px 9px; border-radius: 99px; }}
#notch button.clipfilter:checked {{ background: #e8e8e8; }}
#notch button.clipfilter:checked label {{ color: #151515; }}
#notch button.clipcopy {{ background: transparent; padding: 6px 7px; border-radius: 0; }}
#notch button.clipcopy:hover {{ background: rgba(255,255,255,0.08); }}
#notch frame.tile > border {{ border: none; }}
#notch .tabbar {{ background: transparent; border: none; padding: 0; }}
#notch .label {{ color: rgba(255,255,255,0.55); font-size: 11px; font-weight: 600; }}
#notch .dim, #notch .dim * {{ color: rgba(255,255,255,0.5); font-size: 11px; }}
#notch .title {{ font-size: 15px; font-weight: 700; }}
#notch .big {{ font-size: 44px; font-weight: 300; }}
#notch .pilltext {{ font-size: 11px; font-weight: 600; }}
#notch .rec {{ color: #ff453a; }}
#notch .accent {{ color: {accent}; }}
#notch .green {{ color: #32d74b; }}
#notch button {{ transition: background-color 180ms ease-out, color 180ms ease-out; }}
#notch button {{ background: rgba(255,255,255,0.07); background-image: none; border: none; box-shadow: none;
  border-radius: 10px; padding: 4px 9px; min-height: 0; min-width: 0; outline: none; text-shadow: none; }}
#notch button:hover {{ background: rgba(255,255,255,0.15); }}
#notch button.flat {{ background: transparent; padding: 3px; }}
#notch button.flat:hover {{ background: rgba(255,255,255,0.12); }}
#notch button.tab {{ background: transparent; border-radius: 9px; padding: 4px 14px; }}
#notch button.tab label {{ color: rgba(255,255,255,0.6); font-weight: 600; }}
#notch button.tab:hover {{ background: rgba(255,255,255,0.09); }}
#notch button.tab.active {{ background: rgba(255,255,255,0.16); }}
#notch button.tab.active label, #notch button.tab:hover label {{ color: #ffffff; }}
#notch button.on {{ background: #ff453a; }}
#notch scale {{ padding: 6px 0; min-height: 0; }}
#notch scale trough {{ background: rgba(255,255,255,0.12); border: none; border-radius: 3px; min-height: 5px; }}
#notch scale highlight {{ background: #ffffff; border: none; border-radius: 3px; }}
#notch scale slider {{ background: #ffffff; border: none; box-shadow: none; border-radius: 7px;
  min-width: 0; min-height: 0; margin: 0; padding: 0; }}
#notch scale:disabled highlight {{ background: rgba(255,255,255,0.3); }}
#notch levelbar trough {{ background: rgba(255,255,255,0.10); border: none; border-radius: 3px; min-height: 4px; padding: 0; }}
#notch levelbar block.filled {{ background: {accent}; border: none; border-radius: 3px; }}
#notch levelbar block.empty {{ background: transparent; border: none; }}
#notch entry {{ background: rgba(255,255,255,0.08); border: none; box-shadow: none; border-radius: 9px;
  padding: 4px 8px; min-height: 0; caret-color: {accent}; }}
#notch scrolledwindow, #notch viewport, #notch list, #notch row, #notch stack {{ background: transparent; border: none; }}
#notch row {{ border-radius: 9px; padding: 3px 6px; }}
#notch row:hover {{ background: rgba(255,255,255,0.07); }}
#notch row.bare, #notch row.bare:hover {{ background: transparent; padding: 0; }}
#notch .notecard {{ background: rgba(255,255,255,0.07); border-radius: 14px; margin-bottom: 6px; padding: 10px 12px; }}
#notch .notecard:hover {{ background: rgba(255,255,255,0.08); }}
#notch .apptag {{ color: rgba(255,255,255,0.45); font-size: 10px; font-weight: 600; }}
#notch button.tabicon {{ background: transparent; border-radius: 8px; padding: 3px 6px 7px 6px; }}
#notch button.tabicon image {{ color: rgba(255,255,255,0.55); }}
#notch button.tabicon:hover image, #notch button.tabicon.active image {{ color: #ffffff; }}
#notch button.tabicon.active {{ background-color: transparent; background-image: radial-gradient(circle at 50% 92%, #ffffff 1.6px, transparent 2.2px); }}
#notch .wing {{ font-size: 12px; font-weight: 700; }}
#notch .wingdim {{ font-size: 12px; font-weight: 600; color: rgba(255,255,255,0.7); }}
#notch .song {{ font-size: 18px; font-weight: 800; }}
#notch .bigtime {{ font-size: 34px; font-weight: 300; }}
#notch .temp {{ font-size: 28px; font-weight: 300; }}
#notch .lyric {{ color: rgba(255,255,255,0.38); font-size: 13px; font-weight: 600; }}
#notch .lyric.now {{ color: #ffffff; font-size: 19px; font-weight: 800; }}
#notch button.qtile {{ background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.07); border-radius: 16px; padding: 9px 11px; }}
#notch button.qtile:hover {{ background: rgba(255,255,255,0.12); }}
#notch button.qtile.on {{ background: {accent}; }}
#notch button.qtile.on * {{ color: #0b0b0c; }}  /* accent is white: dark text on lit tiles */
#notch button.seg {{ background: transparent; border-radius: 9px; padding: 4px 10px; }}
#notch button.seg.active {{ background: rgba(255,255,255,0.9); }}
#notch button.seg.active label {{ color: #111111; }}
#notch .segbar {{ background: rgba(255,255,255,0.07); border-radius: 12px; padding: 3px; }}
#notch scale.big {{ padding: 0; }}
#notch scale.big trough {{ background: rgba(255,255,255,0.10); border-radius: 18px; min-width: 58px; }}
#notch scale.big highlight {{ background: rgba(255,255,255,0.92); border-radius: 18px; }}
#notch scale.big slider {{ min-width: 0; min-height: 0; margin: 0; padding: 0; background: transparent; }}
#notch .biglabel {{ color: #6b6b70; font-size: 11px; font-weight: 700; }}
#notch calendar {{ background: transparent; border: none; padding: 0; color: #f4f4f5; }}
#notch calendar.header {{ background: transparent; border: none; }}
#notch calendar.button {{ color: rgba(255,255,255,0.6); background: transparent; border: none; }}
#notch calendar:selected {{ background: {accent}; border-radius: 8px; color: #ffffff; }}
#notch calendar:indeterminate {{ color: rgba(255,255,255,0.25); }}
#notch entry.ask {{ padding: 8px 12px; border-radius: 14px; font-size: 13px; }}
#notch .answer {{ font-size: 13px; }}
#notch .badge {{ background: #ff453a; color: #ffffff; border-radius: 9px; padding: 1px 6px; font-size: 10px; font-weight: 800; }}
#notch .toasticon {{ border-radius: 13px; min-width: 26px; min-height: 26px; font-weight: 800; font-size: 14px; }}
#notch .toasticon.ok {{ background: #32d74b; color: #08200d; }}
#notch .toasticon.fail {{ background: #ff453a; }}
#notch .toasticon.info {{ background: {accent}; }}
"""


def ease_out_back(t, a=0.28):
    """WPF-style BackEase (EaseOut): a light overshoot. Timings follow NotchX (MIT, github.com/Navneet035/NotchX)."""
    u = 1 - t
    return 1 - (u ** 3 - a * u * math.sin(math.pi * u))


def ease_out_cubic(t):
    return 1 - (1 - t) ** 3


def notch_path(cr, x, y, w, h, r):
    """Flat top flush with the screen edge, rounded bottom, small concave shoulders on both top corners."""
    r = max(0.0, min(r, h / 2, w / 2))
    s = min(SHOULDER, h / 2)
    cr.new_path()
    cr.move_to(x - s, y)
    cr.line_to(x + w + s, y)
    cr.arc_negative(x + w + s, y + s, s, -math.pi / 2, -math.pi)
    cr.line_to(x + w, y + h - r)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.line_to(x + r, y + h)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.line_to(x, y + s)
    cr.arc_negative(x - s, y + s, s, 0, -math.pi / 2)
    cr.close_path()


def fmt_time(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}" if seconds >= 3600 \
        else f"{seconds // 60}:{seconds % 60:02d}"


def spawn(*argv):
    """Fire-and-forget helper; GSubprocess reaps the child for us."""
    try:
        Gio.Subprocess.new(list(argv), Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE)
    except GLib.Error as e:
        print("opennotch:", e.message)


def icon_button(icon, tooltip, cb, flat=True, size=Gtk.IconSize.BUTTON):
    b = Gtk.Button.new_from_icon_name(icon, size)
    b.set_tooltip_text(tooltip)
    b.set_relief(Gtk.ReliefStyle.NONE)
    if flat:
        b.get_style_context().add_class("flat")
    b.connect("clicked", lambda *_: cb())
    b.set_can_focus(False)
    return b


def note_icon(note, px):
    """The sending app's icon: its icon path or name, else a name derived from the app, else a bell."""
    spec = (note.get("icon") or "").strip()
    if spec.startswith("file://"):
        spec = spec[7:]
    if spec.startswith("/"):
        try:
            return Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(spec, px, px, True))
        except GLib.Error:
            spec = ""
    theme = Gtk.IconTheme.get_default()
    for name in (spec, note.get("app", "").lower().replace(" ", "-"), "preferences-system-notifications"):
        if name and theme.has_icon(name):
            img = Gtk.Image.new_from_icon_name(name, Gtk.IconSize.DIALOG)
            img.set_pixel_size(px)
            return img
    img = Gtk.Image.new_from_icon_name("preferences-system-notifications-symbolic", Gtk.IconSize.DIALOG)
    img.set_pixel_size(px)
    return img


def time_zone_city():
    """'Europe/Athens' -> 'Athens': a no-network guess for the weather city."""
    try:
        tz = os.path.realpath("/etc/localtime").split("zoneinfo/")[-1]
    except OSError:
        return ""
    return tz.split("/")[-1].replace("_", " ") if "/" in tz else ""


def ago(ts):
    """NotchPixel shows how long ago a notice came ('now', '11m', '2h') rather than a clock time."""
    s = max(0, time.time() - ts)
    return "now" if s < 60 else f"{int(s // 60)}m" if s < 3600 else f"{int(s // 3600)}h" if s < 86400 else f"{int(s // 86400)}d"


def top_panel_height():
    """Height of a Cinnamon panel along the top edge (it swallows clicks there), or 0."""
    try:
        s = Gio.Settings.new("org.cinnamon")
        hidden = {e.split(":")[0] for e in s.get_strv("panels-autohide") if e.endswith(":true")}
        # an auto-hidden panel only covers the top edge while revealed, so it doesn't push the card down
        tops = {e.split(":")[0] for e in s.get_strv("panels-enabled") if e.endswith(":top")} - hidden
        for e in s.get_strv("panels-height"):
            pid, _, h = e.partition(":")
            if pid in tops:
                return int(h)
    except (GLib.Error, ValueError, TypeError):
        pass
    return 0


def tile(child):
    """A soft rounded panel that groups related controls."""
    f = Gtk.Frame(shadow_type=Gtk.ShadowType.NONE)
    f.get_style_context().add_class("tile")
    for side in ("top", "bottom", "start", "end"):
        getattr(child, f"set_margin_{side}")(14)
    f.add(child)
    return f


def panel_head(title, *right):
    """A panel's header: a tracked small-caps title on the left, its actions on the right."""
    head = Gtk.Box(spacing=8)
    head.pack_start(label(title, "label", ellipsize=False), False, False, 0)
    for widget in reversed(right):
        head.pack_end(widget, False, False, 0)
    return head


def empty_state(icon, title, hint):
    """Centred icon, one line, one hint: what a panel shows with nothing in it."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
    box.set_margin_top(18)
    box.set_margin_bottom(18)
    img = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.DND)
    img.get_style_context().add_class("emptyicon")
    box.pack_start(img, False, False, 0)
    box.pack_start(label(title, "stitle", xalign=0.5, ellipsize=False), False, False, 0)
    hint_label = label(hint, "dim", xalign=0.5, ellipsize=False)
    hint_label.set_line_wrap(True)
    hint_label.set_max_width_chars(46)
    hint_label.set_justify(Gtk.Justification.CENTER)
    box.pack_start(hint_label, False, False, 0)
    return box


def fitted_scroller(child, max_height):
    """Scrolls only past max_height; below it the panel is exactly as tall as its content."""
    sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
    sw.set_propagate_natural_height(True)
    sw.set_max_content_height(max_height)
    sw.add(child)
    return sw


def label(text="", css=None, xalign=0.0, ellipsize=True, chars=None):
    lb = Gtk.Label(label=text, xalign=xalign)
    if ellipsize:
        lb.set_ellipsize(3)  # Pango.EllipsizeMode.END
    if chars:
        lb.set_max_width_chars(chars)
    for c in (css or "").split():
        lb.get_style_context().add_class(c)
    return lb


class ArtView(Gtk.DrawingArea):
    """Album art (or a soft placeholder) clipped to a rounded square."""

    def __init__(self, size, radius):
        super().__init__()
        self.size, self.radius, self.pixbuf = size, radius, None
        self.set_size_request(size, size)
        self.set_valign(Gtk.Align.CENTER)
        self.connect("draw", self._draw)

    def set_pixbuf(self, pb):
        self.pixbuf = pb
        self.queue_draw()

    def _draw(self, _w, cr):
        s, r = self.size, self.radius
        cr.save()
        cr.new_path()
        cr.arc(r, r, r, math.pi, 1.5 * math.pi)
        cr.arc(s - r, r, r, 1.5 * math.pi, 2 * math.pi)
        cr.arc(s - r, s - r, r, 0, 0.5 * math.pi)
        cr.arc(r, s - r, r, 0.5 * math.pi, math.pi)
        cr.close_path()
        cr.clip_preserve()
        if self.pixbuf:
            pw, ph = self.pixbuf.get_width(), self.pixbuf.get_height()
            k = max(s / pw, s / ph)
            cr.save()
            cr.translate((s - pw * k) / 2, (s - ph * k) / 2)
            cr.scale(k, k)
            Gdk.cairo_set_source_pixbuf(cr, self.pixbuf, 0, 0)
            cr.paint()
            cr.restore()
        else:
            g = cairo.LinearGradient(0, 0, s, s)
            g.add_color_stop_rgb(0, 0.14, 0.14, 0.16)
            g.add_color_stop_rgb(1, 0.06, 0.06, 0.08)
            cr.set_source(g)
            cr.paint()
            if s >= 40:
                cr.set_source_rgba(1, 1, 1, 0.28)
                cx, cy, u = s * 0.5, s * 0.52, s * 0.16
                cr.set_line_width(max(1.6, s * 0.032))
                cr.set_line_cap(cairo.LINE_CAP_ROUND)
                cr.set_line_join(cairo.LINE_JOIN_ROUND)
                cr.move_to(cx - u * 0.45, cy + u * 0.55)
                cr.line_to(cx - u * 0.45, cy - u * 0.75)
                cr.line_to(cx + u * 0.95, cy - u * 1.05)
                cr.line_to(cx + u * 0.95, cy + u * 0.30)
                cr.stroke()
                for nx, ny in ((cx - u * 0.78, cy + u * 0.65), (cx + u * 0.62, cy + u * 0.40)):
                    cr.arc(nx, ny, max(2.4, u * 0.36), 0, math.tau)
                    cr.fill()
        cr.restore()
        cr.new_path()
        cr.arc(r, r, r, math.pi, 1.5 * math.pi)
        cr.arc(s - r, r, r, 1.5 * math.pi, 2 * math.pi)
        cr.arc(s - r, s - r, r, 0, 0.5 * math.pi)
        cr.arc(r, s - r, r, 0.5 * math.pi, math.pi)
        cr.close_path()
        cr.set_source_rgba(1, 1, 1, 0.14)
        cr.set_line_width(1)
        cr.stroke()


class Equaliser(Gtk.DrawingArea):
    def __init__(self, rgb):
        super().__init__()
        self.rgb, self.phase, self.timer = rgb, 0.0, 0
        self.pixels = True
        self.set_size_request(16, 14)
        self.set_valign(Gtk.Align.CENTER)
        self.connect("draw", self._draw)

    def run(self, on):
        if on and not self.timer:
            self.timer = GLib.timeout_add(90, self._step)  # ~11 fps keeps the pill cheap
        elif not on and self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0
        self.queue_draw()

    def _step(self):
        self.phase += 0.45
        self.queue_draw()
        return True

    def _draw(self, _w, cr):
        # Visualizer=pixels: columns of square pixels instead of smooth bars
        cr.set_source_rgb(*self.rgb)
        for i in range(4):
            amp = 0.25 + 0.75 * abs(math.sin(self.phase * (1 + i * 0.37) + i * 1.7)) if self.timer else 0.25
            if not self.pixels:  # Visualizer=bars: smooth rounded bars
                cr.rectangle(i * 4, 14 - 14 * amp, 2.5, 14 * amp)
                continue
            for j in range(max(1, round(4 * amp))):
                cr.rectangle(i * 4, 14 - (j + 1) * 3.5, 3, 3)
        cr.fill()


class WaveSeek(Gtk.DrawingArea):
    """Apple-style liquid-glass scrub bar: thickens on hover with a floating scrub-time tooltip."""

    def __init__(self, on_seek, reduce_motion=False):
        super().__init__()
        self.on_seek = on_seek
        self.reduce_motion = bool(reduce_motion)
        self.max, self.value, self.phase, self.timer, self.drag = 1.0, 0.0, 0.0, 0, False
        self.comet = True
        self.unknown = False
        self.hovered = False
        self.hover_x = 0.0
        self.hover_t = 0.0
        self._hover_tick = 0
        self._hover_last = 0.0
        self.set_size_request(-1, 30)
        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
            Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.ENTER_NOTIFY_MASK |
            Gdk.EventMask.LEAVE_NOTIFY_MASK
        )
        self.connect("draw", self._draw)
        self.connect("button-press-event", lambda w, e: self._seek(e, True))
        self.connect("motion-notify-event", self._on_motion)
        self.connect("button-release-event", self._on_release)
        self.connect("enter-notify-event", self._on_enter)
        self.connect("leave-notify-event", self._on_leave)
        self.connect("realize", self._on_realize)

    def _on_realize(self, *_):
        win = self.get_window()
        if win is not None:
            win.set_cursor(Gdk.Cursor.new_from_name(self.get_display(), "pointer"))

    def set_range(self, _lo, hi):
        self.unknown = hi <= 0  # live streams and some browser videos report no length
        self.max = max(1.0, hi)
        self.queue_draw()

    def set_value(self, v):
        if not self.drag:
            self.value = v
            self.queue_draw()

    def animate(self, on):
        on = on and not self.comet and not self.reduce_motion
        if on and not self.timer:
            self.timer = GLib.timeout_add(60, self._step)
        elif not on and self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0

    def _step(self):
        self.phase += 0.35
        self.queue_draw()
        return True

    def _start_hover_anim(self):
        target = 1.0 if (self.hovered or self.drag) else 0.0
        if self.reduce_motion:
            self.hover_t = target
            self.queue_draw()
            return
        self._hover_last = time.monotonic()
        if not self._hover_tick:
            self._hover_tick = self.add_tick_callback(self._tick_hover)

    def _tick_hover(self, _w, _clock):
        now = time.monotonic()
        dt = min(0.05, max(0.0, now - self._hover_last))
        self._hover_last = now
        target = 1.0 if (self.hovered or self.drag) else 0.0
        rate = 9.0 if target > self.hover_t else 7.0
        diff = target - self.hover_t
        if abs(diff) < 0.01:
            self.hover_t = target
            self._hover_tick = 0
            self.queue_draw()
            return False
        self.hover_t += diff * min(1.0, dt * rate)
        self.queue_draw()
        return True

    def _on_enter(self, _w, ev):
        self.hovered = True
        self.hover_x = ev.x
        self._start_hover_anim()
        return False

    def _on_leave(self, _w, _ev):
        self.hovered = False
        self._start_hover_anim()
        return False

    def _on_motion(self, _w, ev):
        self.hover_x = ev.x
        if self.drag:
            return self._seek(ev, False)
        if self.hovered:
            self.queue_draw()
        return False

    def _on_release(self, _w, _ev):
        self.drag = False
        self._start_hover_anim()
        return False

    def _seek(self, ev, start):
        if not self.get_sensitive():
            return False
        self.drag = self.drag or start
        self.hover_x = ev.x
        w = self.get_allocated_width()
        pad = 2.0
        frac = max(0.0, min(1.0, (ev.x - pad) / max(1.0, w - 2 * pad)))
        self.value = frac * self.max
        self._start_hover_anim()
        self.queue_draw()
        self.on_seek(self.value)
        return True

    @staticmethod
    def _pill(cr, x, y, w, h, r=None):
        if w <= 0 or h <= 0:
            return
        rr = min(h / 2.0, w / 2.0) if r is None else min(r, h / 2.0, w / 2.0)
        cr.new_path()
        cr.arc(x + w - rr, y + rr, rr, -math.pi / 2, 0)
        cr.arc(x + w - rr, y + h - rr, rr, 0, math.pi / 2)
        cr.arc(x + rr, y + h - rr, rr, math.pi / 2, math.pi)
        cr.arc(x + rr, y + rr, rr, math.pi, 1.5 * math.pi)
        cr.close_path()

    def _draw(self, _w, cr):
        w, h = self.get_allocated_width(), self.get_allocated_height()
        if w < 12:
            return
        pad = 2.0
        span = w - 2 * pad
        ht = self.hover_t if (self.get_sensitive() and not self.unknown) else 0.0
        bar_h = 6.0 + 4.0 * ht  # 6 px resting -> 10 px hovered/dragging
        cy = h - 7.5            # bar anchored in lower half so tooltip sits cleanly above
        by = cy - bar_h / 2.0

        # Frosted liquid-glass capsule track
        self._pill(cr, pad, by, span, bar_h)
        cr.set_source_rgba(1, 1, 1, 0.14 + 0.08 * ht)
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, 0.16 + 0.08 * ht)
        cr.set_line_width(0.8)
        cr.stroke()

        frac = 0.0 if self.unknown else max(0.0, min(1.0, self.value / self.max))
        fill_w = span * frac

        if self.unknown:
            cr.set_source_rgba(1, 1, 1, 0.75)
            cr.arc(pad + bar_h / 2.0, cy, bar_h * 0.38, 0, math.tau)
            cr.fill()
            return

        # Played fill clipped cleanly inside the glass track capsule
        if fill_w > 0.5:
            cr.save()
            self._pill(cr, pad, by, span, bar_h)
            cr.clip()
            if self.comet:
                fw = max(bar_h, fill_w) if frac > 0.001 else 0.0
                self._pill(cr, pad, by, min(span, fw), bar_h)
                g = cairo.LinearGradient(pad, by, pad, by + bar_h)
                g.add_color_stop_rgba(0, 1, 1, 1, 0.98)
                g.add_color_stop_rgba(1, 1, 1, 1, 0.84 + 0.12 * ht)
                cr.set_source(g)
                cr.fill()
                # subtle specular highlight along top edge of the played bar
                cr.set_source_rgba(1, 1, 1, 0.35)
                cr.set_line_width(1.0)
                cr.move_to(pad + bar_h / 2, by + 0.8)
                cr.line_to(min(pad + span - bar_h / 2, pad + fill_w), by + 0.8)
                cr.stroke()
            else:
                cr.set_line_cap(cairo.LINE_CAP_ROUND)
                cr.set_line_width(max(2.6, bar_h * 0.42))
                cr.set_source_rgba(1, 1, 1, 0.95)
                cr.move_to(pad, cy)
                x = pad
                x_end = pad + fill_w
                while x <= x_end:
                    cr.line_to(x, cy + (bar_h * 0.28) * math.sin(x / 5.0 - self.phase))
                    x += 1.5
                cr.stroke()
            cr.restore()

        # Subtle hover scrub hairline + floating scrub-time pill tooltip
        if ht > 0.05 and self.get_sensitive():
            hx = max(pad, min(pad + span, self.hover_x))
            h_frac = (hx - pad) / max(1.0, span)
            h_sec = h_frac * self.max
            # faint hairline inside track at hovered position
            cr.set_source_rgba(1, 1, 1, 0.55 * ht)
            cr.set_line_width(1.2)
            cr.move_to(hx, by + 1.0)
            cr.line_to(hx, by + bar_h - 1.0)
            cr.stroke()
            # floating time pill directly above hover_x
            txt = fmt_time(h_sec)
            cr.select_font_face("SF Pro Text", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(10.5)
            ext = cr.text_extents(txt)
            pw, ph = ext.width + 12.0, 15.0
            px = max(pad, min(w - pad - pw, hx - pw / 2.0))
            py = max(0.0, by - ph - 3.5)
            self._pill(cr, px, py, pw, ph, r=7.5)
            cr.set_source_rgba(0.10, 0.10, 0.12, 0.92 * ht)
            cr.fill_preserve()
            cr.set_source_rgba(1, 1, 1, 0.22 * ht)
            cr.set_line_width(0.8)
            cr.stroke()
            cr.set_source_rgba(1, 1, 1, 0.95 * ht)
            cr.move_to(px + (pw - ext.width) / 2.0 - ext.x_bearing, py + (ph + ext.height) / 2.0 - 0.5)
            cr.show_text(txt)


def dominant_rgb(pb):
    """A vivid version of the image's average colour, for tinting the card behind album art."""
    if pb is None:
        return None
    small = pb.scale_simple(6, 6, GdkPixbuf.InterpType.BILINEAR)
    data, n, stride = small.get_pixels(), small.get_n_channels(), small.get_rowstride()
    best, score = None, -1.0
    for y in range(6):
        for x in range(6):
            i = y * stride + x * n
            r, g, b = data[i] / 255, data[i + 1] / 255, data[i + 2] / 255
            sat = max(r, g, b) - min(r, g, b)
            sc = sat * 2 + max(r, g, b)  # prefer colourful, then bright
            if sc > score:
                best, score = (r, g, b), sc
    r, g, b = best
    top = max(r, g, b) or 1
    return tuple(min(1.0, c / top * 0.85) for c in (r, g, b))  # normalise brightness so dark art still glows


class Notch(Gtk.Window):
    def __init__(self, cfg):
        super().__init__(title="OpenNotch")
        self._start_socket()  # first: a second copy exits before grabbing the hotkey or the bus
        self.cfg = cfg
        i18n.setup(cfg["language"])
        self.loaded_cfg = cfg.copy()
        self.accent = Gdk.RGBA()
        self.accent.parse(cfg["accent"])
        self.set_name("notch")

        # ---- window flags: never steals focus, never in the taskbar, on every workspace ----
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_keep_above(True)
        self.stick()
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.DOCK)
        self.set_accept_focus(False)
        self.set_focus_on_map(False)

        self.scale = cfg["size"] / 100
        self.card_scale = self.scale * cfg["open_size"] / 100
        pw = self.scaled(cfg["pill_width"])
        ph = self.scaled(cfg["pill_height"])
        self.panel_h = 0 if extras.KDE else top_panel_height()
        cw = self.scaled(max(w for w, _ in TAB_SIZES.values()), card=True)
        ch = self.scaled(max(h for _, h in TAB_SIZES.values()), card=True) + self.panel_h
        self.kwin_blur = None
        self.live_glass = False
        self.glass = None  # blurred copy of what is behind the card, taken each time it opens
        self.radius = round(4 + cfg["corner_pct"] * 0.18)
        self.floating = cfg["shape"] == "island"
        self.gap = cfg["top_gap"] if self.floating else 0
        self.position, _, edge = cfg["position"].partition("_")
        self.side = edge == "side"
        self.top = 0 if self.side else self.gap
        self.shoulder = 0 if self.floating else SHOULDER
        self.side_center = 0
        self.inset = self.gap if self.side else self.shoulder
        if not self.side and self.position != "center":
            self.inset += cfg["edge_margin"]
        if self.side:
            pw, ph = ph, pw
        self.geo = {"pill": (pw, ph, min(self.scaled(self.radius), ph / 2)),
                    "toast": self.toast_size(),
                    "card": (cw, ch, self.scaled(self.radius, card=True))}
        # room for the opening overshoot so the bounce is never clipped
        self.W = math.ceil(max(cw, self.geo["toast"][0], pw) * 1.08) + 2 * self.inset
        self.H = math.ceil(max(ch, self.geo["toast"][1], ph) * 1.08) + self.top
        if self.side:
            self.H += 2 * self.shoulder
        self.set_size_request(self.W, self.H)
        self._place_window()
        self.get_screen().connect("monitors-changed", lambda *_: self._place_window())

        self.state = "pill"
        self.cur = list(self.geo["pill"])
        self.anim = None          # (start_geo, start_time, ease)
        self.anim_tick = 0
        self.frame_at = 0
        self.slim = self.fullscreen_hidden = self.game_strip = False
        self.open_timer = self.close_timer = self.toast_timer = 0
        self.dragging = False
        self.toasts = []
        self.toast_showing = False
        self.weather_listeners = []  # builders register here, so it exists before them

        self.connect("draw", self._draw)
        self.connect("enter-notify-event", self._on_enter)
        self.connect("leave-notify-event", self._on_leave)
        self.connect("realize", self._realize_notch)
        self.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK |
                        Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.connect("scroll-event", self._on_scroll)
        self.scroll_acc = 0.0
        # Cinnamon's panel takes pointer input over its strip, so enter/leave never fire there; poll instead
        GLib.timeout_add(120, self._poll_hover)

        provider = Gtk.CssProvider()
        css = CSS.format(accent=cfg["accent"], font=cfg["font"]) + design.island_css(cfg["font"]) + design.type_css()
        if cfg["higher_contrast"]:
            css = re.sub(r"(rgba\(255,255,255,)0\.(?:38|45|5|55|6)\)", r"\g<1>0.82)", css)
        font_rules = re.findall(r"([^{}]+)\{[^{}]*font-size: (\d+)px", css)
        for face, factor in (("pill", self.scale), ("toast", self.scale), ("card", self.card_scale)):
            for selectors, pixels in font_rules:
                scoped = ",".join(sel.replace("#notch ", f"#notch #island-{face} ", 1)
                                  for sel in selectors.split(","))
                css += f"{scoped} {{ font-size: {int(pixels) * factor:.2f}px; }}"
        provider.load_from_data(css.encode())
        Gtk.StyleContext.add_provider_for_screen(self.get_screen(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        # ---- the three faces, one visible at a time ----
        align = {"left": Gtk.Align.START, "center": Gtk.Align.CENTER, "right": Gtk.Align.END}
        self.views = Gtk.Stack(hhomogeneous=False, vhomogeneous=False, halign=align[self.position],
                               valign=Gtk.Align.START)
        self.views.set_direction(Gtk.TextDirection.LTR)
        for face, build in (("pill", self._build_pill), ("toast", self._build_toast), ("card", self._build_card)):
            widget = build()
            widget.set_name(f"island-{face}")
            self.views.add_named(widget, face)
        if self.position == "left":
            self.views.set_margin_start(self.inset)
        elif self.position == "right":
            self.views.set_margin_end(self.inset)
        self.views.add_named(Gtk.Box(), "none")
        pw, ph, _ = self.geo["pill"]
        game = self.game_box = Gtk.Box(halign=Gtk.Align.CENTER)
        game.set_size_request(pw, ph)
        self.game_label = label("", "wing", xalign=0.5, ellipsize=False)
        self.game_label.set_justify(Gtk.Justification.CENTER)
        game.set_center_widget(self.game_label)
        self.views.add_named(game, "game")
        self._position_views()
        self.add(self.views)

        # ---- state & services ----
        os.makedirs(DATA_DIR, exist_ok=True)
        self.clips = ClipStore(os.path.join(DATA_DIR, "clipboard.json"), limit=cfg["clipboard_size"],
                               keep_hours=cfg["clipboard_hours"])
        self.clips_dirty = True
        self.shelf_path = os.path.join(DATA_DIR, "shelf.json")
        self.shelf = self._load_shelf()
        self.share_dialog = None
        self.notes, self.unread = [], 0
        self.recording_since = None
        self.recorder = ScreenRecorder(self._recording_changed)
        self.video_privacy = set()
        self.obs = None
        self.twitch = None
        self.youtube = None
        self.previews = None
        self.dock_bg = None
        self.card_pet = None
        self.roaming_pet = None
        self.pet_idle_clock = None
        self.pet_health = None
        self._high_load_since = None
        self._pet_health_timer = 0
        self.live_wallpaper = None
        self.studio_state = None
        self.meeting = None
        self.calendar_loading = False
        self.capture_timer = 0
        self.call_timer = 0
        self.stats_timer = self.game_timer = self.notes_timer = 0
        self.cpu = system.CpuMeter()
        self.position_us = 0
        self.art_url, self.art_cache = None, {}
        self.last_user_volume = 0.0
        self.pomo = {"phase": "focus", "left": cfg["focus_minutes"] * 60, "running": False, "timer": 0}
        self.art_rgb = None
        self.weather = None
        self.lyrics, self.lyrics_key, self.lyrics_timer = [], None, 0
        self.claude_proc = None
        self.osd_active, self.last_sink, self.last_bright = False, None, extras.get_brightness()
        self.toggle_state = {}

        self.clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        if self.cfg["clipboard_enabled"]:
            self.clipboard.connect("owner-change", self._on_clipboard)

        try:
            self.mpris = Mpris(self._on_music)
        except GLib.Error as e:
            print("opennotch: MPRIS unavailable:", e.message)
            self.mpris = None
        try:
            if not self.cfg["mirror_notifications"]:
                raise GLib.Error("turned off in Settings")
            self.mirror = NotificationMirror(self._on_notification)
        except GLib.Error as e:
            print("opennotch: notification mirror unavailable:", e.message)
            self.mirror = None

        self._setup_dnd()
        self._start_pactl_watch()
        self._check_recording()
        if cfg["obs_enabled"]:
            from .obslink import ObsLink

            self.obs = ObsLink(self._obs_status, password=cfg["obs_password"], port=cfg["obs_port"])
            self.obs.start()
        if cfg["chat_twitch"]:
            from .twitchchat import TwitchChat

            self.twitch = TwitchChat(cfg["chat_twitch"], self._on_chat_message)
            self.twitch.start()
        if cfg["chat_youtube"]:
            from .youtubechat import YouTubeChat

            self.youtube = YouTubeChat(cfg["chat_youtube"], self._on_chat_message)
            self.youtube.start()
        if cfg["custom_taskbar"] and cfg["taskbar_previews"]:
            from .previews import DockPreviews

            self.previews = DockPreviews(cfg["font"])
            self.previews.start()
        if (cfg["meeting_countdown"] or cfg["show_upnext_widget"]) and cfg["calendar_file"]:
            self._refresh_calendar()
            GLib.timeout_add_seconds(60, self._refresh_calendar)
        self._bind_hotkey()
        self.reload_timer = 0
        self._watch_config()
        self._watch_brightness()
        self.activity_watch = ActivityWatch(self.cfg, self._show_activity)
        if cfg["show_privacy_indicator"]:
            self.privacy_watch = VideoPrivacyWatch(self._set_video_privacy)
        if cfg["resting"] == "pet":
            from .pet import IdleClock

            self.pet_idle_clock = IdleClock()
            self._pet_health_timer = GLib.timeout_add_seconds(5, self._poll_pet_health)
        self._tick_clock()
        GLib.timeout_add_seconds(15, self._tick_clock)
        self._refresh_weather()
        GLib.timeout_add_seconds(15 * 60, self._refresh_weather)

        self.views.set_visible_child_name("none" if self.cfg["hidden_until_hover"] else "pill")
        self._on_music()
        self._refresh_shelf()
        self._update_pill()
        self._update_pomo()

    def scaled(self, value, card=False):
        return round(value * (self.card_scale if card else self.scale))

    def toast_size(self, compact=False):
        w, h = (HUD_W, HUD_H) if compact else (TOAST_W, TOAST_H)
        return self.scaled(w), self.scaled(h), self.scaled(self.radius)

    def _place_window(self):
        display = self.get_display()
        monitor = getattr(self, "monitor", None)
        available = [display.get_monitor(i) for i in range(display.get_n_monitors())]
        if not self.cfg["all_monitors"] or monitor is None or monitor not in available:
            self.monitor = display.get_primary_monitor() or display.get_monitor(0)
        if self.monitor:
            screen = self.monitor.get_geometry()
            limits = min(self.W, screen.width), min(self.H, screen.height)
            if limits != (self.W, self.H):
                self.W, self.H = limits
                self.set_size_request(self.W, self.H)
                self.resize(self.W, self.H)
            x = {"left": 0, "center": (screen.width - self.W) // 2, "right": screen.width - self.W}
            y = 0
            if self.side:
                target = round(screen.height * self.cfg["side_position"] / 100)
                y = max(0, min(screen.height - self.H, target - self.H // 2))
                self.side_center = target - y
            self.window_origin = (screen.x + x[self.position], screen.y + y)
            self.move(*self.window_origin)
            if hasattr(self, "views"):
                self._position_views()
                self._set_input_shape(self.cur)

    def _transfer_to_monitor(self, monitor):
        self._cancel("open_timer")
        self._cancel("close_timer")
        self.monitor = monitor
        self.set_accept_focus(False)
        self._place_window()
        self._update_coverage()
        if self.state == "card":
            self._fit_card(self.pages.get_visible_child_name())
            self.cur = list(self.geo["card"])
            if self.cfg["surface"] == "glass" and not self.live_glass:
                self._capture_glass()
            self._set_input_shape(self.cur)
            self.queue_draw()
        else:
            self._open_now()

    def _replica_summary(self):
        if self._capture_status_visible():
            return self.pill_capture.get_text()
        if self.pomo["running"]:
            return self.pill_pomo.get_text()
        if self.pill_meeting.get_visible():
            return self.pill_meeting.get_text()
        if self.recording_since is not None and self.cfg["show_call_activity"]:
            return "● " + self.pill_call.get_text()
        if self.cfg["resting"] == "clock":
            return "   ".join(text for text in (self.pill_time.get_text(), self.pill_temp.get_text()) if text)
        if self.unread:
            return f"{self.unread} notices"
        if self._playing():
            return "♫"
        return ""

    def _face_y(self, height):
        if not self.side:
            return self.top
        return max(self.shoulder, min(self.H - self.shoulder - height, self.side_center - height / 2))

    def _position_views(self):
        self.views.set_margin_top(round(self._face_y(self.geo[self.state][1])))

    def _face_x(self, width):
        if self.position == "left":
            return self.inset
        if self.position == "right":
            return self.W - width - self.inset
        return (self.W - width) / 2

    def _resting_face(self):
        if self._capture_status_visible():
            return "pill"
        if self.game_strip:
            return "game"
        return "none" if self.cfg["hidden_until_hover"] or self.slim or self.fullscreen_hidden else "pill"

    def _hide_surface(self):
        return not self._capture_status_visible() and (
            self.fullscreen_hidden or self.state == "pill" and self.cfg["hidden_until_hover"]
        )

    def _use_slim_strip(self):
        return self.state == "pill" and self.slim and not self._capture_status_visible()

    def _edge_strip(self, geo):
        w, h, r = geo
        thickness = max(3, self.scaled(3))
        return (thickness, h, min(r, thickness / 2)) if self.side else (w, thickness, min(r, thickness / 2))

    def _update_coverage(self):
        if not (self.cfg["slim_strip"] or self.cfg["hide_in_fullscreen"] or self.cfg["game_strip_fullscreen"]):
            return
        maximized, fullscreen = coverage(self.monitor)
        game = self.cfg["game_strip_fullscreen"] and fullscreen  # the strip replaces hiding and the slim edge
        slim = self.cfg["slim_strip"] and (maximized or fullscreen) and not game
        hidden = self.cfg["hide_in_fullscreen"] and fullscreen and not game
        if (slim, hidden, game) == (self.slim, self.fullscreen_hidden, self.game_strip):
            return
        self.slim, self.fullscreen_hidden = slim, hidden
        if game != self.game_strip:
            self.game_strip = game
            self._cancel("game_timer")
            if game:
                self.game_label.set_text(("\n" if self.side else "   ").join(("CPU 100%", "GPU 100%", "RAM 100%")))
                self.game_size, _ = self.game_label.get_preferred_size()  # widest reading: the pill keeps this size
                self._update_pill()
                self.game_box.set_size_request(*map(int, self.geo["pill"][:2]))
                self._tick_game()
                self.game_timer = GLib.timeout_add_seconds(1, self._tick_game)
            else:
                self._update_pill()
        if hidden and self.state == "card":
            self._go("pill")
        if self.state == "pill" and not self.anim:
            self.views.set_visible_child_name(self._resting_face())
        self._set_input_shape(self.cur)
        self.queue_draw()

    # ======================================================================= faces
    def _build_pill(self):
        pw, ph, _ = self.geo["pill"]
        box = self.pill_box = Gtk.Box(spacing=self.scaled(7))
        pad = max(self.scaled(12), int(ph / 2) - 2)
        if self.side:
            box.set_orientation(Gtk.Orientation.VERTICAL)
            box.set_halign(Gtk.Align.CENTER)
            box.set_size_request(pw, ph)
        else:
            box.set_size_request(pw - 2 * pad, ph)
            box.set_margin_start(pad)
            box.set_margin_end(pad)
        self.pill_time = label("", "wing", ellipsize=False)
        self.pill_wicon = Gtk.Image()
        self.pill_temp = label("", "wingdim", ellipsize=False)
        self.pill_art = ArtView(max(14, ph - 14), 4)
        a = self.accent
        self.pill_eq = Equaliser((a.red, a.green, a.blue))
        self.pill_eq.pixels = self.cfg["visualizer"] == "pixels"
        center = Gtk.Box(spacing=6)
        center.pack_start(self.pill_art, False, False, 0)
        center.pack_start(self.pill_eq, False, False, 0)
        self.pill_pet = None
        if self.cfg["resting"] == "pet":
            from .pet import IdlePet

            size = max(8, min(self.scaled(22), (pw if self.side else ph) - 4))
            self.pill_pet = IdlePet(self.cfg["pet"], size=size, vertical=self.side,
                                   reduce_motion=self.cfg["reduce_motion"], on_click=self._on_pet_click)
            self.pill_pet.set_no_show_all(True)
            center.pack_start(self.pill_pet, False, False, 0)
        box.set_center_widget(center)
        self.pill_rec = label("●", "rec pilltext", ellipsize=False)
        self.pill_capture = label("", "pilltext", ellipsize=False)
        self.pill_meeting = label("", "pilltext", ellipsize=False)
        self.pill_call = label("", "rec pilltext", ellipsize=False)
        self.pill_mic = Gtk.Image.new_from_icon_name("microphone-sensitivity-muted-symbolic", Gtk.IconSize.MENU)
        self.pill_pomo = label("", "accent pilltext", ellipsize=False)
        self.pill_badge = label("", "badge", ellipsize=False, xalign=0.5)
        self.pill_badge.set_valign(Gtk.Align.CENTER)
        if self.side:
            for text in (self.pill_time, self.pill_temp, self.pill_call, self.pill_pomo, self.pill_capture, self.pill_meeting):
                text.set_angle(90 if self.position == "left" else 270)
            center.set_orientation(Gtk.Orientation.VERTICAL)
        self.pill_batt = label("", "wingdim", ellipsize=False)
        self.pill_bicon = Gtk.Image()
        if self.side:
            self.pill_batt.set_angle(90 if self.position == "left" else 270)
        for w in (self.pill_batt, self.pill_bicon):
            w.set_no_show_all(self.cfg["resting"] != "clock")
        for w in (self.pill_time, self.pill_wicon, self.pill_temp):
            box.pack_start(w, False, False, 0)
            w.set_no_show_all(self.cfg["resting"] != "clock")
        for w in (self.pill_batt, self.pill_bicon, self.pill_badge, self.pill_pomo, self.pill_call, self.pill_rec,
                  self.pill_mic, self.pill_capture, self.pill_meeting):
            box.pack_end(w, False, False, 0)
        box.show_all()
        return box

    def _build_toast(self):
        box = self.toast_box = Gtk.Box(spacing=self.scaled(12))
        box.set_margin_start(self.scaled(16))
        box.set_margin_end(self.scaled(16))
        self._fit_toast()
        self.toast_icon = label("i", "toasticon info", xalign=0.5, ellipsize=False)
        self.toast_icon.set_valign(Gtk.Align.CENTER)
        self.toast_img = Gtk.Box(valign=Gtk.Align.CENTER)  # holds the sending app's icon for notifications
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1, valign=Gtk.Align.CENTER)
        self.toast_dot = label("●", "small")
        self.toast_dot.set_no_show_all(True)
        self.toast_text = label("", "title")
        self.toast_sub = label("", "dim")
        self.toast_bar = Gtk.LevelBar(min_value=0, max_value=100)
        for off in (Gtk.LEVEL_BAR_OFFSET_LOW, Gtk.LEVEL_BAR_OFFSET_HIGH, "full"):
            self.toast_bar.remove_offset_value(off)
        texts.pack_start(self.toast_text, False, False, 0)
        texts.pack_start(self.toast_sub, False, False, 0)
        texts.pack_start(self.toast_bar, False, False, 0)
        box.pack_start(self.toast_icon, False, False, 0)
        box.pack_start(self.toast_img, False, False, 0)
        box.pack_start(texts, True, True, 0)
        box.pack_end(self.toast_dot, False, False, 0)
        box.show_all()
        return box

    def _fit_toast(self, compact=False):
        w, h, r = self.geo["toast"] = self.toast_size(compact)
        margins = self.toast_box.get_margin_start() + self.toast_box.get_margin_end()
        self.toast_box.set_size_request(w - margins, h)

    def _build_card(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=self.scaled(8, card=True))
        self.card_margins = {"top": self.scaled(6, card=True) + (0 if self.side else self.panel_h),
                             "bottom": self.scaled(12, card=True),
                             "start": self.scaled(12, card=True), "end": self.scaled(12, card=True)}
        for side, m in self.card_margins.items():
            getattr(outer, f"set_margin_{side}")(m)
        self.card_box = outer
        outer.connect("size-allocate", self._check_card_fit)

        tabs = Gtk.Box(spacing=2, halign=Gtk.Align.CENTER)
        tabs.get_style_context().add_class("tabbar")
        self.tab_buttons = {}
        transition = (Gtk.StackTransitionType.CROSSFADE if self.cfg["reduce_motion"]
                      else Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.pages = Gtk.Stack(transition_type=transition, transition_duration=240,
                               hhomogeneous=False, vhomogeneous=False, interpolate_size=True)
        builders = {"clipboard": self._build_clipboard, "shelf": self._build_shelf,
                    "notifications": self._build_notifications}
        builders.update({"music": self._build_music, "overview": self._build_overview,
                         "controls": self._build_controls, "claude": self._build_claude, "web": self._build_web})
        off = {"notifications": not self.cfg["notifications_panel"], "shelf": not self.cfg["shelf_enabled"],
               "clipboard": not self.cfg["clipboard_enabled"], "controls": not self.cfg["controls_panel"],
               "claude": not self.cfg["ask_claude"], "web": not self.cfg["web_panel"]}
        requested = self.cfg["tabs"]
        tabs_wanted = [t for t in config.TABS if (t in requested or t == "web") and not off.get(t)]
        if not tabs_wanted:
            tabs_wanted = ["music"]
        for name in tabs_wanted:
            b = Gtk.Button.new_from_icon_name(TAB_ICONS[name], Gtk.IconSize.BUTTON)
            b.set_tooltip_text(TAB_TITLES[name])
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.set_can_focus(False)
            b.get_style_context().add_class("tabicon")
            b.get_style_context().add_class(f"t-{name}")
            b.connect("clicked", lambda _b, n=name: self._show_tab(n))
            tabs.pack_start(b, False, False, 0)
            self.tab_buttons[name] = b
            self.pages.add_named(builders[name](), name)
        self.pages.connect("notify::visible-child-name", lambda *_: self._on_tab_changed())
        gear = Gtk.Button.new_from_icon_name("emblem-system-symbolic", Gtk.IconSize.BUTTON)
        gear.set_tooltip_text("Settings")
        gear.set_relief(Gtk.ReliefStyle.NONE)
        gear.set_can_focus(False)
        gear.get_style_context().add_class("tabicon")
        gear.connect("clicked", lambda *_: spawn(sys.executable, "-m", "opennotch", "settings"))
        tabs.pack_start(gear, False, False, 6)
        self.card_privacy = label("●", "small", xalign=0.5, ellipsize=False)
        self.card_privacy.set_no_show_all(True)
        tabs.pack_end(self.card_privacy, False, False, 3)
        self.tab_row = tabs
        if self.cfg["resting"] == "pet":
            from .pet import IdlePet

            row = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
            peek = IdlePet(self.cfg["pet"], size=self.scaled(26, card=True),
                           reduce_motion=self.cfg["reduce_motion"], on_click=self._on_pet_click)
            peek.set_valign(Gtk.Align.CENTER)
            self.card_pet = peek
            row.pack_start(peek, False, False, 0)
            row.pack_start(tabs, False, False, 0)
            outer.pack_start(row, False, False, 0)
            self.tab_header = row
        else:
            outer.pack_start(tabs, False, False, 0)
            self.tab_header = tabs
        outer.pack_start(self.pages, True, True, 0)
        outer.show_all()
        self._mark_tab(tabs_wanted[0])
        self._fit_card(tabs_wanted[0])
        return outer

    def _grow_window_for(self, w, h):
        need_w = math.ceil(w * 1.08) + 2 * self.inset
        need_h = math.ceil(h * 1.08) + self.top + (2 * self.shoulder if self.side else 0)
        if self.monitor is not None:
            screen = self.monitor.get_geometry()
            need_w, need_h = min(need_w, screen.width), min(need_h, screen.height)
        if need_w > self.W or need_h > self.H:
            self.W, self.H = max(self.W, need_w), max(self.H, need_h)
            self.set_size_request(self.W, self.H)
            self._place_window()

    def _card_size(self, name):
        w, h = TAB_SIZES.get(name, (560, 300))
        return self.scaled(w, card=True), self.scaled(h, card=True) + self.panel_h

    def _fit_card(self, name, at_least=(0, 0)):
        """Size the content box (and the card target) for one tab. Margins add to a size request, so subtract them.
        The card is never smaller than what the page really needs, so content can't spill past the glass."""
        w, h = self._card_size(name)
        m = self.card_margins
        page = self.pages.get_child_by_name(name)
        if page:
            nat = page.get_preferred_size()[1]
            header = getattr(self, "tab_header", self.tab_row).get_preferred_size()[1]
            tabs_h = header.height + self.card_box.get_spacing()
            # the card is never narrower than its tab bar (pet + tab blobs), or the tabs spill past the edge
            w = max(w, nat.width + m["start"] + m["end"], header.width + m["start"] + m["end"], at_least[0])
            h = max(h, nat.height + tabs_h + m["top"] + m["bottom"], at_least[1])
        if name == "web" and self.monitor is not None:
            screen = self.monitor.get_geometry()
            w = min(w, int((screen.width - 2 * self.inset) / 1.08))
            edge_space = self.top + (2 * self.shoulder if self.side else 0)
            h = min(h, int((screen.height - edge_space) / 1.08))
        self.card_box.set_size_request(max(1, w - m["start"] - m["end"]), max(1, h - m["top"] - m["bottom"]))
        self.geo["card"] = (w, h, self.scaled(self.radius + 4, card=True))  # the open card is rounder than the pill
        if hasattr(self, "views"):
            self._position_views()
        if hasattr(self, "W"):
            self._grow_window_for(w, h)

    # ---- Music (player, or synced lyrics)
    def _build_music(self):
        self.music_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=160)
        player = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, valign=Gtk.Align.CENTER)

        # Header row: compact rounded art + title/artist/album + live equalizer
        head_row = Gtk.Box(spacing=12, valign=Gtk.Align.CENTER)
        self.art = ArtView(68, 14)
        head_row.pack_start(self.art, False, False, 0)
        meta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER)
        self.m_title = label("Nothing playing", "song", chars=28)
        self.m_artist = label("Start a player to see it here", "dim", chars=36)
        self.m_album = label("", "dim", chars=36)
        self.m_album.set_no_show_all(True)
        for w in (self.m_title, self.m_artist, self.m_album):
            meta.pack_start(w, False, False, 0)
        head_row.pack_start(meta, True, True, 0)
        self.card_eq = Equaliser((1.0, 1.0, 1.0))
        self.card_eq.pixels = self.cfg["visualizer"] == "pixels"
        self.card_eq.set_valign(Gtk.Align.CENTER)
        head_row.pack_end(self.card_eq, False, False, 4)

        # Full-width Apple-style liquid-glass scrub bar + tabular time labels
        scrub = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.seek = WaveSeek(self._on_seek_value, reduce_motion=self.cfg["reduce_motion"])
        self.seek.comet = self.cfg["progress"] == "comet"
        times = Gtk.Box()
        self.m_pos, self.m_len = label("0:00", "time", ellipsize=False), label("0:00", "time", ellipsize=False, xalign=1)
        times.pack_start(self.m_pos, True, True, 0)
        times.pack_end(self.m_len, True, True, 0)
        scrub.pack_start(self.seek, False, False, 0)
        scrub.pack_start(times, False, False, 0)

        # Centered transport row + right-aligned Lyrics glass chip
        ctrls = Gtk.Box(valign=Gtk.Align.CENTER)
        transport = Gtk.Box(spacing=14, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.b_play = icon_button("media-playback-start-symbolic", "Play / pause",
                                  lambda: self.mpris and self.mpris.call("PlayPause"), flat=False,
                                  size=Gtk.IconSize.LARGE_TOOLBAR)
        for cls in ("round", "play", "bigplay"):
            self.b_play.get_style_context().add_class(cls)
        for icon, tip, method in (("media-skip-backward-symbolic", "Previous", "Previous"), (None, None, None),
                                  ("media-skip-forward-symbolic", "Next", "Next")):
            if icon is None:
                transport.pack_start(self.b_play, False, False, 0)
                continue
            b = icon_button(icon, tip, lambda m=method: self.mpris and self.mpris.call(m), size=Gtk.IconSize.BUTTON)
            b.get_style_context().add_class("transport")
            b.set_valign(Gtk.Align.CENTER)
            transport.pack_start(b, False, False, 0)
        ctrls.set_center_widget(transport)
        if self.cfg["lyrics"]:
            lyr = Gtk.Button(label="Lyrics")
            lyr.get_style_context().add_class("chip")
            lyr.set_valign(Gtk.Align.CENTER)
            lyr.set_can_focus(False)
            lyr.set_tooltip_text("Synced lyrics from LRCLIB (sends the song's title and artist)")
            lyr.connect("clicked", lambda *_: self._show_lyrics(True))
            ctrls.pack_end(lyr, False, False, 0)

        for w in (head_row, scrub, ctrls):
            player.pack_start(w, False, False, 0)
        self.music_stack.add_named(player, "player")

        lyr_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, valign=Gtk.Align.CENTER)
        head = Gtk.Box()
        self.ly_head = label("", "dim")
        head.pack_start(self.ly_head, True, True, 0)
        back = Gtk.Button(label="Player")
        back.set_can_focus(False)
        back.connect("clicked", lambda *_: self._show_lyrics(False))
        head.pack_end(back, False, False, 0)
        lyr_box.pack_start(head, False, False, 0)
        self.ly_lines = []
        for css in ("lyric", "lyric", "lyric now", "lyric", "lyric"):
            lb = label("", css, xalign=0.5)
            lb.set_line_wrap(True)
            lb.set_lines(2)
            self.ly_lines.append(lb)
            lyr_box.pack_start(lb, False, False, 0)
        self.music_stack.add_named(lyr_box, "lyrics")
        return self.music_stack

    # ---- Overview: Today, Focus timer, Weather, System stats (NotchPixel's widget order)
    def _build_overview(self):
        grid = Gtk.Grid(column_spacing=8, row_spacing=8, column_homogeneous=True)
        cards = []

        def card(child):
            f = Gtk.Box()
            f.get_style_context().add_class("card")
            for side in ("top", "bottom", "start", "end"):
                getattr(child, f"set_margin_{side}")(12)
            f.pack_start(child, True, True, 0)
            return f

        # Today: big date, weekday/month, week number, this week's strip
        today = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        top = Gtk.Box(spacing=6)
        now = time.localtime()
        top.pack_start(label(str(now.tm_mday), "bignum", ellipsize=False), False, False, 0)
        wm = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        wm.pack_start(label(time.strftime("%a").upper(), "small", ellipsize=False), False, False, 0)
        wm.pack_start(label(time.strftime("%b").upper(), "small dim", ellipsize=False), False, False, 0)
        top.pack_start(wm, False, False, 0)
        top.pack_end(label(f"Week {int(time.strftime('%V'))}", "dim", ellipsize=False), False, False, 0)
        today.pack_start(top, False, False, 0)
        week = Gtk.Grid(column_homogeneous=True)
        start = time.time() - ((now.tm_wday + 1) % 7) * 86400  # Sunday first, as NotchPixel shows it
        for i in range(7):
            d = time.localtime(start + i * 86400)
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            col.pack_start(label(time.strftime("%a", d)[0], "small dim", xalign=0.5, ellipsize=False), False, False, 0)
            col.pack_start(label(str(d.tm_mday), "small" if d.tm_yday != now.tm_yday else "small", xalign=0.5,
                                 ellipsize=False), False, False, 0)
            if d.tm_yday == now.tm_yday:
                col.get_style_context().add_class("today")
            week.attach(col, i, 0, 1, 1)
        today.pack_start(week, False, False, 0)
        cards.append(("date", card(today)))

        # Focus timer: ring with the time, title, length, play / minus / plus
        focus = Gtk.Box(spacing=12)
        self.t_ring = Gtk.DrawingArea()
        self.t_ring.set_size_request(64, 64)
        self.t_ring.connect("draw", self._draw_ring)
        focus.pack_start(self.t_ring, False, False, 0)
        fv = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER)
        fv.pack_start(label("Focus timer", "title", ellipsize=False), False, False, 0)
        self.t_phase = label("", "dim", ellipsize=False)
        fv.pack_start(self.t_phase, False, False, 0)
        row = Gtk.Box(spacing=6)
        self.t_start = icon_button("media-playback-start-symbolic", "Start / pause", self._pomo_toggle, flat=False)
        self.t_start.get_style_context().add_class("round")
        self.t_start.get_style_context().add_class("play")
        row.pack_start(self.t_start, False, False, 0)
        for icon, delta in (("list-remove-symbolic", -5), ("list-add-symbolic", 5)):
            b = icon_button(icon, f"{delta:+d} min", lambda d=delta: self._pomo_set(
                max(5, min(180, self.cfg["focus_minutes"] + d))), flat=False)
            b.get_style_context().add_class("round")
            row.pack_start(b, False, False, 0)
        fv.pack_start(row, False, False, 4)
        focus.pack_start(fv, True, True, 0)
        self.t_big = label("", "", ellipsize=False)  # kept for _update_pomo; the ring shows the time
        cards.append(("timer", card(focus)))

        # Weather (minimal look): temperature, icon, divider, condition and high/low
        wbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        wtop = Gtk.Box()
        self.w_temp = label("–°", "bigtemp", ellipsize=False)
        self.w_icon = Gtk.Image()
        self.w_icon.set_pixel_size(22)
        wtop.pack_start(self.w_temp, False, False, 0)
        wtop.pack_end(self.w_icon, False, False, 0)
        wbox.pack_start(wtop, False, False, 0)
        wbox.pack_start(Gtk.Separator(), False, False, 0)
        wbot = Gtk.Box()
        self.w_text = label("Weather", "dim")
        self.w_hilo = label("", "dim", ellipsize=False)
        wbot.pack_start(self.w_text, True, True, 0)
        wbot.pack_end(self.w_hilo, False, False, 0)
        wbox.pack_start(wbot, False, False, 0)
        cards.append(("weather", card(wbox)))

        # System stats: thin lines (RAM in orange, as NotchPixel draws it) and network speed
        sbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.meters = {}
        stats = Gtk.Grid(column_spacing=8, row_spacing=3)
        for i, (name, color) in enumerate((("CPU", "#ffffff"), ("GPU", "rgba(255,255,255,0.55)"), ("RAM", "#ffffff"))):
            bar = Gtk.LevelBar(min_value=0, max_value=100, hexpand=True, valign=Gtk.Align.CENTER)
            for off in (Gtk.LEVEL_BAR_OFFSET_LOW, Gtk.LEVEL_BAR_OFFSET_HIGH, "full"):
                bar.remove_offset_value(off)
            css = Gtk.CssProvider()
            css.load_from_data(f"levelbar block.filled {{ background: {color}; min-height: 2px; }}"
                               "levelbar trough { min-height: 2px; }".encode())
            bar.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
            val = label("–", "small", ellipsize=False, xalign=1)
            val.set_width_chars(4)
            stats.attach(label(name, "small dim", ellipsize=False), 0, i, 1, 1)
            stats.attach(bar, 1, i, 1, 1)
            stats.attach(val, 2, i, 1, 1)
            self.meters[name] = (bar, val)
        sbox.pack_start(stats, False, False, 0)
        self.net_label = label("↓ 0 B/s   ↑ 0 B/s", "mono", ellipsize=False)
        sbox.pack_start(self.net_label, False, False, 0)
        self.net = system.NetMeter()
        cards.append(("stats", card(sbox)))

        def widget(title, big_css="bignum"):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            box.pack_start(label(title, "label", ellipsize=False), False, False, 0)
            big, sub = label("–", big_css, ellipsize=False), label("", "dim")
            box.pack_start(big, False, False, 0)
            box.pack_end(sub, False, False, 0)
            return box, big, sub

        box, self.w_batt, self.w_batt_sub = widget("Battery")
        cards.append(("battery", card(box)))
        box, self.w_disk, self.w_disk_sub = widget("Storage")
        self.w_disk_bar = Gtk.LevelBar(min_value=0, max_value=1)
        box.pack_end(self.w_disk_bar, False, False, 2)
        cards.append(("storage", card(box)))
        box, self.w_next, self.w_next_sub = widget("Up next", "title")
        self.w_next.set_ellipsize(3)
        cards.append(("upnext", card(box)))
        zone = self.cfg["world_clock_zone"]
        box, self.w_clock, self.w_clock_sub = widget(zone.rsplit("/", 1)[-1].replace("_", " "), "bigtime")
        cards.append(("clock", card(box)))
        box, self.w_np, self.w_np_sub = widget("Now playing", "title")
        self.w_np.set_ellipsize(3)
        controls = Gtk.Box(spacing=6)
        for icon, method in (("media-skip-backward-symbolic", "Previous"), ("media-playback-start-symbolic", "PlayPause"),
                             ("media-skip-forward-symbolic", "Next")):
            b = icon_button(icon, method, lambda m=method: self.mpris and self.mpris.call(m), flat=False)
            b.get_style_context().add_class("round")
            controls.pack_start(b, False, False, 0)
        box.pack_end(controls, False, False, 0)
        cards.append(("nowplaying", card(box)))
        notes = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        notes.pack_start(label("Notes", "label", ellipsize=False), False, False, 0)
        self.w_notes = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.w_notes.get_style_context().add_class("notes")
        self.w_notes.connect("button-press-event", self._want_keyboard)
        buf = self.w_notes.get_buffer()
        try:
            with open(os.path.join(DATA_DIR, "notes.txt"), encoding="utf-8") as f:
                buf.set_text(f.read(20000))
        except OSError:
            pass
        buf.connect("changed", lambda *_: self._save_notes_soon())
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, min_content_height=self.scaled(64))
        sw.add(self.w_notes)
        notes_wrap = Gtk.Overlay()
        notes_wrap.add(sw)
        notes_ph = label("Jot something down…", "dim", ellipsize=False)
        notes_ph.set_halign(Gtk.Align.START)
        notes_ph.set_valign(Gtk.Align.START)
        notes_ph.set_margin_start(4)
        notes_ph.set_margin_top(2)
        notes_ph.set_no_show_all(True)
        notes_wrap.add_overlay(notes_ph)
        notes_wrap.set_overlay_pass_through(notes_ph, True)
        notes_ph.set_visible(buf.get_char_count() == 0)
        buf.connect("changed", lambda b, p=notes_ph: p.set_visible(b.get_char_count() == 0))
        notes.pack_start(notes_wrap, True, True, 0)
        cards.append(("notes", card(notes)))
        for name, c in cards:
            c.get_style_context().add_class(f"w-{name}")  # each widget wears its own colour (design.WIDGET_COLORS)
        rank = {name: i for i, name in enumerate(self.cfg["widget_order"])}
        cards.sort(key=lambda kc: rank.get(kc[0], 99))
        shown = [c for k, c in cards if self.cfg[f"show_{k}_widget"]]
        for i, c in enumerate(shown):
            grid.attach(c, i % 2, i // 2, 1, 1)
        if not shown:
            grid.attach(label("All widgets are off. Turn them on in Settings › Widgets.", "dim"), 0, 0, 2, 1)
        self.weather_listeners.append(self._show_weather_overview)
        return grid

    def _draw_ring(self, w, cr):
        size = min(w.get_allocated_width(), w.get_allocated_height())
        c, r = size / 2, size / 2 - 3
        p = self.pomo
        total = self.cfg["focus_minutes" if p["phase"] == "focus" else "break_minutes"] * 60
        frac = 1 - p["left"] / max(1, total)
        cr.set_line_width(4)
        cr.set_source_rgba(1, 1, 1, 0.12)
        cr.arc(c, c, r, 0, 2 * math.pi)
        cr.stroke()
        if frac > 0:
            cr.set_source_rgb(1, 1, 1)
            cr.arc(c, c, r, -math.pi / 2, -math.pi / 2 + 2 * math.pi * frac)
            cr.stroke()
        layout = w.create_pango_layout(fmt_time(p["left"]))
        from gi.repository import Pango
        layout.set_font_description(Pango.FontDescription.from_string("Geist Medium 11"))
        tw, th = layout.get_pixel_size()
        cr.move_to(c - tw / 2, c - th / 2)
        cr.set_source_rgb(0.96, 0.96, 0.97)
        from gi.repository import PangoCairo
        PangoCairo.show_layout(cr, layout)

    # ---- Controls: big sliders, toggle tiles, power mode
    def _build_controls(self):
        box = Gtk.Box(spacing=12)

        def big_slider(icon, cb):
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            sc = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, 0, 100, 1)
            sc.set_inverted(True)
            sc.set_draw_value(False)
            sc.set_can_focus(False)
            sc.get_style_context().add_class("big")
            sc.connect("change-value", cb)
            pct = label("", "biglabel", xalign=0.5, ellipsize=False)
            img = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
            col.pack_start(pct, False, False, 0)
            col.pack_start(sc, True, True, 0)
            col.pack_start(img, False, False, 0)
            return col, sc, pct

        bcol, self.bright, self.bright_pct = big_slider("display-brightness-symbolic", self._on_brightness)
        vcol, self.vol, self.vol_pct = big_slider("audio-volume-high-symbolic", self._on_volume)
        self.bright_row = bcol
        box.pack_start(bcol, False, False, 0)
        box.pack_start(vcol, False, False, 0)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        grid = Gtk.Grid(column_spacing=8, row_spacing=8, column_homogeneous=True, row_homogeneous=True)
        self.tiles = {}
        specs = [("wifi", "Wi-Fi", "network-wireless-symbolic"), ("bt", "Bluetooth", "bluetooth-active-symbolic"),
                 ("night", "Night light", "night-light-symbolic"), ("dnd", "Focus", "notifications-disabled-symbolic"),
                 ("mute", "Mute", "audio-volume-muted-symbolic"), ("mic", "Mic", "audio-input-microphone-symbolic")]
        for i, (key, name, icon) in enumerate(specs):
            b = Gtk.Button()
            b.set_can_focus(False)
            b.get_style_context().add_class("qtile")
            b.get_style_context().add_class(f"q-{key}")
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            inner.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON), False, False, 0)
            inner.get_children()[0].set_halign(Gtk.Align.START)
            nm = label(name, "title", chars=12)
            st = label("", "dim", chars=14)  # a long Wi-Fi name must not stretch the grid past the card
            inner.pack_start(nm, False, False, 0)
            inner.pack_start(st, False, False, 0)
            b.add(inner)
            b.connect("clicked", lambda _b, k=key: self._toggle_tile(k))
            grid.attach(b, i % 3, i // 3, 1, 1)
            self.tiles[key] = (b, st)
        right.pack_start(grid, True, True, 0)
        seg = Gtk.Box(spacing=2)
        seg.get_style_context().add_class("segbar")
        self.power_btns = {}
        for prof, name in (("power-saver", "Battery"), ("balanced", "Balanced"), ("performance", "Performance")):
            b = Gtk.Button(label=name)
            b.set_can_focus(False)
            b.get_style_context().add_class("seg")
            b.connect("clicked", lambda _b, p=prof: self._set_power(p))
            seg.pack_start(b, True, True, 0)
            self.power_btns[prof] = b
        right.pack_start(seg, False, False, 0)
        box.pack_start(right, True, True, 0)
        return box

    # ---- Ask Claude
    def _build_claude(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.pack_start(panel_head("Ask Claude", label("Uses your Claude Code sign-in", "dim", ellipsize=False)),
                       False, False, 0)
        self.c_answer = Gtk.Label(xalign=0, yalign=0, wrap=True, selectable=True)
        self.c_answer.get_style_context().add_class("answer")
        self.c_answer.set_text("")
        self.c_answer.set_margin_start(2)
        self.c_answer.set_margin_end(2)
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        sw.add(self.c_answer)
        self.c_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=220)
        self.c_stack.add_named(empty_state("dialog-question-symbolic", "Ask anything",
                                           "Type below and press Enter. The answer appears here."), "empty")
        self.c_stack.add_named(sw, "answer")
        box.pack_start(self.c_stack, True, True, 0)
        row = Gtk.Box(spacing=8)
        self.c_entry = Gtk.Entry(placeholder_text="Ask anything…")
        self.c_entry.get_style_context().add_class("ask")
        self.c_entry.connect("button-press-event", self._want_keyboard)
        self.c_entry.connect("activate", lambda *_: self._ask())
        row.pack_start(self.c_entry, True, True, 0)
        send = icon_button("go-up-symbolic", "Send", self._ask, flat=False)
        send.get_style_context().add_class("round")
        send.get_style_context().add_class("play")
        row.pack_start(send, False, False, 0)
        box.pack_start(row, False, False, 0)
        return box

    def _build_web(self):
        from .webpanel import WebPanel

        self.web_panel = WebPanel(self._want_keyboard)
        return self.web_panel

    # ---- Clipboard
    def _build_clipboard(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=self.scaled(5, card=True))
        self.clip_filter = "all"
        toolbar = Gtk.Box(spacing=4)
        group = None
        for key, text in (("all", "All"), ("text", "Text"), ("pinned", "Snippets")):
            button = Gtk.RadioButton.new_with_label_from_widget(group, text)
            button.set_mode(False)
            button.get_style_context().add_class("clipfilter")
            group = button
            button.connect("toggled", self._select_clip_filter, key)
            toolbar.pack_start(button, False, False, 0)
        self.clip_search = Gtk.SearchEntry(placeholder_text="Search clipboard history", no_show_all=True)
        self.clip_search.connect("search-changed", lambda *_: self._refresh_clips(force=True))
        self.clip_search.connect("button-press-event", self._want_keyboard)
        self.clip_layout_button = icon_button("view-list-symbolic", "Toggle clipboard layout", self._toggle_clip_layout)
        toolbar.pack_end(self.clip_layout_button, False, False, 0)
        toolbar.pack_end(icon_button("edit-find-symbolic", "Search", self._toggle_clip_search), False, False, 0)
        self.clip_clear = Gtk.Button(label="Clear", no_show_all=True)
        self.clip_clear.get_style_context().add_class("flat")
        self.clip_clear.connect("clicked", self._clear_clips)
        toolbar.pack_end(self.clip_clear, False, False, 0)
        box.pack_start(toolbar, False, False, 0)
        box.pack_start(self.clip_search, False, False, 0)
        self.clip_cards = Gtk.Box(spacing=self.scaled(7, card=True))
        self.clip_rows = Gtk.FlowBox(min_children_per_line=2, max_children_per_line=2, homogeneous=True,
                                     row_spacing=4, column_spacing=6, valign=Gtk.Align.START,
                                     selection_mode=Gtk.SelectionMode.NONE)
        self.clip_scroll = Gtk.ScrolledWindow()
        self.clip_scroll.set_overlay_scrolling(True)
        self.clip_scroll.set_min_content_height(self.scaled(129, card=True))
        self.clip_scroll.connect("scroll-event", self._scroll_clip_cards)
        box.pack_start(self.clip_scroll, True, True, 0)
        self._apply_clip_layout()
        return box

    def _apply_clip_layout(self):
        cards = self.cfg["clipboard_layout"] == "cards"
        child = self.clip_scroll.get_child()
        if child:
            child.remove(child.get_child())
            self.clip_scroll.remove(child)
        self.clip_scroll.set_policy(Gtk.PolicyType.AUTOMATIC if cards else Gtk.PolicyType.NEVER,
                                    Gtk.PolicyType.EXTERNAL if cards else Gtk.PolicyType.AUTOMATIC)
        self.clip_scroll.add(self.clip_cards if cards else self.clip_rows)
        self.clip_scroll.show_all()
        self.clip_layout_button.set_image(Gtk.Image.new_from_icon_name(
            "view-grid-symbolic" if cards else "view-list-symbolic", Gtk.IconSize.BUTTON))

    def _toggle_clip_layout(self):
        mode = "list" if self.cfg["clipboard_layout"] == "cards" else "cards"
        try:
            config.set_value("clipboard_layout", mode)
        except OSError as error:
            print(f"opennotch: unable to save clipboard layout: {error}")
            return
        self.cfg["clipboard_layout"] = self.loaded_cfg["clipboard_layout"] = mode
        self._apply_clip_layout()
        self._refresh_clips(force=True)
        self._show_tab("clipboard")

    def _toggle_clip_search(self):
        visible = not self.clip_search.get_visible()
        self.clip_search.set_visible(visible)
        if visible:
            self.set_accept_focus(True)
            self.get_window().focus(Gtk.get_current_event_time())
            self.clip_search.grab_focus()
        else:
            self.clip_search.set_text("")
        self._show_tab("clipboard")

    def _select_clip_filter(self, button, key):
        if button.get_active():
            self.clip_filter = key
            self._refresh_clips(force=True)
            self.clip_scroll.get_hadjustment().set_value(0)

    def _clear_clips(self, _button):
        self.clips.clear_unpinned()
        self._refresh_clips(force=True)

    def _scroll_clip_cards(self, scroller, event):
        if self.cfg["clipboard_layout"] != "cards":
            return False
        if event.direction == Gdk.ScrollDirection.SMOOTH:
            _, dx, dy = event.get_scroll_deltas()
            if dx or not dy:
                return False
        elif event.direction in (Gdk.ScrollDirection.UP, Gdk.ScrollDirection.DOWN):
            dy = 1 if event.direction == Gdk.ScrollDirection.DOWN else -1
        else:
            return False
        adj = scroller.get_hadjustment()
        adj.set_value(adj.get_value() + dy * self.scaled(56, card=True))
        return True

    def _clip_card(self, item):
        text = item["text"]
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card.set_size_request(self.scaled(112, card=True), self.scaled(128, card=True))
        ctx = card.get_style_context()
        ctx.add_class("clipcard")
        if item["pinned"]:
            ctx.add_class("pinned")
        head = Gtk.Box(spacing=4)
        head.get_style_context().add_class("cliphead")
        head.pack_start(label("Text", "small"), True, True, 0)
        head.pack_end(label(ago(item["ts"]), "small"), False, False, 0)
        card.pack_start(head, False, False, 0)
        copy = Gtk.Button(valign=Gtk.Align.FILL)
        copy.get_style_context().add_class("clipcopy")
        copy.set_tooltip_text(text[:600])
        copy.connect("clicked", lambda *_: self._copy_clip(text))
        preview = label(text.strip()[:600])
        preview.set_line_wrap(True)
        preview.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        preview.set_lines(3)
        preview.set_valign(Gtk.Align.START)
        copy.add(preview)
        card.pack_start(copy, True, True, 0)
        foot = Gtk.Box()
        foot.get_style_context().add_class("clipfoot")
        foot.pack_start(label(f"{len(text)} chars", "small"), True, True, 0)
        pin = icon_button("view-pin-symbolic", "Unpin" if item["pinned"] else "Pin as snippet",
                          lambda: self._clip_op("pin", text))
        remove = icon_button("window-close-symbolic", "Remove", lambda: self._clip_op("rm", text))
        for button in (pin, remove):
            button.get_image().set_pixel_size(self.scaled(11, card=True))
            foot.pack_start(button, False, False, 0)
        card.pack_end(foot, False, False, 0)
        return card

    def _clip_row(self, item):
        text = item["text"]
        row = Gtk.Box(spacing=3)
        row.get_style_context().add_class("cliprow")
        button = Gtk.Button()
        button.get_style_context().add_class("clipcopy")
        button.set_tooltip_text(text[:600])
        button.connect("clicked", lambda *_: self._copy_clip(text))
        contents = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        contents.pack_start(label(" ".join(text.split())[:200]), False, False, 0)
        contents.pack_start(label(f"Text · {ago(item['ts'])}", "dim"), False, False, 0)
        button.add(contents)
        row.pack_start(button, True, True, 0)
        row.pack_end(icon_button("window-close-symbolic", "Remove", lambda: self._clip_op("rm", text)), False, False, 0)
        row.pack_end(icon_button("view-pin-symbolic", "Unpin" if item["pinned"] else "Pin as snippet",
                                 lambda: self._clip_op("pin", text)), False, False, 0)
        return row

    def _refresh_clip_cards(self):
        cards = self.cfg["clipboard_layout"] == "cards"
        container = self.clip_cards if cards else self.clip_rows
        for child in container.get_children():
            child.destroy()
        items = self.clips.search(self.clip_search.get_text())
        self.clip_clear.set_visible(any(not item["pinned"] for item in self.clips.items))
        shown = [item for item in items if self.clip_filter == "all" or
                 item["pinned"] == (self.clip_filter == "pinned")]
        if shown:
            for item in shown:
                if cards:
                    self.clip_cards.pack_start(self._clip_card(item), False, False, 0)
                else:
                    self.clip_rows.add(self._clip_row(item))
        else:
            message, hint = "Copy anything", "Ctrl+C, and it lands here. Pin the ones you keep."
            if self.clip_search.get_text():
                message, hint = "No matching clips", "Try a different search."
            elif self.clip_filter == "pinned":
                message, hint = "No pinned snippets", "Pin a clip to keep it here."
            empty = Gtk.Box(spacing=14, valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
            icon = Gtk.Image.new_from_icon_name("edit-copy-symbolic", Gtk.IconSize.DIALOG)
            icon.set_pixel_size(self.scaled(30, card=True))
            empty.pack_start(icon, False, False, 0)
            texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            texts.pack_start(label(message, "title"), False, False, 0)
            texts.pack_start(label(hint, "wingdim"), False, False, 0)
            empty.pack_start(texts, False, False, 0)
            if cards:
                self.clip_cards.pack_start(empty, True, True, 0)
            else:
                self.clip_rows.add(label(message, "wingdim"))
        container.show_all()

    # ---- Shelf
    def _build_shelf(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.shelf_clear = Gtk.Button(label="Clear")
        self.shelf_clear.get_style_context().add_class("flat")
        self.shelf_clear.set_can_focus(False)
        self.shelf_clear.set_no_show_all(True)
        self.shelf_clear.connect("clicked", lambda *_: self._shelf_set([]))
        box.pack_start(panel_head("Shelf", self.shelf_clear), False, False, 0)
        self.shelf_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.shelf_list.connect("row-activated", lambda _l, row: spawn("xdg-open", row.uri))
        box.pack_start(fitted_scroller(self.shelf_list, self.scaled(260)), True, True, 0)
        return box

    # ---- Notifications
    def _build_notifications(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.note_count = label("", "dim", ellipsize=False)
        self.note_clear = Gtk.Button(label="Clear all")
        self.note_clear.get_style_context().add_class("flat")
        self.note_clear.set_can_focus(False)
        self.note_clear.set_no_show_all(True)
        self.note_clear.connect("clicked", lambda *_: (self.notes.clear(), self._refresh_notes(), self._fit_card("notifications")))
        box.pack_start(panel_head("Notifications", self.note_count, self.note_clear), False, False, 0)
        self.note_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        box.pack_start(fitted_scroller(self.note_list, self.scaled(300)), True, True, 0)
        return box

    # ======================================================================= drawing & animation
    def _draw(self, _w, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        if self._hide_surface():
            if self.kwin_blur:
                self.kwin_blur.set_region(None, self.get_scale_factor())
            return False
        w, h, r = self._edge_strip(self.cur) if self._use_slim_strip() else self.cur
        x0, y0 = self._face_x(w), self._face_y(h)
        ph = self.geo["pill"][0 if self.side else 1]
        self._surface_path(cr, x0, y0, w, h, r)
        glassy = (self.cfg["surface"] == "glass" and self.state != "pill" and
                  (self.live_glass or self.glass is not None) and ((w if self.side else h) > ph + 6 or self.state == "toast"))
        if self.kwin_blur:
            self.kwin_blur.set_region(cr if glassy and self.live_glass else None, self.get_scale_factor())
        if not glassy:
            rgb = self._card_rgb()
            if rgb and w > 300:  # MusicBackground=album: the card takes the artwork's colours
                g = cairo.LinearGradient(x0, y0, x0 + w, y0 + h)
                g.add_color_stop_rgb(0, *(c * 0.55 for c in rgb))
                g.add_color_stop_rgb(0.6, *(c * 0.2 for c in rgb))
                g.add_color_stop_rgb(1, 0.043, 0.043, 0.047)
                cr.set_source(g)
            else:
                g = cairo.LinearGradient(0, y0, 0, y0 + h)
                g.add_color_stop_rgb(0, *design.INK)
                g.add_color_stop_rgb(1, *(c + 0.018 for c in design.INK))  # the faintest lift toward the bottom
                cr.set_source(g)
            cr.fill_preserve()
            if (w if self.side else h) > ph + 24:  # open card, not the pill: a soft light falling from the top
                cr.save()
                cr.clip_preserve()
                glow = cairo.RadialGradient(x0 + w / 2, y0, 0, x0 + w / 2, y0, max(w, h) * 0.75)
                glow.add_color_stop_rgba(0, *design.CHAMPAGNE_RGB, 0.13)
                glow.add_color_stop_rgba(0.55, *design.CHAMPAGNE_RGB, 0.03)
                glow.add_color_stop_rgba(1, *design.CHAMPAGNE_RGB, 0)
                cr.set_source(glow)
                cr.paint()
                cr.restore()
            rim = cairo.LinearGradient(0, y0, 0, y0 + h)
            top_alpha, low_alpha = (0.18, 0.34) if self.cfg["higher_contrast"] else (0.0, 0.13)
            rim.add_color_stop_rgba(0, *design.CHAMPAGNE_RGB, top_alpha)  # fades out into the bezel at the top
            rim.add_color_stop_rgba(1, *design.CHAMPAGNE_RGB, low_alpha)
            cr.set_source(rim)
            cr.set_line_width(1)
            cr.stroke()
            return False
        # liquid glass: blurred backdrop, a deep tint (album colour on the music tab), a bright rim
        cr.save()
        cr.clip_preserve()
        if not self.live_glass:
            Gdk.cairo_set_source_pixbuf(cr, self.glass, 0, 0)
            cr.paint()
        rgb = self._card_rgb()
        g = cairo.LinearGradient(x0, y0, x0 + w, y0 + h)
        if rgb:
            g.add_color_stop_rgba(0, *(c * 0.55 for c in rgb), 0.86)
            g.add_color_stop_rgba(0.6, *(c * 0.18 for c in rgb), 0.84)
            g.add_color_stop_rgba(1, 0.03, 0.03, 0.05, 0.86)
        else:  # smoked glass: ink with a trace of warmth, deeper toward the bottom
            g.add_color_stop_rgba(0, 0.075, 0.068, 0.060, 0.62)
            g.add_color_stop_rgba(1, *design.INK, 0.80)
        cr.set_source(g)
        cr.paint()
        # the band under the top edge stays solid black so the notch still reads as one with the bezel
        top = cairo.LinearGradient(0, y0, 0, y0 + ph + 14)
        top.add_color_stop_rgba(0, 0, 0, 0, 1)
        top.add_color_stop_rgba(0.6, 0, 0, 0, 0.85)
        top.add_color_stop_rgba(1, 0, 0, 0, 0)
        cr.set_source(top)
        cr.paint()
        # soft sheen across the upper part
        sheen = cairo.LinearGradient(0, y0 + ph, 0, y0 + max(ph + 1, h * 0.55))
        sheen.add_color_stop_rgba(0, *design.CHAMPAGNE_RGB, 0.05)
        sheen.add_color_stop_rgba(1, *design.CHAMPAGNE_RGB, 0)
        cr.set_source(sheen)
        cr.paint()
        cr.restore()
        rim = cairo.LinearGradient(x0, y0 + ph, x0 + w, y0 + h)
        rim.add_color_stop_rgba(0, *design.CHAMPAGNE_RGB, 0.30)
        rim.add_color_stop_rgba(0.5, *design.CHAMPAGNE_RGB, 0.06)
        rim.add_color_stop_rgba(1, *design.CHAMPAGNE_RGB, 0.20)
        cr.set_source(rim)
        cr.set_line_width(1)
        cr.stroke()
        return False  # let GTK draw the children on top

    def _surface_path(self, cr, x0, y0, w, h, r):
        if self.floating:
            rr = min(r, h / 2, w / 2)
            cr.new_path()
            cr.arc(x0 + w - rr, y0 + rr, rr, -math.pi / 2, 0)
            cr.arc(x0 + w - rr, y0 + h - rr, rr, 0, math.pi / 2)
            cr.arc(x0 + rr, y0 + h - rr, rr, math.pi / 2, math.pi)
            cr.arc(x0 + rr, y0 + rr, rr, math.pi, 1.5 * math.pi)
            cr.close_path()
        elif self.side:
            cr.save()
            if self.position == "left":
                cr.translate(x0, y0 + h)
                cr.rotate(-math.pi / 2)
            else:
                cr.translate(x0 + w, y0)
                cr.rotate(math.pi / 2)
            notch_path(cr, 0, 0, h, w, r)
            cr.restore()
        else:
            notch_path(cr, x0, y0, w, h, r)

    def _card_rgb(self):
        if self.cfg["music_background"] != "album" or self.state != "card":
            return None
        return self.art_rgb if self.pages.get_visible_child_name() == "music" else None

    def _realize_notch(self, _widget):
        self._set_input_shape(self.geo["pill"])
        if not extras.KDE or self.cfg["surface"] != "glass":
            return
        try:
            gi.require_version("GdkX11", "3.0")
            from gi.repository import GdkX11
            from Xlib.error import DisplayError
            from .kwinblur import KWinBlur

            window = self.get_window()
            self.kwin_blur = KWinBlur(self.get_display().get_name(), GdkX11.X11Window.get_xid(window))
        except (ImportError, ValueError, TypeError):
            return
        except DisplayError as error:
            print(f"opennotch: unable to connect to KWin for blur: {error}")

    def _capture_glass(self):
        """Snapshot what is behind the window and blur it (shrink, then scale back up smoothly)."""
        win = self.get_window()
        if not win:
            return
        x, y = self.window_origin
        try:
            pb = Gdk.pixbuf_get_from_window(Gdk.get_default_root_window(), x, y, self.W, self.H)
            if pb is None:
                self.glass = None
                return
            small = pb.scale_simple(max(1, self.W // 14), max(1, self.H // 14), GdkPixbuf.InterpType.BILINEAR)
            small = small.scale_simple(max(1, self.W // 5), max(1, self.H // 5), GdkPixbuf.InterpType.BILINEAR)
            self.glass = small.scale_simple(self.W, self.H, GdkPixbuf.InterpType.BILINEAR)
        except (GLib.Error, TypeError):
            self.glass = None

    def _set_input_shape(self, geo):
        if not self.get_realized():
            return
        if self._hide_surface():
            self.input_shape_combine_region(cairo.Region())
            return
        w, h, _ = self._edge_strip(geo) if self._use_slim_strip() and not self.anim else geo
        xpad, ypad = (0, self.shoulder) if self.side else (self.shoulder, 0)
        x, y = math.floor(self._face_x(w)), math.floor(self._face_y(h))
        region = cairo.Region(cairo.RectangleInt(x - xpad, y - ypad,
                                                 math.ceil(w) + 2 * xpad, math.ceil(h) + 2 * ypad))
        self.input_shape_combine_region(region)

    def _go(self, state):
        if state == self.state and not self.anim:
            return
        opening = self.geo[state][0] * self.geo[state][1] > self.cur[0] * self.cur[1]
        if state in ("card", "toast") and self.state == "pill" and self.cfg["surface"] == "glass":
            self.live_glass = bool(self.kwin_blur and self.kwin_blur.available)
            if not self.live_glass:
                self._capture_glass()
        self.state = state
        self._position_views()
        self.anim = (list(self.cur), time.monotonic(), design.spring if opening else design.ease_out_quint, True)
        start, end = self.anim[0], self.geo[state]
        self._set_input_shape((max(start[0], end[0]), max(start[1], end[1]), 0))
        self.views.set_visible_child_name("none")
        if not self.anim_tick:
            self.anim_tick = self.add_tick_callback(self._tick)
        if state == "card":
            self._on_card_opened()
        else:
            self._on_card_closed()

    def _tick(self, _w, _clock):
        frame_time = _clock.get_frame_time()
        if self.cfg["motion"] == "battery":
            if frame_time - self.frame_at < 16_000:
                return True
            self.frame_at = frame_time
        start, t0, ease, fade = self.anim
        end = self.geo[self.state]
        speed = {"relaxed": 1.4, "normal": 1.0, "quick": 0.6}[self.cfg["anim_speed"]]
        p = min(1.0, (time.monotonic() - t0) / ((GROW_SECONDS if ease is design.spring else ANIM_SECONDS) * speed))
        reduced = self.cfg["reduce_motion"]
        if reduced:
            p = min(1.0, (time.monotonic() - t0) / 0.14)
        k = 1 if reduced else ease(p)
        self.cur = [a + (b - a) * k for a, b in zip(start, end)]
        if fade and (reduced or p >= 0.35):
            face = self._resting_face() if self.state == "pill" else self.state
            if self.views.get_visible_child_name() != face:
                self.views.set_visible_child_name(face)
            self.views.set_opacity(p if reduced else design.content_fade(p))
        self.queue_draw()
        if p >= 1.0:
            self.cur = list(end)
            self.anim = None
            self.anim_tick = 0
            self._set_input_shape(end)
            if self.state == "card":  # content measured mid-animation may not fit: check once it has settled
                self._check_card_fit(None, self.card_box.get_allocation())
            return False
        return True

    # ======================================================================= hover
    def _on_enter(self, _w, ev):
        if ev.detail == Gdk.NotifyType.INFERIOR:
            return False
        self._cancel("close_timer")
        if self.state != "card" and not self.open_timer:
            self.open_timer = GLib.timeout_add(max(1, self.cfg["hover_delay_ms"]), self._open_now)
        return False

    def _on_leave(self, _w, ev):
        if ev.detail == Gdk.NotifyType.INFERIOR:
            return False
        self._cancel("open_timer")
        self._schedule_close()
        return False

    def _schedule_close(self):
        self._cancel("close_timer")
        self.close_timer = GLib.timeout_add(CLOSE_DELAY_MS, self._close_check)

    def _cancel(self, attr):
        if getattr(self, attr):
            GLib.source_remove(getattr(self, attr))
            setattr(self, attr, 0)

    def _open_now(self, tab=None):
        self.open_timer = 0
        if self.fullscreen_hidden:
            return False
        self._cancel("toast_timer")
        self.toast_showing = False
        if not tab and self.cfg["open_on"] == "music" and self._playing() and "music" in self.tab_buttons:
            tab = "music"
        if tab and tab in self.tab_buttons:
            self._show_tab(tab)
        self._go("card")
        return False

    def _pointer_inside(self):
        win = self.get_window()
        if not win:
            return False
        _, x, y, _ = win.get_device_position(Gdk.Display.get_default().get_default_seat().get_pointer())
        if self.fullscreen_hidden:
            return False
        w, h, _ = (self._edge_strip(self.cur)
                   if self._use_slim_strip() or self._hide_surface() else self.cur)
        xpad, ypad = (0, self.shoulder) if self.side else (self.shoulder, 0)
        left, top = self._face_x(w), self._face_y(h)
        return left - xpad <= x <= left + w + xpad and top - ypad <= y <= top + h + ypad

    def _poll_hover(self):
        self._update_coverage()
        if self.anim or self.dragging or self.fullscreen_hidden:
            return True
        inside = self._pointer_inside()
        if self.state != "card" and inside and not self.open_timer:
            self.open_timer = GLib.timeout_add(max(1, self.cfg["hover_delay_ms"]), self._open_now)
        elif self.state != "card" and not inside:
            self._cancel("open_timer")
        elif self.state == "card" and not inside and not self.close_timer:
            self._schedule_close()
        return True

    def _close_check(self):
        self.close_timer = 0
        if self.dragging or self.state != "card" or self._pointer_inside():
            return False
        self._go("pill")
        GLib.timeout_add(int(ANIM_SECONDS * 1000) + 60, self._next_toast)
        return False

    def _want_keyboard(self, _w, ev):
        # only the search box needs typing: take focus on click, give it back when the card closes
        self.set_accept_focus(True)
        self.get_window().focus(ev.time)
        return False

    def _on_card_opened(self):
        self._refresh_controls()
        self._on_tab_changed()

    def _on_card_closed(self):
        self._stop_stats()
        if hasattr(self, "seek"):
            self.seek.animate(False)
        if hasattr(self, "card_eq"):
            self.card_eq.run(False)
        if self.get_accept_focus():
            self.set_accept_focus(False)
        self._update_pill()

    # ======================================================================= tabs
    def _on_scroll(self, _w, ev):
        """Scroll on the closed pill = volume ±2%; scroll on the tab row = next/previous tab (gestures as in NotchX)."""
        if ev.direction == Gdk.ScrollDirection.SMOOTH:
            self.scroll_acc += ev.get_scroll_deltas()[2]
            if abs(self.scroll_acc) < 1:
                return True
            step, self.scroll_acc = (1 if self.scroll_acc > 0 else -1), 0.0
        elif ev.direction in (Gdk.ScrollDirection.UP, Gdk.ScrollDirection.DOWN):
            step = 1 if ev.direction == Gdk.ScrollDirection.DOWN else -1
        else:
            return False
        if self.cfg["reverse_scroll"]:
            step = -step
        if self.state != "card":
            v = system.sink_volume()
            if v is not None:
                spawn("pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{max(0, min(100, v - 2 * step))}%")
            return True
        if ev.y > self._face_y(self.cur[1]) + self.card_margins["top"] + self.tab_row.get_allocated_height() + 4:
            return False  # below the tabs: let lists scroll
        names = list(self.tab_buttons)
        cur = self.pages.get_visible_child_name()
        self._show_tab(names[(names.index(cur) + step) % len(names)])
        return True

    def _show_tab(self, name):
        self._fit_card(name)
        self.pages.set_visible_child_name(name)
        self._mark_tab(name)
        if self.state == "card":
            self._morph()

    def _check_card_fit(self, _box, alloc):
        """Safety net: if the content ended up bigger than the card (fonts and lists settle a frame late), grow it."""
        if not hasattr(self, "pages") or self.anim:
            return
        m = self.card_margins
        need = (alloc.width + m["start"] + m["end"], alloc.height + m["top"] + m["bottom"])
        if need[0] > self.geo["card"][0] + 1 or need[1] > self.geo["card"][1] + 1:
            def refit():
                self._fit_card(self.pages.get_visible_child_name(), at_least=need)
                if self.state == "card":
                    self._morph()
                return False
            GLib.idle_add(refit)

    def _morph(self):
        """Animate the open card to its new size without hiding the content."""
        self.anim = (list(self.cur), time.monotonic(), design.ease_out_quint, False)
        end = self.geo["card"]
        self._set_input_shape((max(self.cur[0], end[0]), max(self.cur[1], end[1]), 0))
        if not self.anim_tick:
            self.anim_tick = self.add_tick_callback(self._tick)

    def _mark_tab(self, name):
        for n, b in self.tab_buttons.items():
            ctx = b.get_style_context()
            (ctx.add_class if n == name else ctx.remove_class)("active")

    def _on_tab_changed(self):
        name = self.pages.get_visible_child_name()
        self._mark_tab(name)
        if self.state != "card":
            return
        self.queue_draw()  # the music page tints the card
        if name in ("overview", "music"):
            self._start_stats()
        else:
            self._stop_stats()
        if name == "controls":
            self._refresh_controls()
            self._refresh_tiles()
        if hasattr(self, "seek"):
            music_live = name == "music" and self._playing()
            self.seek.animate(music_live)
            if hasattr(self, "card_eq"):
                self.card_eq.run(music_live and not self.cfg["reduce_motion"])
        if name == "clipboard":
            self._refresh_clips()
        if name == "notifications":
            self.unread = 0
            self._refresh_notes()
            self._update_pill()

    # ======================================================================= music
    def _on_music(self):
        info = self.mpris.info() if self.mpris else None
        playing = bool(info and info["status"] == "Playing")
        if not hasattr(self, "music_stack"):
            self._update_pill()
            return False
        if info:
            self.m_title.set_text(info["title"])
            self.m_artist.set_text(info["artist"] or "Unknown artist")
            self.m_album.set_text(info["album"])
            key = (info["title"], info["artist"], info["length"])
            if key != getattr(self, "track_key", None):  # a new track starts at 0, not where the last one was
                self.track_key = key
                self.position_est = (0, time.monotonic())
                self.seek.set_value(0)
            self.seek.set_range(0, info["length"] / 1e6)
            self.m_album.set_visible(bool(info["album"]))
            self.m_len.set_text(fmt_time(info["length"] / 1e6) if info["length"] else ("LIVE" if playing else "–"))
            self.seek.set_sensitive(bool(info["length"]))
        else:
            self.m_title.set_text("Nothing playing")
            self.m_artist.set_text("Start a player to see it here")
            self.m_album.set_text("")
            self.seek.set_sensitive(False)
            self.seek.set_range(0, 0)
        self.b_play.set_image(Gtk.Image.new_from_icon_name(
            "media-playback-pause-symbolic" if playing else "media-playback-start-symbolic",
            Gtk.IconSize.LARGE_TOOLBAR))
        self._load_art(info["art"] if info else "")
        if self.music_stack.get_visible_child_name() == "lyrics":
            self._load_lyrics()
        music_live = playing and self.state == "card" and self.pages.get_visible_child_name() == "music"
        self.seek.animate(music_live)
        if hasattr(self, "card_eq"):
            self.card_eq.set_visible(playing)
            self.card_eq.run(music_live and not self.cfg["reduce_motion"])
        self._update_pill()
        return False

    def _load_art(self, url):
        if url == self.art_url:
            return
        self.art_url = url
        if not url:
            return self._set_art(None)
        if url in self.art_cache:
            return self._set_art(self.art_cache[url])
        if url.startswith("file://"):
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(Gio.File.new_for_uri(url).get_path(), 160, 160, True)
            except GLib.Error:
                pb = None
            self.art_cache[url] = pb
            return self._set_art(pb)
        if url.startswith(("http://", "https://")):
            threading.Thread(target=self._fetch_art, args=(url,), daemon=True).start()
        else:
            self._set_art(None)

    def _fetch_art(self, url):
        try:
            with urllib.request.urlopen(url, timeout=6) as r:
                data = r.read(5_000_000)
        except Exception as e:  # network errors of any kind just mean "no art"
            print("opennotch: art download failed:", e)
            data = None
        GLib.idle_add(self._art_downloaded, url, data)

    def _art_downloaded(self, url, data):
        pb = None
        if data:
            try:
                loader = GdkPixbuf.PixbufLoader()
                loader.set_size(160, 160)
                loader.write(data)
                loader.close()
                pb = loader.get_pixbuf()
            except GLib.Error:
                pb = None
        if len(self.art_cache) > 30:
            self.art_cache.clear()
        self.art_cache[url] = pb
        if url == self.art_url:
            self._set_art(pb)
        return False

    def _set_art(self, pb):
        self.art.set_pixbuf(pb)
        self.pill_art.set_pixbuf(pb)
        self.art_rgb = dominant_rgb(pb)
        self.queue_draw()

    def _on_seek_value(self, value):
        if self.mpris:
            self.mpris.seek_to(value, self.position_us)

    def _playing(self):
        info = self.mpris.info() if getattr(self, "mpris", None) else None
        return bool(info and info["status"] == "Playing")

    def _poll_position(self):
        def got(us):
            now = time.monotonic()
            if us is None:  # player won't say: carry on from the last reading while it plays
                last_us, last_at = getattr(self, "position_est", (0, now))
                us = last_us + ((now - last_at) * 1e6 if self._playing() else 0)
            self.position_est = (us, now)
            self.position_us = us
            self.seek.set_value(us / 1e6)
            self.m_pos.set_text(fmt_time(us / 1e6))
            self._show_lyric_line(us / 1e6)
        if self.mpris:
            self.mpris.position(got)

    # ======================================================================= system stats (card open + Home tab only)
    def _start_stats(self):
        if not self.stats_timer:
            self._tick_stats()
            self.stats_timer = GLib.timeout_add_seconds(1, self._tick_stats)

    def _tick_game(self):
        def pct(name, read):
            try:
                value = read()
            except OSError:
                value = None
            return f"{name} {'–' if value is None else f'{value:.0f}%'}"
        # shortcut: no FPS on X11 without hooking the game (MangoHud); add it if a reader turns up
        parts = (pct("CPU", self.cpu.percent), pct("GPU", system.gpu_percent), pct("RAM", system.ram_percent))
        self.game_label.set_text(("\n" if self.side else "   ").join(parts))
        return True

    def _tick_widgets(self):
        bat = system.battery()
        self.w_batt.set_text(f"{bat[0]}%" if bat else "–")
        self.w_batt_sub.set_text(("Charging" if bat[1] else "On battery") if bat else "No battery")
        try:
            disk = shutil.disk_usage(os.path.expanduser("~"))
            self.w_disk.set_text(f"{disk.free / 1e9:.0f} GB")
            self.w_disk_sub.set_text(f"free of {disk.total / 1e9:.0f} GB")
            self.w_disk_bar.set_value(disk.used / disk.total)
        except OSError:
            self.w_disk.set_text("–")
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo

        there = _dt.now(ZoneInfo(self.cfg["world_clock_zone"]))
        self.w_clock.set_text(there.strftime("%H:%M"))
        diff = (there.utcoffset() - _dt.now().astimezone().utcoffset()).total_seconds() / 3600
        self.w_clock_sub.set_text(there.strftime("%a") + (f" · {diff:+g} h" if diff else " · same time"))
        info = self.mpris.info() if getattr(self, "mpris", None) else None
        self.w_np.set_text(info["title"] if info and info.get("title") else "Nothing playing")
        self.w_np_sub.set_text(info.get("artist", "") if info else "")
        m = self.meeting
        if m is None:
            self.w_next.set_text("Nothing scheduled")
            self.w_next_sub.set_text("" if self.cfg["calendar_file"] else "Choose a calendar file in Settings › Calls")
        else:
            self.w_next.set_text(m.title)
            self.w_next_sub.set_text(m.starts_at.astimezone().strftime("%a %d %b · %H:%M"))

    def _save_notes_soon(self):
        self._cancel("notes_timer")
        self.notes_timer = GLib.timeout_add(600, self._save_notes)

    def _save_notes(self):
        self.notes_timer = 0
        buf = self.w_notes.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            tmp = os.path.join(DATA_DIR, "notes.txt.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, os.path.join(DATA_DIR, "notes.txt"))  # never leave a half-written file
        except OSError as error:
            print("opennotch: could not save notes:", error)
        return False

    def _stop_stats(self):
        self._cancel("stats_timer")

    def _tick_stats(self):
        def put(name, value, text=None):
            bar, val = self.meters[name]
            bar.set_value(0 if value is None else max(0, min(100, value)))
            val.set_text(text or ("–" if value is None else f"{value:.0f}%"))
        try:
            put("CPU", self.cpu.percent())
            put("RAM", system.ram_percent())
        except OSError:
            pass
        put("GPU", system.gpu_percent())
        down, up = self.net.rates()
        self.net_label.set_text(f"↓ {system.human_rate(down)}   ↑ {system.human_rate(up)}")
        self._tick_widgets()
        self._poll_position()
        return True

    # ======================================================================= quick controls
    def _refresh_controls(self):
        if time.monotonic() - self.last_user_volume > 0.6:  # don't fight the slider while it is dragged
            v = system.sink_volume()
            if v is not None:
                self.vol.set_value(v)
                self.vol_pct.set_text(f"{v}%")
        b = extras.get_brightness()
        self.bright_row.set_visible(b is not None)
        if b is not None:
            self.bright.set_value(b)
            self.bright_pct.set_text(f"{b}%")
        self._show_mic_state(system.mic_muted())
        self._paint_tile("mute", system.sink_muted(), "On" if system.sink_muted() else "Off")

    def _refresh_tiles(self):
        def read():
            return {"wifi": extras.wifi_on(), "ssid": extras.wifi_name(), "bt": extras.bluetooth_on(),
                    "night": extras.night_light_on(), "dnd": extras.dnd_on(), "power": extras.power_profile()}

        def show(st):
            if not st:
                return
            self.toggle_state.update(st)
            self._paint_tile("wifi", st["wifi"], st["ssid"] or ("On" if st["wifi"] else "Off"))
            self._paint_tile("bt", st["bt"], "On" if st["bt"] else "Off")
            self._paint_tile("night", st["night"], "On" if st["night"] else "Off")
            self._paint_tile("dnd", st["dnd"], "On" if st["dnd"] else "Off")
            for prof, b in self.power_btns.items():
                (b.get_style_context().add_class if prof == st["power"] else b.get_style_context().remove_class)("active")
        extras.in_thread(read, show)

    def _paint_tile(self, key, on, text):
        if key not in getattr(self, "tiles", {}):
            return
        b, st = self.tiles[key]
        (b.get_style_context().add_class if on else b.get_style_context().remove_class)("on")
        st.set_text(text)

    def _toggle_tile(self, key):
        st = self.toggle_state
        if key == "mute":
            spawn("pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle")
            return GLib.timeout_add(200, lambda: self._refresh_controls() and False)
        if key == "mic":
            return self._toggle_mic(toast=False)
        actions = {"wifi": lambda: extras.set_wifi(not st.get("wifi")),
                   "bt": lambda: extras.set_bluetooth(not st.get("bt")),
                   "night": lambda: extras.set_night_light(not st.get("night")),
                   "dnd": lambda: extras.set_dnd(not st.get("dnd"))}
        if key in ("night", "dnd"):  # gsettings: instant, main thread is fine
            actions[key]()
            return self._refresh_tiles()
        extras.in_thread(actions[key], lambda _r: self._refresh_tiles())

    def _set_power(self, prof):
        extras.in_thread(lambda: extras.set_power_profile(prof), lambda _r: self._refresh_tiles())

    def _on_volume(self, _s, _scroll, value):
        self.last_user_volume = time.monotonic()
        self.vol_pct.set_text(f"{int(max(0, min(100, value)))}%")
        spawn("pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{int(max(0, min(100, value)))}%")
        return False

    def _on_brightness(self, _s, _scroll, value):
        value = int(max(1, min(100, value)))
        self.last_bright = value
        self.bright_pct.set_text(f"{value}%")
        extras.set_brightness(value)
        return False

    def _show_mic_state(self, muted):
        self.mic_muted = muted
        self._paint_tile("mic", not muted, "Muted" if muted else "On")
        self._update_pill()

    def _toggle_mic(self, toast=True):
        system.pactl("set-source-mute", "@DEFAULT_SOURCE@", "toggle")
        muted = system.mic_muted()
        self._show_mic_state(muted)
        if toast:
            self.show_toast("Microphone muted" if muted else "Microphone on", "fail" if muted else "ok", 2)

    def _bind_hotkey(self):
        if not Keybinder:
            print("opennotch: Keybinder not available, Ctrl+Alt+M disabled")
            return
        Keybinder.init()
        c = self.cfg
        keys = {c["key_mic"]: lambda: self._toggle_mic(),
                c["key_toggle"]: lambda: self._go("pill") if self.state == "card" else self._open_now(),
                c["key_play"]: lambda: self.mpris and self.mpris.call("PlayPause"),
                c["key_timer"]: lambda: self._pomo_toggle(),
                c["key_hide"]: lambda: self.set_visible(not self.get_visible())}
        if c["color_pick"]:
            keys.setdefault("<Ctrl><Alt>C", self._pick_color)
        keys.setdefault("<Ctrl><Alt>S", lambda: self._capture_hotkey(self._take_screenshot))
        if c["screen_record"]:
            keys.setdefault("<Ctrl><Alt><Shift>R", lambda: self._capture_hotkey(self._toggle_screen_recording))
        if self.obs is not None:
            keys.setdefault("<Ctrl><Alt>R", self._toggle_obs_recording)
        if c["alt_tab_animation"]:
            from .alttab import AltTab

            self.alt_tab = AltTab(c["alt_tab_style"], c["reduce_motion"])
            keys.setdefault("<Alt>Tab", lambda: self.alt_tab.step(1))
            keys.setdefault("<Alt><Shift>Tab", lambda: self.alt_tab.step(-1))
        if c["custom_taskbar"] and c["taskbar_number_keys"]:
            for n in range(1, 10):
                keys.setdefault(f"<Super>{n}", lambda n=n: self._open_pinned(n))
        if extras.KDE:
            vol = lambda arg: spawn("pactl", "set-sink-volume", "@DEFAULT_SINK@", arg)
            keys.update({"XF86AudioRaiseVolume": lambda: vol("+5%"), "XF86AudioLowerVolume": lambda: vol("-5%"),
                         "XF86AudioMute": lambda: spawn("pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"),
                         "XF86AudioMicMute": lambda: self._toggle_mic(),
                         "XF86AudioPlay": lambda: self.mpris and self.mpris.call("PlayPause"),
                         "XF86AudioNext": lambda: self.mpris and self.mpris.call("Next"),
                         "XF86AudioPrev": lambda: self.mpris and self.mpris.call("Previous")})
        taken_super = False
        for accel, fn in keys.items():
            if Keybinder.bind(accel, lambda *_a, f=fn: f()):
                continue
            fallback = config.DEFAULTS["key_timer"]
            if accel == config.LEGACY_TIMER_KEY and accel == c["key_timer"] and fallback not in keys:
                if Keybinder.bind(fallback, lambda *_: self._pomo_toggle()):
                    print(f"opennotch: {accel} is taken; using {fallback} for the timer")
                    continue
            print(f"opennotch: {accel} is taken by another program")
            if accel.startswith("<Super>") and accel[-1].isdigit():
                taken_super = True
            if accel == "<Alt>Tab":
                where = ("System Settings › Shortcuts › KWin (Walk Through Windows)" if extras.KDE
                         else "Keyboard settings › Shortcuts › Windows (Switch windows)")
                self.show_toast("Alt+Tab is taken", "info", 6, f"Free it in {where}.")
        if taken_super:
            where = ("System Settings › Shortcuts › plasmashell (Activate Task Manager Entry)" if extras.KDE
                     else "Keyboard settings › Shortcuts")
            self.show_toast("Super + number is taken", "info", 6, f"Free it in {where}.")

    def _open_pinned(self, n):
        from . import taskkeys

        reason = taskkeys.open_position(n, Keybinder.get_current_event_time())
        if reason:
            self.show_toast(reason, "info", 3)

    def _capture_hotkey(self, action):
        try:
            action()
        except ValueError as error:
            self.show_toast("Capture unavailable", "fail", 3, str(error))

    def _capture_monitor(self):
        display = self.get_display()
        pointer = display.get_default_seat().get_pointer()
        _, x, y = pointer.get_position()
        monitor = display.get_monitor_at_point(x, y) or self.monitor
        if monitor is None:
            raise ValueError("There is no screen to capture.")
        return monitor

    def _take_screenshot(self):
        try:
            path = screenshot(self._capture_monitor())
        except (GLib.Error, OSError) as error:
            raise ValueError(str(error)) from error
        shelved = self.cfg["captures_to_shelf"] and "shelf" in self.tab_buttons
        if shelved:
            self._shelf_set([path.as_uri(), *self.shelf])
        self.show_toast("Screenshot saved", "ok", 2.5,
                        "Added to the Shelf" if shelved else path.parent.name + " · " + path.name)

    def _toggle_screen_recording(self):
        if self.recorder.active:
            self.recorder.stop()
            return
        if not self.cfg["screen_record"]:
            raise ValueError("Enable screen recording in Settings › Tools.")
        try:
            self.recorder.start(self._capture_monitor(), self.cfg["record_microphone"])
        except OSError as error:
            raise ValueError(str(error)) from error

    def _recording_changed(self, event, path, error):
        self._cancel("capture_timer")
        if event == "started":
            self.capture_timer = GLib.timeout_add_seconds(1, lambda: self._update_pill() or True)
            self.show_toast("Recording started", "info", 2)
        elif event == "saved":
            self.show_toast("Recording saved", "ok", 4, path.name)
        else:
            print(f"opennotch: {error}", file=sys.stderr)
            self.show_toast("Recording stopped", "fail", 5,
                            f"Partial recording: {path.name}" if path else error)
        if self.state == "pill":
            self.views.set_visible_child_name(self._resting_face())
        self._update_pill()
        self._set_input_shape(self.cur)
        self.queue_draw()

    def _set_video_privacy(self, active):
        self.video_privacy = active
        self._update_pill()
        if self.state == "pill":
            self.views.set_visible_child_name(self._resting_face())
        self._set_input_shape(self.cur)
        self.queue_draw()

    def _capture_status_visible(self):
        return self.recorder.active or bool(self.video_privacy) or bool(
            self.studio_state and (self.studio_state.recording or self.studio_state.streaming)
        )

    def _obs_status(self, state):
        self.studio_state = state
        self._update_pill()
        if self.state == "pill":
            self.views.set_visible_child_name(self._resting_face())
        self._set_input_shape(self.cur)
        self.queue_draw()

    def _on_chat_message(self, author, text):
        if len(self.toasts) < 2:  # don't let a busy chat queue up behind other notices
            self.show_toast(author, "info", 4, text[:200])

    def _toggle_obs_recording(self):
        if self.obs is not None and not self.obs.toggle_recording():
            self.show_toast("OBS unavailable", "info", 3, self.obs.state.error or "Open OBS and enable its WebSocket server.")

    def _refresh_calendar(self):
        if self.calendar_loading:
            return True
        self.calendar_loading = True

        def read_calendar():
            from .calendarfeed import next_meeting

            try:
                return next_meeting(self.cfg["calendar_file"])
            except (OSError, ValueError):
                print("opennotch: could not read the calendar file", file=sys.stderr)
                return None

        def loaded(meeting):
            self.meeting = meeting
            self.calendar_loading = False
            self._update_pill()

        extras.in_thread(read_calendar, loaded)
        return True

    def _upcoming_meeting(self):
        if self.meeting is None or not self.cfg["meeting_countdown"]:  # the Up next widget may load meetings too
            return None
        left = (self.meeting.starts_at - datetime.now(timezone.utc)).total_seconds()
        if 0 < left <= 3600:
            return f"◷ {max(1, math.ceil(left / 60))}m"
        return None

    def _pick_color(self):
        display = self.get_display()
        _, x, y = display.get_default_seat().get_pointer().get_position()
        pixel = Gdk.pixbuf_get_from_window(Gdk.get_default_root_window(), x, y, 1, 1)
        if pixel is not None:
            hex_color = "#" + bytes(pixel.get_pixels()[:3]).hex().upper()
            self.clipboard.set_text(hex_color, -1)
            self.clipboard.store()
            self.show_toast(hex_color, "ok", 2, "Copied colour to clipboard")

    # ---- pactl subscribe: event driven, no polling
    def _start_pactl_watch(self):
        try:
            self.pactl_proc = Gio.Subprocess.new(["pactl", "subscribe"], Gio.SubprocessFlags.STDOUT_PIPE)
        except GLib.Error as e:
            print("opennotch: pactl subscribe failed:", e.message)
            return
        self.pactl_stream = Gio.DataInputStream.new(self.pactl_proc.get_stdout_pipe())
        self.pactl_stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self._on_pactl_line)
        self.pactl_pending = 0

    def _on_pactl_line(self, stream, res):
        try:
            line, _ = stream.read_line_finish_utf8(res)
        except GLib.Error:
            line = None
        if line is None:  # pactl exited (sound server restarted): try again shortly
            GLib.timeout_add_seconds(3, lambda: self._start_pactl_watch() and False)
            return
        if "source-output" in line or "on source" in line or "on server" in line:
            if not self.pactl_pending:
                self.pactl_pending = GLib.timeout_add(250, self._after_pactl_event)
        elif "on sink" in line and "sink-input" not in line:
            if self.state == "card":
                if not self.pactl_pending:
                    self.pactl_pending = GLib.timeout_add(250, self._after_pactl_event)
            elif self.cfg["show_volume_hud"] and not getattr(self, "sink_pending", 0):
                self.sink_pending = GLib.timeout_add(60, self._after_sink_event)
        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self._on_pactl_line)

    def _after_sink_event(self):
        self.sink_pending = 0
        now = (system.sink_volume(), system.sink_muted())
        if self.last_sink is not None and now != self.last_sink and now[0] is not None:
            self.show_osd("volume", now[0], now[1])
        self.last_sink = now
        return False

    def _watch_brightness(self):
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION)
            bus.signal_subscribe("org.cinnamon.SettingsDaemon.Power", "org.cinnamon.SettingsDaemon.Power.Screen",
                                 "Changed", "/org/cinnamon/SettingsDaemon/Power", None, 0, self._on_bright_signal)
            bus.signal_subscribe("org.kde.Solid.PowerManagement", extras._KPOWER[2], "brightnessChanged",
                                 extras._KPOWER[1], None, 0, self._on_bright_signal)
        except GLib.Error as e:
            print("opennotch: brightness watch unavailable:", e.message)
        self.last_sink = (system.sink_volume(), system.sink_muted())

    def _on_bright_signal(self, *_):
        b = extras.get_brightness()
        if b is not None and b != self.last_bright and self.state != "card" and self.cfg["show_brightness_hud"]:
            self.show_osd("brightness", b)
        self.last_bright = b

    def _after_pactl_event(self):
        self.pactl_pending = 0
        self._check_recording()
        if self.state == "card":
            self._refresh_controls()
        else:
            self._show_mic_state(system.mic_muted())
        return False

    # ======================================================================= calls
    def _check_recording(self):
        apps = [app for app in system.recording_apps() if app != RECORDER_APP]
        if apps and self.recording_since is None:
            self.recording_since = time.monotonic()
            self.call_timer = GLib.timeout_add_seconds(1, lambda: self._update_pill() or True)
        elif not apps and self.recording_since is not None:
            self.recording_since = None
            self._cancel("call_timer")
        self.pill_rec.set_tooltip_text("Recording: " + ", ".join(apps) if apps else None)
        self._update_pill()

    # ======================================================================= pill
    def _tick_clock(self):
        self.pill_time.set_text(time.strftime("%H:%M"))
        bat = system.battery()
        show = self.cfg["resting"] == "clock"
        self.pill_batt.set_visible(show and bool(bat))
        self.pill_bicon.set_visible(show and bool(bat))
        if bat:
            self.pill_batt.set_text(f"{bat[0]}%")
            level = min(100, (bat[0] + 5) // 10 * 10)
            self.pill_bicon.set_from_icon_name(f"battery-level-{level}{'-charging' if bat[1] else ''}-symbolic",
                                               Gtk.IconSize.MENU)
        self._update_pill()
        return True

    def _refresh_weather(self):
        city = self.cfg["weather_city"] or time_zone_city()
        if city:
            extras.in_thread(extras.fetch_weather, self._got_weather, city, self.cfg["weather_fahrenheit"])
        return True

    def _got_weather(self, w):
        if not w:
            return
        self.weather = w
        self.pill_wicon.set_from_icon_name(w["icon"], Gtk.IconSize.MENU)
        self.pill_temp.set_text(f"{w['temp']}°")
        for fn in self.weather_listeners:
            fn(w)

    def _show_weather_overview(self, w):
        self.w_temp.set_text(f"{w['temp']}°")
        self.w_icon.set_from_icon_name(w["icon"], Gtk.IconSize.DIALOG)
        self.w_text.set_text(f"{w['text']} · {w['place']}")
        self.w_hilo.set_text(f"H {w['high']}°  L {w['low']}°")

    def _update_pill(self):
        info = self.mpris.info() if getattr(self, "mpris", None) else None
        playing = bool(info and info["status"] == "Playing")
        self.pill_art.set_visible(playing)
        self.pill_eq.set_visible(playing)
        self.pill_eq.run(playing and self.state == "pill")
        rec = self.recording_since is not None
        rec = rec and self.cfg["show_call_activity"]
        self.pill_rec.set_visible(rec)
        self.pill_call.set_visible(rec)
        if rec:
            self.pill_call.set_text(fmt_time(time.monotonic() - self.recording_since))
        self.pill_mic.set_visible(getattr(self, "mic_muted", False) and rec)
        p = getattr(self, "pomo", None)
        if p and p["running"]:
            self.pill_pomo.set_text(("◔ " if p["phase"] == "focus" else "☕ ") + fmt_time(p["left"]))
            self.pill_pomo.show()
        else:
            self.pill_pomo.hide()
        self.pill_capture.set_visible(self._capture_status_visible())
        if self.recorder.active:
            elapsed = fmt_time(time.monotonic() - self.recorder.started_at)
            self.pill_capture.set_text(f"● REC  {elapsed}")
            self.pill_capture.set_tooltip_text("Screen recording")
        elif self.studio_state and (self.studio_state.recording or self.studio_state.streaming):
            studio = [label for condition, label in ((self.studio_state.recording, "REC"),
                      (self.studio_state.streaming, "LIVE")) if condition]
            self.pill_capture.set_text("● " + " · ".join(studio))
            self.pill_capture.set_tooltip_text("OBS" + (f" · {', '.join(sorted(self.video_privacy))}" if self.video_privacy else ""))
        else:
            self.pill_capture.set_text("●")
            self.pill_capture.set_tooltip_text(", ".join(sorted(self.video_privacy)) or None)
        countdown = self._upcoming_meeting()
        self.pill_meeting.set_visible(bool(countdown))
        if countdown:
            self.pill_meeting.set_text(countdown)
            self.pill_meeting.set_tooltip_text(self.meeting.title)
        self.card_privacy.set_visible(self._capture_status_visible())
        self.card_privacy.set_tooltip_text(self.pill_capture.get_tooltip_text())
        self.pill_badge.set_text(str(min(self.unread, 99)) if getattr(self, "unread", 0) else "")
        self.pill_badge.set_visible(bool(getattr(self, "unread", 0)))
        if self.pill_pet is not None:
            self.pill_pet.set_visible(not (rec or self._capture_status_visible() or countdown or self.game_strip))
        self._update_pet_mood(playing=playing, pomo=p)
        if "notifications" in self.tab_buttons:
            n = getattr(self, "unread", 0)
            self.tab_buttons["notifications"].set_tooltip_text("Notifications" + (f" ({n} new)" if n else ""))

        minimum, _ = self.pill_box.get_preferred_size()
        if self.game_strip:  # the strip's text must sit inside the pill, so the pill grows to it
            strip = self.game_size
            pad = 2 * self.scaled(14)
            minimum.width = max(minimum.width, strip.width + pad)
            minimum.height = max(minimum.height, strip.height + (pad if self.side else 0))
        w, h, r = self.geo["pill"]
        if self.side:
            h = max(minimum.height, self.scaled(self.cfg["pill_width"]))
            w = max(w, minimum.width)
        else:
            w = max(minimum.width, self.scaled(self.cfg["pill_width"]))
        if (w, h, r) != self.geo["pill"]:
            self.geo["pill"] = (w, h, r)
            if self.state == "pill" and not self.anim:
                self.cur = list(self.geo["pill"])
                self._position_views()
                self._set_input_shape(self.cur)
                self.queue_draw()

    # ======================================================================= toasts (scripting API, hotkey, timer)
    def _show_activity(self, text, icon_name, active):
        self.show_toast(text, seconds=2.2, activity=(icon_name, active))

    def show_toast(self, text, icon="info", seconds=5, sub="", note=None, activity=None):
        text, sub = i18n.tr(text), i18n.tr(sub)
        if self.cfg["longer_notices"]:
            seconds *= 2
        self.toasts.append((text, icon, seconds, sub, note, activity))
        if self.state != "card" and not self.toast_showing:
            self._next_toast()

    def show_osd(self, kind, value, muted=False):
        """Volume/brightness pop-up from the notch; repeated changes just update the one already showing."""
        if self.state == "card":
            return
        if self.toast_showing and not self.osd_active:
            return  # a message is up; don't cover it
        self._cancel("toast_timer")
        self._fit_toast()
        self.toast_dot.hide()
        self.toast_text.get_style_context().add_class("title")
        icon = ("display-brightness-symbolic" if kind == "brightness" else
                "audio-volume-muted-symbolic" if muted or value == 0 else
                "audio-volume-low-symbolic" if value < 34 else
                "audio-volume-medium-symbolic" if value < 67 else "audio-volume-high-symbolic")
        for child in self.toast_img.get_children():
            child.destroy()
        img = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.DND)
        self.toast_img.add(img)
        self.toast_img.show_all()
        self.toast_icon.hide()
        self.toast_sub.hide()
        self.toast_text.set_text(("Brightness" if kind == "brightness" else "Volume") +
                                 ("  · muted" if muted else f"  {value}%"))
        self.toast_bar.set_value(0 if muted else value)
        self.toast_bar.show()
        self.osd_active = self.toast_showing = True
        self._go("toast")
        seconds = 3000 if self.cfg["longer_notices"] else 1500
        self.toast_timer = GLib.timeout_add(seconds, self._end_toast)

    def _next_toast(self):
        if self.state == "card" or self.toast_showing or not self.toasts:
            return False
        self.toast_bar.hide()
        self.osd_active = False
        text, icon, seconds, sub, note, activity = self.toasts.pop(0)
        self._fit_toast(activity is not None)
        title = self.toast_text.get_style_context()
        (title.remove_class if activity else title.add_class)("title")
        self.toast_dot.set_visible(activity is not None)
        self.toast_text.set_text(text)
        self.toast_sub.set_text(sub)
        self.toast_sub.set_visible(bool(sub))
        for child in self.toast_img.get_children():
            child.destroy()
        if activity:
            icon_name, active = activity
            self.toast_img.add(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU))
            self.toast_dot.set_text("●" if active else "○")
        elif note:
            self.toast_img.add(note_icon(note, 34))
        if note or activity:
            self.toast_img.show_all()
        else:
            self.toast_img.hide()
        self.toast_icon.set_visible(not (note or activity))
        if not (note or activity):
            self.toast_icon.set_text(ICON_GLYPHS[icon])
            ctx = self.toast_icon.get_style_context()
            for c in ICON_GLYPHS:
                ctx.remove_class(c)
            ctx.add_class(icon)
        self.toast_showing = True
        self._go("toast")
        self.toast_timer = GLib.timeout_add(int(seconds * 1000), self._end_toast)
        return False

    def _end_toast(self):
        self.toast_timer = 0
        self.toast_showing = self.osd_active = False
        if self.state == "toast":
            self._go("pill")
        if self.toasts:
            GLib.timeout_add(int(ANIM_SECONDS * 1000) + 150, self._next_toast)
        return False

    # ======================================================================= clipboard
    def _on_clipboard(self, cb, _ev):
        cb.request_targets(self._got_targets)

    def _got_targets(self, cb, atoms, *_):
        if any(a.name() == PASSWORD_HINT for a in (atoms or [])):
            return  # a password manager asked not to be remembered
        cb.request_text(self._got_text)

    def _got_text(self, _cb, text, *_):
        if text and self.clips.add(text):
            self.clips.save()
            self.clips_dirty = True
            if self.state == "card" and self.pages.get_visible_child_name() == "clipboard":
                self._refresh_clips()

    def _refresh_clips(self, force=False):
        if not (self.clips_dirty or force):
            return
        self.clips_dirty = False
        self._refresh_clip_cards()

    def _clip_op(self, op, text):
        (self.clips.toggle_pin if op == "pin" else self.clips.remove)(text)
        self.clips.save()
        self._refresh_clips(force=True)

    def _copy_clip(self, text):
        self.clipboard.set_text(text, -1)
        self.clipboard.store()
        self.show_toast("Copied to clipboard", "ok", 1.5)

    # ======================================================================= file shelf
    def _setup_dnd(self):
        self.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY | Gdk.DragAction.LINK)
        self.drag_dest_add_uri_targets()
        self.connect("drag-motion", self._on_drag_motion)
        self.connect("drag-leave", lambda *_: self._schedule_close())
        self.connect("drag-data-received", self._on_drop)

    def _on_drag_motion(self, *_):
        self._cancel("close_timer")
        if self.dragging:
            return False  # our own shelf item: not a new drop
        if self.state != "card" and "shelf" in self.tab_buttons:
            self._open_now("shelf")
        elif "shelf" in self.tab_buttons and self.pages.get_visible_child_name() != "shelf":
            self._show_tab("shelf")
        return False

    def _on_drop(self, _w, _ctx, _x, _y, data, _info, _time):
        if self.dragging:
            return
        uris = [u for u in (data.get_uris() or []) if u not in self.shelf]
        if uris:
            self._shelf_set(self.shelf + uris)

    def _load_shelf(self):
        try:
            with open(self.shelf_path, encoding="utf-8") as f:
                uris = [u for u in json.load(f) if isinstance(u, str)]
        except (OSError, ValueError, TypeError):
            return []
        return [u for u in uris if not u.startswith("file://") or Gio.File.new_for_uri(u).query_exists()]

    def _shelf_set(self, uris):
        self.shelf = uris
        try:
            with open(self.shelf_path, "w", encoding="utf-8") as f:
                json.dump(uris, f)
        except OSError as e:
            print("opennotch: could not save shelf:", e)
        self._refresh_shelf()

    def _refresh_shelf(self):
        if not hasattr(self, "shelf_list"):
            return
        for child in self.shelf_list.get_children():
            child.destroy()
        if not self.shelf:
            row = Gtk.ListBoxRow(child=empty_state("folder-download-symbolic", "Nothing on the shelf",
                                                   "Drop files on the notch to park them here, then drag them into any app."),
                                 activatable=False)
            row.get_style_context().add_class("bare")
            self.shelf_list.add(row)
        self.shelf_clear.set_visible(bool(self.shelf))
        for uri in self.shelf:
            f = Gio.File.new_for_uri(uri)
            icon_name = "text-x-generic"
            try:
                info = f.query_info("standard::icon", Gio.FileQueryInfoFlags.NONE, None)
                gicon = info.get_icon()
            except GLib.Error:
                gicon = None
            row = Gtk.ListBoxRow()
            row.uri = uri
            ev = Gtk.EventBox()
            box = Gtk.Box(spacing=8)
            img = Gtk.Image.new_from_gicon(gicon, Gtk.IconSize.DND) if gicon else \
                Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.DND)
            box.pack_start(img, False, False, 0)
            name = label(f.get_basename() or uri)
            name.set_tooltip_text(f.get_path() or uri)
            box.pack_start(name, True, True, 0)
            box.pack_end(icon_button("window-close-symbolic", "Remove from shelf",
                                     lambda u=uri: self._shelf_set([x for x in self.shelf if x != u])),
                         False, False, 0)
            path = f.get_path()
            if self.cfg["phone_share"] and path and os.path.isfile(path):
                box.pack_end(icon_button("phone-symbolic", "Send to phone",
                                         lambda filename=path: self._share_file(filename)), False, False, 0)
            ev.add(box)
            ev.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, [], Gdk.DragAction.COPY | Gdk.DragAction.LINK)
            ev.drag_source_add_uri_targets()
            ev.connect("drag-data-get", lambda _w, _c, data, _i, _t, u=uri: data.set_uris([u]))
            ev.connect("drag-begin", self._on_shelf_drag_begin, gicon)
            ev.connect("drag-end", self._on_shelf_drag_end)
            row.add(ev)
            row.set_tooltip_text("Drag out to any app · click to open")
            self.shelf_list.add(row)
        self.shelf_list.show_all()

    def _share_file(self, path):
        from .shareui import ShareDialog

        if self.share_dialog is not None:
            self.share_dialog.destroy()
        try:
            dialog = ShareDialog(path)
        except (GLib.Error, OSError, ValueError) as error:
            self._go("pill")
            self.show_toast("Could not share file", "fail", 4, str(error))
            return
        self.share_dialog = dialog
        dialog.connect("destroy", lambda *_: setattr(self, "share_dialog", None))
        dialog.show_all()

    def _on_shelf_drag_begin(self, widget, ctx, gicon):
        self.dragging = True
        if gicon:
            Gtk.drag_set_icon_gicon(ctx, gicon, 0, 0)

    def _on_shelf_drag_end(self, *_):
        self.dragging = False
        self._schedule_close()

    # ======================================================================= notifications mirror
    def _on_notification(self, note):
        self.notes.insert(0, note)
        del self.notes[30:]
        if self.state == "card" and self.pages.get_visible_child_name() == "notifications":
            self._refresh_notes()
        else:
            self.unread += 1
            title = note["summary"] or note["app"]
            sub = note["body"] or (note["app"] if note["summary"] else "")
            self.show_toast(title, seconds=self.cfg["notification_seconds"], sub=" ".join(sub.split()), note=note)
            for pet in (self.pill_pet, self.card_pet):
                if pet is not None:
                    pet.trigger_hop(self.unread)
            if self.roaming_pet is not None:
                self.roaming_pet.jump_to_notice(self.unread)
        self._update_pill()
        return False

    # ======================================================================= pet jobs
    def _poll_pet_health(self):
        if self.cfg["resting"] != "pet":
            self._pet_health_timer = 0
            return False
        now = time.monotonic()
        bat = system.battery()
        low_bat = bool(bat and not bat[1] and bat[0] <= 15)
        cpu = self.cpu.percent() or 0
        ram = system.ram_percent() or 0
        high_now = cpu > 85 or ram > 85
        if high_now:
            if self._high_load_since is None:
                self._high_load_since = now
        elif cpu < 80 and ram < 80:
            self._high_load_since = None
        sustained_high = self._high_load_since is not None and (now - self._high_load_since) >= 15.0

        if low_bat:
            self.pet_health = ("battery", bat[0])
        elif sustained_high:
            self.pet_health = ("cpu", round(cpu)) if cpu >= ram else ("ram", round(ram))
        else:
            self.pet_health = None
        self._update_pet_mood()
        return True

    def _update_pet_mood(self, playing=None, pomo=None):
        if self.pill_pet is None and self.card_pet is None:
            return
        from .pet import choose_mood

        if playing is None:
            info = self.mpris.info() if getattr(self, "mpris", None) else None
            playing = bool(info and info["status"] == "Playing")
        if pomo is None:
            pomo = getattr(self, "pomo", None)
        idle_s = self.pet_idle_clock.seconds() if self.pet_idle_clock is not None else 0.0
        health = self.pet_health
        mood = choose_mood(
            unread=getattr(self, "unread", 0),
            low_battery=bool(health and health[0] == "battery"),
            high_load=bool(health and health[0] in ("cpu", "ram")),
            pomo_running=bool(pomo and pomo["running"]),
            pomo_phase=pomo["phase"] if pomo else "focus",
            playing=playing,
            idle_s=idle_s,
        )
        if self.unread > 0:
            tip = f"{self.unread} unread notice{'s' if self.unread != 1 else ''} — click to open"
        elif health:
            kind, val = health
            label_map = {"battery": f"Battery {val}%", "cpu": f"CPU {val}%", "ram": f"RAM {val}%"}
            tip = f"{label_map[kind]} — click to check"
        else:
            tip = "Click to pause focus timer" if (pomo and pomo["running"]) else "Click to start focus timer"
        for pet in (self.pill_pet, self.card_pet):
            if pet is not None:
                pet.set_mood(mood, badge=self.unread, tooltip=tip)

    def _on_pet_click(self):
        from .pet import smart_click_action

        action = smart_click_action(self.unread, self.pet_health)
        if action == "notifications":
            if "notifications" in self.tab_buttons:
                self._open_now("notifications")
            elif self.notes:
                n = self.notes[0]
                self.unread = 0
                self.show_toast(n["summary"] or n["app"], seconds=self.cfg["notification_seconds"], sub=n.get("body", ""), note=n)
                self._update_pill()
        elif action == "stats":
            kind, val = self.pet_health
            if "overview" in self.tab_buttons:
                self._open_now("overview")
            msg = f"Battery at {val}%" if kind == "battery" else f"{kind.upper()} at {val}%"
            if self.state != "card":
                self.show_toast(msg, "dialog-warning-symbolic", seconds=3)
        else:
            self._pomo_toggle()
            if self.state == "pill":
                running = bool(self.pomo and self.pomo["running"])
                self.show_toast("Focus timer started" if running else "Focus timer paused",
                                "alarm-symbolic", seconds=2)

    def _pet_notch_anchor(self):
        if self.monitor is None:
            return None
        ox, oy = self.window_origin
        w, h, _ = self.cur
        return ox + self._face_x(w) + w / 2.0, oy + self._face_y(h) + h - 4.0

    def _pet_plank_bounds(self):
        if self.dock_bg is not None and self.dock_bg.has_plank and self.dock_bg.mon_geo is not None:
            g = self.dock_bg.mon_geo
            top_y = g.y + g.height - self.dock_bg.base_h
            return g.x + self.dock_bg.base_left, g.x + self.dock_bg.base_right, top_y
        return None

    def _pet_toast_perch(self):
        if self.state != "toast":
            return None
        ox, oy = self.window_origin
        w, h, _ = self.geo["toast"]
        return ox + self._face_x(w) + w / 2.0, oy + self._face_y(h) + 2.0

    def _refresh_notes(self):
        for child in self.note_list.get_children():
            child.destroy()
        if not self.notes:
            row = Gtk.ListBoxRow(child=empty_state("preferences-system-notifications-symbolic", "All caught up",
                                                   "New notices land here."), activatable=False)
            row.get_style_context().add_class("bare")
            self.note_list.add(row)
        for n in self.notes:
            card = Gtk.Box(spacing=12)
            card.get_style_context().add_class("notecard")
            icon = note_icon(n, 32)
            icon.set_valign(Gtk.Align.START)
            card.pack_start(icon, False, False, 0)
            texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            top = Gtk.Box(spacing=8)
            top.pack_start(label(n["app"].upper(), "apptag"), True, True, 0)
            when = time.strftime("%H:%M", time.localtime(n["time"])) if self.cfg["notice_clock_time"] else ago(n["time"])
            top.pack_end(label(when, "apptag", ellipsize=False), False, False, 0)
            texts.pack_start(top, False, False, 0)
            if n["summary"]:
                texts.pack_start(label(n["summary"], "title"), False, False, 0)
            if n["body"]:
                body = label(" ".join(n["body"].split()), "dim")
                body.set_line_wrap(True)
                body.set_lines(2)
                texts.pack_start(body, False, False, 0)
            card.pack_start(texts, True, True, 0)
            row = Gtk.ListBoxRow(child=card, activatable=False)
            row.get_style_context().add_class("bare")
            self.note_list.add(row)
        self.note_list.show_all()
        k = len(self.notes)
        self.note_count.set_text(str(k) if k else "")
        self.note_clear.set_visible(bool(k))

    # ======================================================================= lyrics
    def _show_lyrics(self, on):
        self.music_stack.set_visible_child_name("lyrics" if on else "player")
        if on:
            self._load_lyrics()
        self._cancel("lyrics_timer")
        if on:
            self.lyrics_timer = GLib.timeout_add(400, lambda: self._poll_position() or True)

    def _load_lyrics(self):
        info = self.mpris.info() if self.mpris else None
        if not info or not info["title"]:
            self.lyrics, self.lyrics_key = [], None
            self.ly_head.set_text("Nothing playing")
            return self._paint_lyrics(-1)
        key = (info["title"], info["artist"])
        self.ly_head.set_text(f"{info['title']} · {info['artist']}")
        if key == self.lyrics_key:
            return
        self.lyrics_key, self.lyrics = key, []
        self.ly_lines[2].set_text("Looking for lyrics…")
        for i in (0, 1, 3, 4):
            self.ly_lines[i].set_text("")

        def got(lines):
            if self.lyrics_key != key:
                return
            self.lyrics = lines or []
            if not self.lyrics:
                self.ly_lines[2].set_text("No synced lyrics for this song")
        extras.in_thread(extras.fetch_lyrics, got, info["title"], info["artist"], info["album"], info["length"] / 1e6)

    def _show_lyric_line(self, seconds):
        if self.lyrics and self.music_stack.get_visible_child_name() == "lyrics":
            self._paint_lyrics(extras.line_at(self.lyrics, seconds + 0.3))

    def _paint_lyrics(self, idx):
        for k, lb in enumerate(self.ly_lines):
            j = idx + k - 2
            lb.set_text(self.lyrics[j][1] if 0 <= j < len(self.lyrics) else ("♪" if k == 2 and self.lyrics else ""))

    # ======================================================================= ask claude
    def _ask(self):
        q = self.c_entry.get_text().strip()
        if not q:
            return
        if self.claude_proc:
            self.claude_proc.force_exit()
        self.c_answer.set_text("Thinking…")
        self.c_stack.set_visible_child_name("answer")

        def done(answer, err):
            self.claude_proc = None
            self.c_answer.set_text(answer if answer else "Couldn't get an answer: " + (err or ""))
        self.claude_proc = extras.ask_claude(q, done)
        self.c_entry.set_text("")

    # ======================================================================= focus timer
    def _pomo_toggle(self):
        p = self.pomo
        p["running"] = not p["running"]
        if p["running"]:
            p["end"] = time.monotonic() + p["left"]
            p["timer"] = GLib.timeout_add_seconds(1, self._pomo_tick)
        elif p["timer"]:
            GLib.source_remove(p["timer"])
            p["timer"] = 0
        self._update_pomo()

    def _pomo_reset(self, phase):
        p = self.pomo
        if p["running"]:
            self._pomo_toggle()
        p["phase"] = phase
        p["left"] = self.cfg["focus_minutes" if phase == "focus" else "break_minutes"] * 60
        self._update_pomo()

    def _pomo_next(self, announce=True):
        p = self.pomo
        was_running = p["running"]
        nxt = "break" if p["phase"] == "focus" else "focus"
        self._pomo_reset(nxt)
        if announce:
            self.show_toast(f"Focus done. Take {self.cfg['break_minutes']} minutes." if nxt == "break"
                            else "Break over. Back to focus.", "info", 6)
        if was_running:
            self._pomo_toggle()

    def _pomo_tick(self):
        p = self.pomo
        p["left"] = max(0, round(p["end"] - time.monotonic()))
        if p["left"] <= 0:
            p["timer"] = 0
            self._pomo_next()
            return False
        self._update_pomo()
        return True

    def _pomo_set(self, minutes):
        self.cfg["focus_minutes"] = minutes
        p = self.pomo
        if p["running"]:
            self._pomo_toggle()
        p["phase"], p["left"] = "focus", minutes * 60
        self._update_pomo()

    def _update_pomo(self):
        p = self.pomo
        if hasattr(self, "t_big"):
            self.t_big.set_text(fmt_time(p["left"]))
            self.t_phase.set_text(f"{self.cfg['focus_minutes']} + {self.cfg['break_minutes']} min" if p["phase"] == "focus"
                                  else "Break")
            self.t_start.set_image(Gtk.Image.new_from_icon_name(
                "media-playback-pause-symbolic" if p["running"] else "media-playback-start-symbolic", Gtk.IconSize.BUTTON))
            self.t_ring.queue_draw()
        self._update_pill()

    # ======================================================================= scripting socket
    def _activate_wallpaper(self):
        from .wallpaper import LiveWallpaper

        wallpaper = LiveWallpaper(self.cfg["live_wallpaper_file"])
        try:
            wallpaper.start()
        except (GLib.Error, ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
            self.show_toast("Could not play wallpaper", "fail", 5, str(error))
        else:
            self.live_wallpaper = wallpaper
        return GLib.SOURCE_REMOVE

    def _recover_wallpaper(self):
        from .wallpaper import recover_pending_wallpaper

        try:
            recover_pending_wallpaper()
        except (GLib.Error, ValueError, RuntimeError, OSError) as error:
            print(f"opennotch: wallpaper recovery failed: {error}", file=sys.stderr)
        return GLib.SOURCE_REMOVE

    def _stop_wallpaper(self):
        if self.live_wallpaper is not None:
            try:
                self.live_wallpaper.close()
            except (GLib.Error, ValueError, RuntimeError, OSError) as error:
                print(f"opennotch: wallpaper restore failed: {error}", file=sys.stderr)

    def _start_socket(self):
        self.sock_path = socket_path()
        self.server = protocol.listen(self.sock_path)
        GLib.io_add_watch(self.server.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN, self._on_socket)

    def _on_socket(self, *_):
        try:
            conn, _ = self.server.accept()
        except OSError:
            return True
        protocol.handle_connection(conn, self._on_request)
        return True

    def _on_request(self, req):
        command = req["cmd"]
        if command == "screenshot":
            self._take_screenshot()
        elif command == "record":
            self._toggle_screen_recording()
        elif command in ("say", "done") and self.cfg["notify_endpoint"]:
            if command == "say" or self.cfg["agents_notify_done"]:
                self.show_toast(req["text"], req["icon"], req["seconds"])

    def _watch_config(self):
        self.cfg_monitor = Gio.File.new_for_path(os.path.join(config.CONFIG_DIR, "config.json")).monitor_file(
            Gio.FileMonitorFlags.WATCH_MOVES, None)
        self.cfg_monitor.connect("changed", lambda *_: self._config_changed())

    def _config_changed(self):
        self._cancel("reload_timer")
        self.reload_timer = GLib.timeout_add(600, self._reload)

    def _reload(self):
        """Apply new settings by starting fresh: simplest way to get every widget, binding and service right."""
        self.reload_timer = 0
        if config.load() == self.loaded_cfg:
            return False
        self.recorder.close()
        if self.obs is not None:
            self.obs.close()
        if self.twitch is not None:
            self.twitch.close()
        if self.youtube is not None:
            self.youtube.close()
        if self.previews is not None:
            self.previews.close()
        if self.dock_bg is not None:
            self.dock_bg.close()
        if self.roaming_pet is not None:
            self.roaming_pet.close()
        if self.pet_idle_clock is not None:
            self.pet_idle_clock.close()
        self._stop_wallpaper()
        if self.share_dialog is not None:
            self.share_dialog.destroy()
        try:
            self.server.close()
            os.unlink(self.sock_path)
        except OSError:
            pass
        os.execv(sys.executable, [sys.executable, "-m", "opennotch"])

    def shutdown(self):
        self.recorder.close()
        if self.obs is not None:
            self.obs.close()
        if self.twitch is not None:
            self.twitch.close()
        if self.youtube is not None:
            self.youtube.close()
        if self.previews is not None:
            self.previews.close()
        if self.dock_bg is not None:
            self.dock_bg.close()
        if self.roaming_pet is not None:
            self.roaming_pet.close()
        if self.pet_idle_clock is not None:
            self.pet_idle_clock.close()
        self._stop_wallpaper()
        if self.share_dialog is not None:
            self.share_dialog.destroy()
        try:
            self.server.close()
            os.unlink(self.sock_path)
        except OSError:
            pass
        Gtk.main_quit()


def main():
    cfg = config.load()
    Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
    try:
        win = Notch(cfg)
    except RuntimeError as e:  # already running
        print("opennotch:", e)
        return 1
    win.show_all()
    if cfg["live_wallpaper"] and cfg["live_wallpaper_file"]:
        GLib.timeout_add(350, win._activate_wallpaper)
    else:
        GLib.timeout_add(350, win._recover_wallpaper)
    if cfg["all_monitors"]:
        from .monitors import DisplayMirrors
        win.display_mirrors = DisplayMirrors(win)
    if cfg["custom_taskbar"]:
        from .dockbg import DockBackground
        win.dock_bg = DockBackground(extras.KDE, cfg["reduce_motion"], cfg["surface"])
    if cfg["resting"] == "pet" and not cfg["reduce_motion"]:
        from .pet import RoamingPet
        win.roaming_pet = RoamingPet(
            cfg["pet"],
            reduce_motion=cfg["reduce_motion"],
            get_notch_anchor=win._pet_notch_anchor,
            get_plank_bounds=win._pet_plank_bounds,
            get_toast_perch=win._pet_toast_perch,
            on_click=win._on_pet_click,
        )
    if cfg["custom_taskbar"] and cfg["taskbar_status"]:
        from .tray import StatusStrip
        win.status_strip = StatusStrip(extras.KDE, cfg["taskbar_auto_hide"], on_bell=lambda: win._open_now("notifications"),
                                       on_controls=lambda: win._open_now("controls"))
    if cfg["desktop_widgets"]:
        from .desktop import DesktopWidgets
        win.desk = DesktopWidgets(win)
        win.desk.show_all()
    win.views.set_visible_child_name("none" if cfg["hidden_until_hover"] else "pill")
    win._update_pill()
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda *_: win.shutdown() or False)
    Gtk.main()
    return 0
