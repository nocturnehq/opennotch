"""Window previews over the Plank dock: rest the pointer on an app's icon to see and pick its windows."""
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkX11", "3.0")
from gi.repository import Gdk, GdkX11, Gio, GLib, Gtk  # noqa: E402

from . import design  # noqa: E402
from .taskkeys import window_keys  # noqa: E402

try:
    gi.require_version("Wnck", "3.0")
    from gi.repository import Wnck
except (ImportError, ValueError):
    Wnck = None

PLANK = ("net.launchpad.plank", "/net/launchpad/plank/dock1", "net.launchpad.plank.Items")
BAND = 90       # px from the bottom edge where the dock lives
REACH = 30      # px either side of an icon's centre that counts as on it
REST_MS = 450   # how long the pointer rests on an icon before the previews show
THUMB_W = 200

CSS = ("""
#previews { background: rgba(5,5,6,0.94); border-radius: 18px; border: 1px solid %(hair)s; }
#previews button { background: transparent; border: 1px solid transparent; box-shadow: none; padding: 8px; border-radius: 12px;
  transition: background-color %(fast)s %(ease)s, border-color %(fast)s %(ease)s; }
#previews button:hover, #previews button:focus { background: %(fillh)s; border-color: rgba(255,255,255,0.28); }
#previews label { color: %(t2)s; font-size: 11px; font-weight: 600; }
#previews button:hover label { color: %(text)s; }
""" % dict(fast=design.CSS_FAST, ease=design.CSS_EASE, fillh=design.FILL_HOVER, hair=design.HAIRLINE_STRONG,
           t2=design.TEXT_2, text=design.TEXT)).encode()


def nearest_item(px, anchors, reach=REACH):
    """anchors: [(uri, x)] → the uri whose icon centre is within reach of px, else None."""
    best = min(anchors, key=lambda a: abs(a[1] - px), default=None)
    return best[0] if best is not None and abs(best[1] - px) <= reach else None


class DockPreviews:
    def __init__(self, font="Geist"):
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.anchors, self.anchors_at = [], 0
        self.hover_uri, self.hover_since, self.shown_uri = None, 0, None
        self.popup = None
        self.timer = 0
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS + f"#previews label {{ font-family: '{font}'; }}".encode())
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def start(self):
        if Wnck is not None and not self.timer:
            self.timer = GLib.timeout_add(150, self._poll)

    def close(self):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0
        self._hide()

    def _call(self, method, args=None, reply="(as)"):
        return self.bus.call_sync(PLANK[0], PLANK[1], PLANK[2], method, args,
                                  GLib.VariantType(reply), Gio.DBusCallFlags.NONE, 300, None).unpack()

    def _refresh_anchors(self):
        now = GLib.get_monotonic_time()
        if now - self.anchors_at < 2_000_000:
            return
        self.anchors_at, anchors = now, []
        try:
            uris = self._call("GetPersistentApplications")[0] + self._call("GetTransientApplications")[0]
            for uri in uris:
                x, _y, _pos, ok = self._call("GetHoverPosition", GLib.Variant("(s)", (uri,)), "(iiib)")
                if ok:
                    anchors.append((uri, x))
        except GLib.Error:
            pass  # Plank not running: no dock, no previews
        self.anchors = anchors

    def _poll(self):
        display = Gdk.Display.get_default()
        _screen, px, py = display.get_default_seat().get_pointer().get_position()[:3]
        mon = display.get_monitor_at_point(px, py).get_geometry()
        if self.popup is not None and self._inside_popup(px, py):
            return True
        uri = None
        if py >= mon.y + mon.height - BAND:
            self._refresh_anchors()
            uri = nearest_item(px, self.anchors)
        now = GLib.get_monotonic_time()
        if uri != self.hover_uri:
            self.hover_uri, self.hover_since = uri, now
            if uri != self.shown_uri:
                self._hide()
        elif uri and uri != self.shown_uri and now - self.hover_since >= REST_MS * 1000:
            self._show(uri, dict(self.anchors)[uri], mon)
        return True

    def _inside_popup(self, px, py):
        x, y = self.popup.get_position()
        w, h = self.popup.get_size()
        return x - 8 <= px <= x + w + 8 and y - 8 <= py <= y + h + BAND

    def _windows(self, uri):
        path = Gio.File.new_for_uri(uri).get_path()
        app = Gio.DesktopAppInfo.new_from_filename(path) if path else None
        if app is None:
            return []
        keys = window_keys(app)
        screen = Wnck.Screen.get_default()
        screen.force_update()
        return [w for w in screen.get_windows()
                if not w.is_skip_tasklist() and {(w.get_class_group_name() or "").lower(),
                                                 (w.get_class_instance_name() or "").lower()} & keys]

    @staticmethod
    def _thumbnail(window):
        if not window.is_minimized():
            try:
                gdk_win = GdkX11.X11Window.foreign_new_for_display(Gdk.Display.get_default(), window.get_xid())
                w, h = gdk_win.get_width(), gdk_win.get_height()
                pb = Gdk.pixbuf_get_from_window(gdk_win, 0, 0, w, h) if w > 0 and h > 0 else None
                if pb is not None:
                    th = max(1, int(h * THUMB_W / w))
                    return Gtk.Image.new_from_pixbuf(pb.scale_simple(THUMB_W, min(th, 160), 2))  # BILINEAR
            except (TypeError, GLib.Error):
                pass
        icon = window.get_icon()
        return Gtk.Image.new_from_pixbuf(icon) if icon is not None else Gtk.Image()

    def _show(self, uri, anchor_x, mon):
        windows = self._windows(uri)
        self._hide()
        if not windows:
            return
        self.shown_uri = uri
        pop = self.popup = Gtk.Window(type=Gtk.WindowType.POPUP)
        pop.set_name("previews")
        visual = pop.get_screen().get_rgba_visual()
        if visual is not None:
            pop.set_visual(visual)
        row = Gtk.Box(spacing=6, margin=8)
        for window in windows[:6]:
            button = Gtk.Button()
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            box.pack_start(self._thumbnail(window), False, False, 0)
            title = Gtk.Label(label=window.get_name() or "", xalign=0.5, max_width_chars=22)
            title.set_ellipsize(3)
            box.pack_start(title, False, False, 0)
            button.add(box)
            button.connect("clicked", lambda _b, w=window: (w.activate(Gtk.get_current_event_time()), self._hide()))
            row.pack_start(button, False, False, 0)
        pop.add(row)
        pop.show_all()
        w, h = pop.get_size()
        x = max(mon.x + 8, min(anchor_x - w // 2, mon.x + mon.width - w - 8))
        pop.move(x, mon.y + mon.height - BAND - h - 6)

    def _hide(self):
        if self.popup is not None:
            self.popup.destroy()
        self.popup, self.shown_uri = None, None
