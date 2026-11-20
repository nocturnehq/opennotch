"""Custom Alt+Tab for OpenNotch: Ring, Fan or Flip 3D, drawn with cairo over a dimmed screen."""
import math
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkX11", "3.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GdkX11, GLib, Gtk, Pango, PangoCairo  # noqa: E402

from . import design  # noqa: E402

try:
    gi.require_version("Wnck", "3.0")
    from gi.repository import Wnck
except (ImportError, ValueError):
    Wnck = None

CARD_W = 300
STEP_SECONDS = 0.18


def switchable(windows):
    """Normal, top-level, taskbar windows; transient dialogs and panels are left out."""
    return [w for w in windows if not w.is_skip_tasklist() and w.get_transient() is None
            and w.get_window_type() == Wnck.WindowType.NORMAL]


def layout(style, d, n, cx, cy):
    """Card placement for offset d from the selection: (x_centre, y_centre, scale, alpha, shear)."""
    if style == "ring":
        angle = d * 2 * math.pi / max(n, 3)
        depth = (math.cos(angle) + 1) / 2  # 1 = front
        return cx + 360 * math.sin(angle), cy - 50 * (1 - depth), 0.55 + 0.45 * depth, 0.3 + 0.7 * depth, 0
    if style == "fan":
        angle = d * 0.28
        return cx + 650 * math.sin(angle), cy + 650 * (1 - math.cos(angle)), 1 - 0.08 * min(abs(d), 4), \
            max(0.0, 1 - 0.18 * abs(d)), 0
    # flip: the selection in front, the rest receding up and to the right; passed cards fade toward you
    if d < 0:
        return cx + 40 * d, cy - 30 * d, 1 - 0.3 * d, max(0.0, 1 + 1.5 * d), -0.12
    return cx + 90 * d, cy - 55 * d, max(0.35, 1 - 0.13 * d), max(0.0, 1 - 0.16 * d), -0.12


def draw_order(style, offsets):
    """Indices back to front."""
    if style == "ring":
        return sorted(range(len(offsets)), key=lambda i: math.cos(offsets[i] * 2 * math.pi / max(len(offsets), 3)))
    if style == "fan":
        return sorted(range(len(offsets)), key=lambda i: -abs(offsets[i]))
    return sorted(range(len(offsets)), key=lambda i: -offsets[i] if offsets[i] >= 0 else -100 - offsets[i])


