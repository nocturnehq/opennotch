"""Liquid-glass dock background that waves with Plank's magnified icons."""
import math
import time

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

from . import design, extras  # noqa: E402
from .windowstate import coverage  # noqa: E402

PLANK_SCHEMA = "net.launchpad.plank.dock.settings"
PLANK_PATH = "/net/launchpad/plank/docks/dock1/"
PLANK_DBUS = ("net.launchpad.plank", "/net/launchpad/plank/dock1", "net.launchpad.plank.Items")
WIN_H = 160       # window height above the bottom edge (room for 200% zoom on 64 px icons)
CORNER_R = 20     # matches OpenNotch-Black TopRoundness
WAVE_IN_S = 0.22  # matches Plank's 200 ms DOCK_ZOOM_DURATION with a calm settle
WAVE_OUT_S = 0.34


def wave_bump(x, wave_x, radius, peak):
    """Smooth cos^2 wave height at horizontal position x."""
    if peak <= 0.0 or radius <= 0.0:
        return 0.0
    d = abs(x - wave_x)
    if d >= radius:
        return 0.0
    c = math.cos(math.pi * d / (2.0 * radius))
    return peak * c * c


def bar_edges(base_left, base_right, wave_x, icon_size, zoom_scale, amp):
    """Expand bar left/right edges outward under zoom, matching Plank's icon displacement."""
    if amp <= 0.0 or zoom_scale <= 1.0:
        return float(base_left), float(base_right)
    z_icon = icon_size * zoom_scale
    extra = (zoom_scale - 1.0) * amp

    def shift(dist):
        if dist <= 0.0:
            return 0.0
        d = min(dist, z_icon)
        return d * extra * (1.0 - (d / z_icon) / 3.0)

    return base_left - shift(wave_x - base_left), base_right + shift(base_right - wave_x)


def bar_path(cr, left, right, base_top, bottom, corner_r, wave_x, radius, peak):
    """Build the cairo path for the dock bar with a smooth wave along its top edge."""
    w = right - left
    if w <= 2 or bottom <= base_top + 1:
        cr.new_path()
        return
    r = min(float(corner_r), w / 2.0, max(2.0, (bottom - base_top) * 0.65))
    y_l = base_top - wave_bump(left + r, wave_x, radius, peak)
    y_r = base_top - wave_bump(right - r, wave_x, radius, peak)
    r_l = min(r, max(2.0, bottom - y_l))
    r_r = min(r, max(2.0, bottom - y_r))

    cr.new_path()
    cr.move_to(left, bottom)
    cr.line_to(left, y_l + r_l)
    cr.arc(left + r_l, y_l + r_l, r_l, math.pi, 1.5 * math.pi)

    x_start = left + r_l
    x_end = right - r_r
    if x_end > x_start:
        if peak > 0.25:
            step = 3.0
            x = x_start + step
            while x < x_end:
                cr.line_to(x, base_top - wave_bump(x, wave_x, radius, peak))
                x += step
        cr.line_to(x_end, y_r)

    cr.arc(right - r_r, y_r + r_r, r_r, 1.5 * math.pi, 2.0 * math.pi)
    cr.line_to(right, bottom)
    cr.close_path()


