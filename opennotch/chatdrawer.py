"""Floating Twitch/YouTube live chat drawer in black + liquid glass."""
import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import design  # noqa: E402

MAX_LINES = 50


class ChatDrawer(Gtk.Window):
    """Draggable floating overlay for live Twitch and YouTube chat."""

    def __init__(self, font="SF Pro Text", opacity=86, text_size=11):
        super().__init__(title="OpenNotch Chat")
        self.bg_alpha = max(0.4, min(1.0, opacity / 100.0))
        self.set_name("opennotch-chat")
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_accept_focus(False)
        self.stick()
        self.set_default_size(320, 360)

        visual = self.get_screen().get_rgba_visual()
        if visual is not None:
            self.set_visual(visual)
        self.set_app_paintable(True)

        prov = Gtk.CssProvider()
        prov.load_from_data((
            f"#opennotch-chat * {{ color: #ffffff; font-family: '{font}', 'SF Pro Text', sans-serif; font-size: {int(text_size)}px; }}"
            "#opennotch-chat .head { font-family: 'SF Pro Display', sans-serif; font-size: 14px; font-weight: 600; }"
            "#opennotch-chat .dim { color: rgba(255,255,255,0.55); }"
            "#opennotch-chat button { background: rgba(255,255,255,0.08); border: none; border-radius: 99px; padding: 3px 9px; }"
            "#opennotch-chat button:hover { background: rgba(255,255,255,0.16); }"
        ).encode())
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=12)
        head = Gtk.Box(spacing=8)
        title = Gtk.Label(label="Live chat", xalign=0)
        title.get_style_context().add_class("head")
        close = Gtk.Button(label="×")
        close.set_can_focus(False)
        close.connect("clicked", lambda *_: self.hide())
        head.pack_start(title, True, True, 0)
        head.pack_end(close, False, False, 0)
        outer.pack_start(head, False, False, 0)

        self.feed = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.empty = Gtk.Label(label="Waiting for messages…", xalign=0)
        self.empty.get_style_context().add_class("dim")
        self.feed.pack_start(self.empty, False, False, 0)

        self.scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.scroll.add(self.feed)
        outer.pack_start(self.scroll, True, True, 0)
        self.add(outer)

        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("draw", self._draw)
        self.connect("button-press-event", self._drag)

        mon = self.get_display().get_primary_monitor() or self.get_display().get_monitor(0)
        if mon is not None:
            g = mon.get_geometry()
            self.move(g.x + g.width - 344, g.y + 80)

    def _drag(self, _w, ev):
        if ev.button == 1:
            self.begin_move_drag(ev.button, int(ev.x_root), int(ev.y_root), ev.time)
            return True
        return False

    def _draw(self, _w, cr):
        w, h = self.get_allocated_width(), self.get_allocated_height()
        r = 18.0
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        cr.new_path()
        cr.arc(w - r, r, r, -1.5708, 0)
        cr.arc(w - r, h - r, r, 0, 1.5708)
        cr.arc(r, h - r, r, 1.5708, 3.1416)
        cr.arc(r, r, r, 3.1416, 4.7124)
        cr.close_path()
        cr.set_source_rgba(*design.INK, self.bg_alpha)
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, 0.16)
        cr.set_line_width(1.0)
        cr.stroke()
        return False

    def push(self, source, author, text):
        if self.empty.get_parent() is not None:
            self.feed.remove(self.empty)
        row = Gtk.Label(xalign=0, wrap=True, wrap_mode=2)
        row.set_markup(f"<b>{GLib.markup_escape_text(author)}</b>  {GLib.markup_escape_text(text)}")
        self.feed.pack_start(row, False, False, 0)
        children = self.feed.get_children()
        if len(children) > MAX_LINES:
            children[0].destroy()
        row.show()
        adj = self.scroll.get_vadjustment()
        adj.set_value(adj.get_upper())

    def toggle(self):
        if self.get_visible():
            self.hide()
        else:
            self.show_all()
