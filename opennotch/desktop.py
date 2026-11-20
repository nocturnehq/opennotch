"""Desktop widgets: a huge faded day name, the date and time, and a column of glass cards (weather, system, music).

One transparent window under every other window. It takes no clicks, so desktop icons keep working.
"""
import math
import time

import cairo
import gi

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango, PangoCairo

from . import system  # noqa: E402

CARD_W, CARD_R, GAP, MARGIN = 290, 22, 14, 56


def rounded(cr, x, y, w, h, r):
    cr.new_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    cr.close_path()


def text(cr, s, font, x, y, rgba=(1, 1, 1, 1), spacing=0, align="left", width=None):
    """Draw s with Pango; returns (w, h). align centre/right uses width (or the text width)."""
    layout = PangoCairo.create_layout(cr)
    layout.set_font_description(Pango.FontDescription.from_string(font))
    attrs = Pango.AttrList()
    if spacing:
        attrs.insert(Pango.attr_letter_spacing_new(int(spacing * Pango.SCALE)))
    layout.set_attributes(attrs)
    layout.set_text(s, -1)
    w, h = layout.get_pixel_size()
    if align == "center":
        x = x + ((width or 0) - w) / 2
    elif align == "right":
        x = x + (width or 0) - w
    cr.set_source_rgba(*rgba)
    cr.move_to(x, y)
    PangoCairo.show_layout(cr, layout)
    return w, h


class DesktopWidgets(Gtk.Window):
    def __init__(self, notch):
        super().__init__(title="OpenNotch desktop")
        self.notch = notch
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.set_decorated(False)
        self.set_keep_below(True)
        self.stick()
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_accept_focus(False)
        self.set_focus_on_map(False)
        self.set_type_hint(Gdk.WindowTypeHint.DESKTOP)  # the desktop layer: always under every app window
        display = Gdk.Display.get_default()
        mon = display.get_primary_monitor() or display.get_monitor(0)
        self.geo = mon.get_geometry()
        self.move(self.geo.x, self.geo.y)
        self.set_default_size(self.geo.width, self.geo.height)
        self.connect("draw", self._draw)
        # no input region at all: every click goes to the desktop / windows underneath
        self.connect("realize", lambda *_: self.input_shape_combine_region(cairo.Region()))
        self.cpu = system.CpuMeter()
        self.stats = {}
        self.icons = {}
        notch.weather_listeners.append(lambda _w: self.queue_draw())
        self.bg = Gio.Settings.new("org.cinnamon.desktop.background")
        self.bg.connect("changed::picture-uri", lambda *_: self._pick_ink())
        self._pick_ink()
        self._tick()
        GLib.timeout_add_seconds(3, self._tick)

    def _pick_ink(self):
        """Dark text on a light wallpaper, white text on a dark one (judged from the top half, where the clock is)."""
        self.dark_ink = False
        try:
            path = Gio.File.new_for_uri(self.bg.get_string("picture-uri")).get_path()
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 32, 18, False)
            data, n, stride = pb.get_pixels(), pb.get_n_channels(), pb.get_rowstride()
            lum = [0.2126 * data[y * stride + x * n] + 0.7152 * data[y * stride + x * n + 1] +
                   0.0722 * data[y * stride + x * n + 2] for y in range(9) for x in range(32)]
            self.dark_ink = sum(lum) / len(lum) > 150
        except (GLib.Error, TypeError):
            pass
        self.queue_draw()

    def _tick(self):
        try:
            self.stats = {"CPU": self.cpu.percent(), "RAM": system.ram_percent(), "GPU": system.gpu_percent()}
        except OSError:
            pass
        self.queue_draw()
        return True

    def _icon(self, name, px):
        key = (name, px)
        if key not in self.icons:
            try:
                info = Gtk.IconTheme.get_default().lookup_icon(name, px, Gtk.IconLookupFlags.FORCE_SIZE)
                white = Gdk.RGBA(1, 1, 1, 1)
                self.icons[key] = info.load_symbolic(white, None, None, None)[0] if info else None
            except GLib.Error:
                self.icons[key] = None
        return self.icons[key]

    def _card(self, cr, x, y, h):
        rounded(cr, x, y, CARD_W, h, CARD_R)
        cr.set_source_rgba(0.06, 0.06, 0.08, 0.42)
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, 0.10)
        cr.set_line_width(1)
        cr.stroke()

    def _draw(self, _w, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        W, H = self.geo.width, self.geo.height

        # ---- the day, huge and faded, across the upper third
        ink = (0.13, 0.16, 0.20) if self.dark_ink else (1, 1, 1)
        day = time.strftime("%A").upper()
        text(cr, day, "SF Pro Display Thin 150px", 0, H * 0.12, ink + (0.55 if self.dark_ink else 0.42,), spacing=34,
             align="center", width=W)
        stamp = time.strftime("%-d %B %Y").upper() + "   ·   " + time.strftime("%H:%M")
        text(cr, stamp, "SF Pro Text Medium 17px", 0, H * 0.12 + 200, ink + (0.8,), spacing=6, align="center",
             width=W)

        # ---- glass cards on the right
        x, y = W - CARD_W - MARGIN, H * 0.42
        w = self.notch.weather
        if w:
            self._card(cr, x, y, 118)
            text(cr, f"{w['temp']}°", "SF Pro Display Light 46px", x + 20, y + 14)
            pb = self._icon(w["icon"], 40)
            if pb:
                Gdk.cairo_set_source_pixbuf(cr, pb, x + CARD_W - 60, y + 22)
                cr.paint()
            text(cr, f"{w['text']} · {w['place']}", "SF Pro Text Medium 13px", x + 22, y + 72, (1, 1, 1, 0.85))
            text(cr, f"H {w['high']}°   L {w['low']}°", "SF Pro Text 12px", x + 22, y + 92, (1, 1, 1, 0.6))
            y += 118 + GAP

        rows = [(k, v) for k, v in self.stats.items() if v is not None]
        bat = system.battery()
        if bat:
            rows.append(("BAT", float(bat[0])))
        if rows:
            h = 26 + 26 * len(rows)
            self._card(cr, x, y, h)
            for i, (name, v) in enumerate(rows):
                ry = y + 18 + i * 26
                text(cr, name, "SF Pro Text Semibold 11px", x + 22, ry, (1, 1, 1, 0.6), spacing=1.5)
                bx, bw = x + 70, CARD_W - 140
                rounded(cr, bx, ry + 6, bw, 4, 2)
                cr.set_source_rgba(1, 1, 1, 0.14)
                cr.fill()
                rounded(cr, bx, ry + 6, max(4, bw * min(100, v) / 100), 4, 2)
                cr.set_source_rgba(1, 1, 1, 0.9)
                cr.fill()
                text(cr, f"{v:.0f}%", "SF Pro Text Medium 12px", x + CARD_W - 64, ry - 1, (1, 1, 1, 0.85),
                     align="right", width=42)
            y += h + GAP

        info = self.notch.mpris.info() if getattr(self.notch, "mpris", None) else None
        if info and info["title"]:
            self._card(cr, x, y, 66)
            pb = self._icon("audio-x-generic-symbolic", 22)
            if pb:
                Gdk.cairo_set_source_pixbuf(cr, pb, x + 20, y + 22)
                cr.paint()
            cr.save()
            cr.rectangle(x + 54, y, CARD_W - 70, 66)
            cr.clip()
            text(cr, info["title"], "SF Pro Text Semibold 14px", x + 56, y + 14)
            text(cr, info["artist"] or "", "SF Pro Text 12px", x + 56, y + 35, (1, 1, 1, 0.6))
            cr.restore()
        return False