def blur_rects(left, right, base_top, bottom, corner_r, wave_x, radius, peak, scale=1):
    """Analytic _KDE_NET_WM_BLUR_BEHIND_REGION rectangles (physical px) for the waving dock bar."""
    if right - left <= 2 or bottom <= base_top + 1:
        return []
    rects = []
    r = min(float(corner_r), (right - left) / 2.0, max(2.0, (bottom - base_top) * 0.65))
    y_l = base_top - wave_bump(left + r, wave_x, radius, peak)
    y_r = base_top - wave_bump(right - r, wave_x, radius, peak)

    def add_span(x0, x1, y, h=1):
        ix0 = math.ceil(x0 * scale)
        ix1 = math.floor(x1 * scale)
        if ix1 <= ix0 or h <= 0:
            return
        if rects and rects[-4] == ix0 and rects[-2] == ix1 - ix0 and rects[-3] + rects[-1] == y:
            rects[-1] += h
        else:
            rects.extend((ix0, y, ix1 - ix0, h))

    top_most = base_top - peak
    y_start = max(0, math.ceil(top_most * scale))
    y_body = min(math.floor(bottom * scale), math.ceil((base_top + r) * scale))
    y_end = math.floor(bottom * scale)

    for py in range(y_start, y_body):
        y = (py + 0.5) / scale
        if y < base_top and peak > 0.25 and radius > 0.0:
            frac = min(1.0, max(0.0, (base_top - y) / peak))
            dx = radius * (2.0 / math.pi) * math.acos(math.sqrt(frac))
            xl = max(left, wave_x - dx)
            xr = min(right, wave_x + dx)
            # respect rounded top-left / top-right corners if the wave is near an end
            if y < y_l + r and xl < left + r:
                dy = r - max(0.0, y - y_l)
                xl = max(xl, left + r - math.sqrt(max(0.0, r * r - dy * dy)))
            if y < y_r + r and xr > right - r:
                dy = r - max(0.0, y - y_r)
                xr = min(xr, right - r + math.sqrt(max(0.0, r * r - dy * dy)))
            add_span(xl, xr, py, 1)
        elif y >= base_top:
            dl = r - max(0.0, y - y_l)
            dr = r - max(0.0, y - y_r)
            xl = left + (r - math.sqrt(max(0.0, r * r - dl * dl)) if dl > 0 else 0.0)
            xr = right - (r - math.sqrt(max(0.0, r * r - dr * dr)) if dr > 0 else 0.0)
            add_span(xl, xr, py, 1)

    if y_end > y_body:
        add_span(left, right, y_body, y_end - y_body)
    return rects