class AltTab(Gtk.Window):
    def __init__(self, style="ring", reduce_motion=False):
        super().__init__(type=Gtk.WindowType.POPUP)
        self.style, self.reduce_motion = style, reduce_motion
        visual = self.get_screen().get_rgba_visual()
        if visual is not None:
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.add_events(Gdk.EventMask.KEY_PRESS_MASK | Gdk.EventMask.KEY_RELEASE_MASK)
        self.connect("draw", self._draw)
        self.connect("key-press-event", self._key_press)
        self.connect("key-release-event", self._key_release)
        self.windows, self.cards, self.sel, self.pos = [], [], 0, 0.0
        self.anim, self.tick = None, 0
        self.open = False

    # ---------------------------------------------------------------- entry points
    def step(self, by=1):
        """Alt+Tab pressed: open on the previous window, or move on when already open."""
        if self.open:
            self._move(by)
            return
        if Wnck is None:
            return
        screen = Wnck.Screen.get_default()
        screen.force_update()
        self.windows = list(reversed(switchable(screen.get_windows_stacked())))  # most recent first
        if len(self.windows) < 2:
            if self.windows:
                self.windows[0].activate(Gtk.get_current_event_time())
            return
        self.cards = [self._thumbnail(w) for w in self.windows]
        self.sel, self.pos = 1, 1.0
        display = Gdk.Display.get_default()
        _s, px, py = display.get_default_seat().get_pointer().get_position()[:3]
        mon = display.get_monitor_at_point(px, py).get_geometry()
        self.move(mon.x, mon.y)
        self.resize(mon.width, mon.height)
        self.show_all()
        self.open = True
        seat = display.get_default_seat()
        seat.grab(self.get_window(), Gdk.SeatCapabilities.KEYBOARD, False, None, None, None, None)
        state = Gdk.Keymap.get_for_display(display).get_modifier_state()
        if not state & Gdk.ModifierType.MOD1_MASK:  # Alt already let go: a quick tap switches back
            self.commit()

    def commit(self):
        window = self.windows[self.sel] if self.open else None
        # KWin's focus-stealing prevention ignores a zero timestamp, so ask the X server for "now"
        stamp = Gtk.get_current_event_time() or (GdkX11.x11_get_server_time(self.get_window()) if self.open else 0)
        self.cancel()
        if window is not None:
            window.activate(stamp)

    def cancel(self):
        if not self.open:
            return
        self.open = False
        Gdk.Display.get_default().get_default_seat().ungrab()
        if self.tick:
            self.remove_tick_callback(self.tick)
            self.tick = 0
        self.hide()
        self.cards = []

    # ---------------------------------------------------------------- keys
    def _key_press(self, _w, event):
        name = Gdk.keyval_name(event.keyval) or ""
        if name == "Escape":
            self.cancel()
        elif name in ("ISO_Left_Tab", "Left", "Up") or name == "Tab" and event.state & Gdk.ModifierType.SHIFT_MASK:
            self._move(-1)
        elif name in ("Tab", "Right", "Down"):
            self._move(1)
        elif name in ("Return", "KP_Enter", "space"):
            self.commit()
        return True

    def _key_release(self, _w, event):
        if (Gdk.keyval_name(event.keyval) or "") in ("Alt_L", "Alt_R", "Meta_L", "Meta_R"):
            self.commit()
        return True

    # ---------------------------------------------------------------- motion and drawing
    def _move(self, by):
        self.sel = (self.sel + by) % len(self.windows)
        target = self.pos + by  # keep moving the same way across the wrap
        if self.reduce_motion:
            self.pos = float(self.sel)
            self.queue_draw()
            return
        self.anim = (self.pos, target, time.monotonic())
        if not self.tick:
            self.tick = self.add_tick_callback(self._on_tick)

    def _on_tick(self, *_):
        start, end, t0 = self.anim
        p = min(1.0, (time.monotonic() - t0) / STEP_SECONDS)
        self.pos = start + (end - start) * (1 - (1 - p) ** 3)
        self.queue_draw()
        if p >= 1.0:
            self.pos = float(self.sel)
            self.tick = 0
            return False
        return True

    @staticmethod
    def _thumbnail(window):
        pb = None
        if not window.is_minimized():
            try:
                gdk_win = GdkX11.X11Window.foreign_new_for_display(Gdk.Display.get_default(), window.get_xid())
                w, h = gdk_win.get_width(), gdk_win.get_height()
                pb = Gdk.pixbuf_get_from_window(gdk_win, 0, 0, w, h) if w > 0 and h > 0 else None
            except (TypeError, GLib.Error):
                pb = None
        if pb is None:
            return None, window.get_icon()
        return pb.scale_simple(CARD_W, max(1, min(int(pb.get_height() * CARD_W / pb.get_width()), 220)), 2), None

    def _draw(self, _w, cr):
        width, height = self.get_allocated_width(), self.get_allocated_height()
        cr.set_source_rgba(*design.INK, 0.72)
        cr.paint()
        n = len(self.cards)
        offsets = []
        for i in range(n):
            d = (i - self.pos) % n
            offsets.append(d - n if d > n / 2 else d)  # nearest way round
        cx, cy = width / 2, height / 2
        for i in draw_order(self.style, offsets):
            x, y, scale, alpha, shear = layout(self.style, offsets[i], n, cx, cy)
            if alpha <= 0.01:
                continue
            thumb, icon = self.cards[i]
            w, h = (thumb.get_width(), thumb.get_height()) if thumb else (CARD_W, 180)
            cr.save()
            cr.translate(x, y)
            if self.style == "fan":
                cr.rotate(offsets[i] * 0.28)
            if shear:
                cr.transform(cairo_matrix(shear))
            cr.scale(scale, scale)
            cr.translate(-w / 2, -h / 2)
            rounded(cr, w, h, 18)
            cr.save()
            cr.clip()
            cr.set_source_rgba(0.05, 0.05, 0.06, alpha)
            cr.paint()
            if thumb is not None:
                Gdk.cairo_set_source_pixbuf(cr, thumb, 0, 0)
                cr.paint_with_alpha(alpha)
            elif icon is not None:
                Gdk.cairo_set_source_pixbuf(cr, icon, (w - icon.get_width()) / 2, (h - icon.get_height()) / 2)
                cr.paint_with_alpha(alpha)
            cr.restore()
            rounded(cr, w, h, 18)
            selected = abs(offsets[i]) < 0.5
            cr.set_source_rgba(*design.CHAMPAGNE_RGB, (0.95 if selected else 0.14) * alpha)
            cr.set_line_width((2.2 if selected else 1.0) / scale)
            cr.stroke()
            cr.restore()
        title = self.windows[self.sel].get_name() if self.windows else ""
        layout_ = self.create_pango_layout(title)
        layout_.set_font_description(Pango.FontDescription("SF Pro Display Semibold 14"))
        layout_.set_width((width - 40) * Pango.SCALE)
        layout_.set_ellipsize(Pango.EllipsizeMode.END)
        tw, th = layout_.get_pixel_size()
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.95)
        cr.move_to(cx - tw / 2, cy + 190)
        PangoCairo.show_layout(cr, layout_)
        return True


def cairo_matrix(shear):
    import cairo

    return cairo.Matrix(1, shear, 0, 1, 0, 0)


def rounded(cr, w, h, r):
    cr.new_sub_path()
    cr.arc(w - r, r, r, -math.pi / 2, 0)
    cr.arc(w - r, h - r, r, 0, math.pi / 2)
    cr.arc(r, h - r, r, math.pi / 2, math.pi)
    cr.arc(r, r, r, math.pi, 1.5 * math.pi)
    cr.close_path()