class DockBackground(Gtk.Window):
    """Transparent, click-through liquid-glass bar stacked directly under Plank."""

    def __init__(self, kde=None, reduce_motion=False, surface="glass"):
        super().__init__(title="OpenNotch Dock Background")
        self.kde = extras.KDE if kde is None else bool(kde)
        self.reduce_motion = bool(reduce_motion)
        self.surface = surface

        self.set_name("opennotch-dockbg")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_type_hint(Gdk.WindowTypeHint.DOCK)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_accept_focus(False)
        self.set_focus_on_map(False)
        self.stick()

        visual = self.get_screen().get_rgba_visual()
        if visual is not None:
            self.set_visual(visual)
        self.set_app_paintable(True)

        # Plank preferences
        self.icon_size = 44
        self.zoom_enabled = True
        self.zoom_percent = 150
        self.plank_position = "bottom"
        self.plank_settings = None
        self.has_plank = False
        self.base_h = self._default_bar_h()
        self._init_plank_settings()

        # X11 / KWin blur handles
        self.xdisp = None
        self.xroot = None
        self.plank_win = None
        self.plank_xid = None
        self.kwin_blur = None
        self.live_glass = False
        self.glass = None
        self._init_x11()

        # Bar geometry (in monitor-local coordinates; window sits at (mon.x, mon.y + mon.height - WIN_H))
        self.mon_geo = None
        self.base_left = 0.0
        self.base_right = 0.0
        self.hide_progress = 1.0  # 0 = fully shown, 1 = hidden

        # Wave animation state
        self.hovered = False
        self.wave_x = 0.0
        self.wave_amp = 0.0
        self.wave_anim = None  # (start_amp, target_amp, start_time, duration)
        self.tick_id = 0
        self.poll_id = 0
        self.closed = False
        self._last_fs_check = 0.0
        self._fullscreen = False
        self._last_dbus_check = 0.0
        self._last_stack_check = 0.0
        self._last_draw_key = None

        self.connect("draw", self._draw)
        self.connect("realize", self._on_realize)
        self.connect("map", self._on_map)

        self._place()
        self._poll()
        self.poll_id = GLib.timeout_add(110, self._poll)

    def _default_bar_h(self):
        # OpenNotch-Black: TopPadding=3 + BottomPadding=1 (tenths of IconSize) + border (~0.43 * icon_size)
        return self.icon_size + round(self.icon_size * 0.43)

    def _init_plank_settings(self):
        source = Gio.SettingsSchemaSource.get_default()
        if source is None or source.lookup(PLANK_SCHEMA, True) is None:
            return
        try:
            self.plank_settings = Gio.Settings.new_with_path(PLANK_SCHEMA, PLANK_PATH)
            self._read_plank_settings()
            self.plank_settings.connect("changed", lambda *_: self._read_plank_settings())
        except GLib.Error:
            self.plank_settings = None

    def _read_plank_settings(self):
        if self.plank_settings is None:
            return
        self.icon_size = max(16, self.plank_settings.get_int("icon-size"))
        self.zoom_enabled = bool(self.plank_settings.get_boolean("zoom-enabled"))
        self.zoom_percent = max(100, self.plank_settings.get_int("zoom-percent"))
        self.plank_position = self.plank_settings.get_string("position") or "bottom"
        if not self.has_plank:
            self.base_h = self._default_bar_h()

    def _init_x11(self):
        try:
            from Xlib import display as xdisplay
            from Xlib.error import DisplayError

            self.xdisp = xdisplay.Display(self.get_display().get_name())
            self.xroot = self.xdisp.screen().root
        except (ImportError, DisplayError, OSError):
            self.xdisp = None
            self.xroot = None

    def _monitor(self):
        display = self.get_display()
        return display.get_primary_monitor() or display.get_monitor(0)

    def _place(self):
        mon = self._monitor()
        if mon is None:
            return
        geo = mon.get_geometry()
        if self.mon_geo and (geo.x, geo.y, geo.width, geo.height) == (
            self.mon_geo.x, self.mon_geo.y, self.mon_geo.width, self.mon_geo.height
        ):
            return
        self.mon_geo = geo
        self.set_size_request(geo.width, WIN_H)
        self.resize(geo.width, WIN_H)
        self.move(geo.x, geo.y + geo.height - WIN_H)

    def _on_realize(self, *_):
        gdk_win = self.get_window()
        if gdk_win is not None:
            gdk_win.input_shape_combine_region(cairo.Region(), 0, 0)
        self._init_kwin_blur()

    def _on_map(self, *_):
        gdk_win = self.get_window()
        if gdk_win is not None:
            gdk_win.input_shape_combine_region(cairo.Region(), 0, 0)
            gdk_win.lower()
            self.get_display().flush()
        GLib.idle_add(self._lower_once)
        GLib.timeout_add(120, self._lower_once)

    def _lower_once(self):
        if self.closed or not self.get_visible():
            return False
        gdk_win = self.get_window()
        if gdk_win is not None:
            gdk_win.input_shape_combine_region(cairo.Region(), 0, 0)
            gdk_win.lower()
            self.get_display().flush()
        self._restack_below_plank()
        return False

    def _restack_below_plank(self):
        if self.xdisp is None or self.xroot is None or self.plank_xid is None:
            return
        gdk_win = self.get_window()
        if gdk_win is None:
            return
        try:
            gi.require_version("GdkX11", "3.0")
            from gi.repository import GdkX11
            from Xlib import X
            from Xlib.error import XError
            from Xlib.protocol import event as xevent

            my_xid = GdkX11.X11Window.get_xid(gdk_win)
            me = self.xdisp.create_resource_object("window", my_xid)
            ev = xevent.ClientMessage(
                window=me,
                client_type=self.xdisp.intern_atom("_NET_RESTACK_WINDOW"),
                data=(32, [2, self.plank_xid, X.Below, 0, 0]),
            )
            self.xroot.send_event(ev, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
            if self.plank_win is not None:
                self.plank_win.raise_window()
            self.xdisp.flush()
        except (ImportError, ValueError, XError):
            pass

    def _init_kwin_blur(self):
        if not self.kde or self.surface != "glass":
            return
        try:
            gi.require_version("GdkX11", "3.0")
            from gi.repository import GdkX11
            from Xlib.error import DisplayError
            from .kwinblur import KWinBlur

            gdk_win = self.get_window()
            if gdk_win is not None:
                self.kwin_blur = KWinBlur(self.get_display().get_name(), GdkX11.X11Window.get_xid(gdk_win))
                self.live_glass = self.kwin_blur.available
        except (ImportError, ValueError, TypeError, DisplayError):
            self.kwin_blur = None
            self.live_glass = False

    def _capture_glass(self):
        """Snapshot and blur the clean band just above the dock (Cinnamon / non-KWin fallback).

        Sampling above Plank's unhovered icons avoids baking blurry icon ghosts into the glass.
        """
        if self.mon_geo is None or self.surface != "glass" or self.live_glass:
            return
        w = self.mon_geo.width
        sample_h = 64
        y = max(self.mon_geo.y, self.mon_geo.y + self.mon_geo.height - self.base_h - sample_h - 12)
        try:
            pb = Gdk.pixbuf_get_from_window(Gdk.get_default_root_window(), self.mon_geo.x, y, w, sample_h)
            if pb is None:
                self.glass = None
                return
            small = pb.scale_simple(max(1, w // 14), max(1, sample_h // 8), GdkPixbuf.InterpType.BILINEAR)
            small = small.scale_simple(max(1, w // 5), max(1, sample_h // 3), GdkPixbuf.InterpType.BILINEAR)
            self.glass = small.scale_simple(w, WIN_H, GdkPixbuf.InterpType.BILINEAR)
        except (GLib.Error, TypeError):
            self.glass = None

    def _find_plank_window(self):
        if self.xdisp is None or self.xroot is None:
            return None
        from Xlib import X
        from Xlib.error import XError

        # First check EWMH client list (fast)
        try:
            atom = self.xdisp.intern_atom("_NET_CLIENT_LIST_STACKING")
            prop = self.xroot.get_full_property(atom, X.AnyPropertyType)
            if prop:
                for xid in reversed(prop.value):
                    try:
                        w = self.xdisp.create_resource_object("window", xid)
                        cls = w.get_wm_class()
                        if cls and "plank" in cls[0].lower():
                            if w.get_attributes().map_state == X.IsViewable:
                                return w
                    except XError:
                        continue
        except XError:
            pass

        # Fallback: walk root children
        def walk(win, depth=0):
            if depth > 2:
                return None
            try:
                cls = win.get_wm_class()
                if cls and "plank" in cls[0].lower() and win.get_attributes().map_state == X.IsViewable:
                    return win
                for ch in win.query_tree().children:
                    found = walk(ch, depth + 1)
                    if found is not None:
                        return found
            except XError:
                return None
            return None

        return walk(self.xroot)

    def _read_plank_geometry(self):
        """Return (left, right, input_h, visible) in monitor-local coords, or None if Plank isn't found."""
        if self.mon_geo is None or self.xdisp is None:
            return None
        from Xlib import X
        from Xlib.error import XError
        from Xlib.ext import shape

        if self.plank_win is None:
            self.plank_win = self._find_plank_window()
            self.plank_xid = self.plank_win.id if self.plank_win is not None else None
        if self.plank_win is None:
            return None

        try:
            if self.plank_win.get_attributes().map_state != X.IsViewable:
                self.plank_win = None
                self.plank_xid = None
                return None
            g = self.plank_win.get_geometry()
            t = self.plank_win.translate_coords(self.xroot, 0, 0)
            wx, wy = -t.x, -t.y
            rects = self.plank_win.shape_get_rectangles(shape.SK.Input).rectangles
        except XError:
            self.plank_win = None
            self.plank_xid = None
            return None

        if not rects:
            return None
        # Plank uses a single rectangle for its cursor/input region
        r = max(rects, key=lambda item: item.width * item.height)
        left = (wx + r.x) - self.mon_geo.x
        right = left + r.width
        return float(left), float(right), int(r.height), True

    def _dbus_bar_bounds(self):
        """Fallback: estimate left/right edges from Plank's D-Bus GetHoverPosition."""
        if self.mon_geo is None:
            return None
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

            def call(method, args=None, reply="(as)"):
                return bus.call_sync(*PLANK_DBUS, method, args, GLib.VariantType(reply),
                                     Gio.DBusCallFlags.NONE, 200, None).unpack()

            uris = call("GetPersistentApplications")[0] + call("GetTransientApplications")[0]
            xs = [call("GetHoverPosition", GLib.Variant("(s)", (u,)), "(iiib)")[0] for u in uris]
        except GLib.Error:
            return None
        if not xs:
            return None
        pad = round(self.icon_size * 1.25)
        return float(min(xs) - pad - self.mon_geo.x), float(max(xs) + pad - self.mon_geo.x)

    def _ensure_below_plank(self, now):
        if not self.get_visible() or self.plank_xid is None or now - self._last_stack_check < 0.3:
            return
        self._last_stack_check = now
        gdk_win = self.get_window()
        if gdk_win is None or self.xdisp is None:
            return
        try:
            gi.require_version("GdkX11", "3.0")
            from gi.repository import GdkX11
            from Xlib import X
            from Xlib.error import XError

            my_xid = GdkX11.X11Window.get_xid(gdk_win)
            prop = self.xroot.get_full_property(self.xdisp.intern_atom("_NET_CLIENT_LIST_STACKING"), X.AnyPropertyType)
            if prop:
                stack = list(prop.value)
                if my_xid in stack and self.plank_xid in stack and stack.index(my_xid) > stack.index(self.plank_xid):
                    gdk_win.lower()
                    self.get_display().flush()
                    self._restack_below_plank()
        except (ImportError, ValueError, XError):
            pass

    def _pointer_pos(self):
        pointer = self.get_display().get_default_seat().get_pointer()
        _, px, py = pointer.get_position()
        return px, py

    def _start_wave(self, target, now):
        if self.reduce_motion or not self.zoom_enabled or self.zoom_percent <= 100:
            self.wave_amp = 0.0
            self.wave_anim = None
            return
        dur = WAVE_IN_S if target > self.wave_amp else WAVE_OUT_S
        self.wave_anim = (self.wave_amp, float(target), now, dur)
        self._ensure_tick()

    def _ensure_tick(self):
        if not self.tick_id and not self.closed:
            self.tick_id = self.add_tick_callback(self._frame_tick)

    def _stop_tick(self):
        if self.tick_id:
            self.remove_tick_callback(self.tick_id)
            self.tick_id = 0

    def _update_state(self, now):
        self._place()
        if self.mon_geo is None or self.plank_position != "bottom":
            self._set_shown(False)
            return False

        # Check fullscreen at ~4 Hz
        if now - self._last_fs_check >= 0.25:
            self._last_fs_check = now
            _, self._fullscreen = coverage(self._monitor())
        if self._fullscreen:
            self._set_shown(False)
            return False

        info = self._read_plank_geometry()
        if info is None:
            # No Plank window found; try D-Bus fallback only once per 2 s
            if now - self._last_dbus_check >= 2.0:
                self._last_dbus_check = now
                bounds = self._dbus_bar_bounds()
                if bounds is None:
                    self.has_plank = False
                    self._set_shown(False)
                    return False
                self.base_left, self.base_right = bounds
                self.base_h = self._default_bar_h()
                self.hide_progress = 0.0
                self.has_plank = True
            elif not self.has_plank:
                self._set_shown(False)
                return False
        else:
            left, right, input_h, _ = info
            self.has_plank = True
            # When Plank is fully unhidden and unhovered, input_h == exact bar height and [left, right] == exact bar width
            if not self.hovered and input_h > 20:
                if abs(input_h - self._default_bar_h()) <= 12:
                    self.base_h = input_h
                self.base_left, self.base_right = left, right
            elif self.base_right <= self.base_left:
                self.base_left, self.base_right = left, right
            elif abs((right - left) - (self.base_right - self.base_left)) > self.icon_size * 0.6:
                # An app was opened or closed while hovered
                self.base_left, self.base_right = left, right

            # Track Plank's exact dodge/hide animation from its input_h
            if input_h <= 2:
                self.hide_progress = 1.0
            elif input_h >= self.base_h:
                self.hide_progress = 0.0
            else:
                self.hide_progress = 1.0 - max(0.0, min(1.0, (input_h - 1.0) / max(1.0, self.base_h - 1.0)))

        if self.hide_progress >= 0.99:
            self.hovered = False
            self.wave_amp = 0.0
            self.wave_anim = None
            self._set_shown(False)
            return False

        self._set_shown(True)
        self._ensure_below_plank(now)

        # Pointer tracking
        px, py = self._pointer_pos()
        lx = px - self.mon_geo.x
        bottom_y = self.mon_geo.y + self.mon_geo.height
        zoom_scale = self.zoom_percent / 100.0 if (self.zoom_enabled and not self.reduce_motion) else 1.0
        max_bump = (zoom_scale - 1.0) * self.icon_size
        cur_left, cur_right = bar_edges(self.base_left, self.base_right, self.wave_x,
                                        self.icon_size, zoom_scale, self.wave_amp)
        hover_band = self.base_h + (max_bump + 8 if self.hovered else 6)
        over = (self.hide_progress < 0.25 and
                cur_left - 8 <= lx <= cur_right + 8 and
                bottom_y - hover_band <= py <= bottom_y)

        if over:
            self.wave_x = max(self.base_left - 12, min(self.base_right + 12, float(lx)))
            if not self.hovered:
                self.hovered = True
                self._start_wave(1.0, now)
        elif self.hovered:
            self.hovered = False
            self._start_wave(0.0, now)

        # Advance wave animation
        if self.wave_anim is not None:
            start_a, target_a, t0, dur = self.wave_anim
            t = min(1.0, max(0.0, (now - t0) / dur))
            if target_a > start_a:
                eased = design.spring(t)
            else:
                eased = design.ease_out_quint(t)
            self.wave_amp = max(0.0, min(1.08, start_a + (target_a - start_a) * eased))
            if t >= 1.0:
                self.wave_amp = target_a
                self.wave_anim = None

        return over or self.wave_anim is not None or (0.0 < self.hide_progress < 1.0)

    def _set_shown(self, visible):
        if visible == self.get_visible():
            return
        if visible:
            if not self.live_glass and self.surface == "glass":
                self._capture_glass()
            self.show_all()
            gdk_win = self.get_window()
            if gdk_win is not None:
                gdk_win.input_shape_combine_region(cairo.Region(), 0, 0)
                gdk_win.lower()
                self.get_display().flush()
            GLib.idle_add(self._lower_once)
            GLib.timeout_add(120, self._lower_once)
            self.queue_draw()
        else:
            if self.kwin_blur is not None:
                self.kwin_blur.set_rects(None)
            self.hide()

    def _draw_key(self):
        return (round(self.base_left), round(self.base_right), self.base_h,
                round(self.hide_progress, 3), round(self.wave_amp, 3), round(self.wave_x),
                self.zoom_enabled, self.zoom_percent, self.reduce_motion)

    def _poll(self):
        if self.closed:
            return False
        now = time.monotonic()
        active = self._update_state(now)
        key = self._draw_key()
        if active:
            self._ensure_tick()
            self._last_draw_key = key
            self.queue_draw()
        elif self.get_visible() and key != self._last_draw_key:
            self._last_draw_key = key
            self.queue_draw()
        return True

    def _frame_tick(self, _widget, _clock):
        if self.closed:
            self.tick_id = 0
            return False
        now = time.monotonic()
        active = self._update_state(now)
        key = self._draw_key()
        if self.get_visible() and (active or key != self._last_draw_key):
            self._last_draw_key = key
            self.queue_draw()
        if not active:
            self.tick_id = 0
            return False
        return True

    def _draw(self, _widget, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        if not self.has_plank or self.base_right <= self.base_left or self.hide_progress >= 0.99:
            if self.kwin_blur is not None:
                self.kwin_blur.set_rects(None)
            return False

        zoom_scale = self.zoom_percent / 100.0 if (self.zoom_enabled and not self.reduce_motion) else 1.0
        amp = 0.0 if self.reduce_motion else self.wave_amp * (1.0 - self.hide_progress)
        peak = max(0.0, (zoom_scale - 1.0) * self.icon_size * amp)
        radius = self.icon_size * 2.6
        left, right = bar_edges(self.base_left, self.base_right, self.wave_x, self.icon_size, zoom_scale, amp)

        slide_y = self.base_h * self.hide_progress
        base_top = WIN_H - self.base_h + slide_y
        bottom = float(WIN_H)
        if base_top >= bottom - 1:
            if self.kwin_blur is not None:
                self.kwin_blur.set_rects(None)
            return False

        bar_path(cr, left, right, base_top, bottom, CORNER_R, self.wave_x, radius, peak)

        # KWin live blur region
        if self.kwin_blur is not None:
            if self.surface == "glass" and self.live_glass:
                rects = blur_rects(left, right, base_top, bottom, CORNER_R,
                                   self.wave_x, radius, peak, self.get_scale_factor())
                self.kwin_blur.set_rects(rects)
            else:
                self.kwin_blur.set_rects(None)

        glassy = self.surface == "glass"
        cr.save()
        cr.clip_preserve()
        if glassy and not self.live_glass and self.glass is not None:
            Gdk.cairo_set_source_pixbuf(cr, self.glass, 0, 0)
            cr.paint()

        top_y = max(0.0, base_top - peak)
        g = cairo.LinearGradient(0, top_y, 0, bottom)
        if glassy:
            if self.live_glass or self.glass is not None:
                g.add_color_stop_rgba(0, 0.048, 0.050, 0.056, 0.64)
                g.add_color_stop_rgba(1, *design.INK, 0.78)
            else:
                g.add_color_stop_rgba(0, 0.048, 0.050, 0.056, 0.84)
                g.add_color_stop_rgba(1, *design.INK, 0.92)
        else:
            g.add_color_stop_rgba(0, *design.INK, 0.96)
            g.add_color_stop_rgba(1, *design.INK, 0.98)
        cr.set_source(g)
        cr.paint()

        # Soft liquid-glass top sheen (brightens gently over the wave)
        sheen = cairo.LinearGradient(0, top_y, 0, min(bottom, base_top + self.base_h * 0.45))
        sheen.add_color_stop_rgba(0, *design.CHAMPAGNE_RGB, 0.08 if glassy else 0.03)
        sheen.add_color_stop_rgba(1, *design.CHAMPAGNE_RGB, 0.0)
        cr.set_source(sheen)
        cr.paint()
        cr.restore()

        # Faint white rim along the top/wave and sides
        rim = cairo.LinearGradient(0, top_y, 0, bottom)
        rim.add_color_stop_rgba(0, *design.CHAMPAGNE_RGB, 0.28 if glassy else 0.14)
        rim.add_color_stop_rgba(0.6, *design.CHAMPAGNE_RGB, 0.14 if glassy else 0.09)
        rim.add_color_stop_rgba(1, *design.CHAMPAGNE_RGB, 0.06)
        cr.set_source(rim)
        cr.set_line_width(1.0)
        cr.stroke()
        return False

    def close(self):
        self.closed = True
        self._stop_tick()
        if self.poll_id:
            GLib.source_remove(self.poll_id)
            self.poll_id = 0
        if self.kwin_blur is not None:
            try:
                self.kwin_blur.set_rects(None)
            except Exception:
                pass
        if self.xdisp is not None:
            try:
                self.xdisp.close()
            except Exception:
                pass
            self.xdisp = None
        self.destroy()
