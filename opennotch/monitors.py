"""Idle islands on secondary displays, backed by one shared card and app state."""
import math

import cairo
import gi

gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo

from .windowstate import coverage


def resting_bounds(screen, w, h, *, position, side, gap, margin, fraction, shoulder):
    """Position the resting shape inside one monitor, excluding its concave shoulders."""
    if side:
        x = screen.x + (gap if position == "left" else screen.width - w - gap)
        target = round(screen.height * fraction / 100 - h / 2)
        y = screen.y + max(shoulder, min(screen.height - h - shoulder, target))
    else:
        inset = margin + shoulder
        x = screen.x + {"left": inset, "right": screen.width - w - inset,
                        "center": (screen.width - w) // 2}[position]
        y = screen.y + gap
    return x, y


class IdleIsland(Gtk.Window):
    def __init__(self, app, monitor):
        super().__init__(title="OpenNotch · Display")
        self.app = app
        self.monitor = monitor
        self.set_name("notch-replica")
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
        self.connect("realize", lambda *_: self.input_shape_combine_region(cairo.Region()))
        self.connect("draw", self._draw)
        self.last_frame = None
        self.hitbox = None

    def update(self):
        app = self.app
        maximized, fullscreen = coverage(self.monitor)
        status = app._capture_status_visible()
        hidden = not status and (app.cfg["hidden_until_hover"] or
                                 bool(app.cfg["hide_in_fullscreen"] and fullscreen))
        slim = not status and (app.cfg["slim_strip"] and (maximized or fullscreen))
        geometry = app.geo["pill"]
        w, h, r = app._edge_strip(geometry) if slim or hidden else geometry
        shoulder = app.shoulder
        xpad, ypad = (0, shoulder) if app.side else (shoulder, 0)
        bounds = self.monitor.get_geometry()
        x, y = resting_bounds(bounds, w, h, position=app.position, side=app.side, gap=app.gap,
                              margin=app.cfg["edge_margin"], fraction=app.cfg["side_position"],
                              shoulder=shoulder)
        if app.cfg["hide_in_fullscreen"] and fullscreen:
            self.hitbox = None
        else:
            self.hitbox = Gdk.Rectangle()
            self.hitbox.x, self.hitbox.y = x - xpad, y - ypad
            self.hitbox.width, self.hitbox.height = math.ceil(w) + 2 * xpad, math.ceil(h) + 2 * ypad
        summary = app._replica_summary() if not slim and not hidden else ""
        pet = (not summary and not hidden and not slim and app.pill_pet is not None and
               app.pill_pet.get_visible())
        frame = (x, y, w, h, r, xpad, ypad, summary, pet)
        if frame != self.last_frame:
            self.last_frame = frame
            self.set_size_request(math.ceil(w) + 2 * xpad, math.ceil(h) + 2 * ypad)
            self.move(x - xpad, y - ypad)
            self.queue_draw()
        visible = not hidden and app.get_visible()
        if visible != self.get_visible():
            self.set_visible(visible)
            if visible:
                self.move(x - xpad, y - ypad)

    def contains(self, x, y):
        b = self.hitbox
        return b is not None and b.x <= x < b.x + b.width and b.y <= y < b.y + b.height

    def _draw(self, _widget, cr):
        if not self.last_frame:
            return True
        _, _, w, h, r, x, y, text, pet = self.last_frame
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        self.app._surface_path(cr, x, y, w, h, r)
        cr.set_source_rgb(0.043, 0.043, 0.047)
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, 0.28 if self.app.cfg["higher_contrast"] else 0.09)
        cr.set_line_width(1)
        cr.stroke()
        if pet:
            from .pet import paint_pet

            cr.save()
            cr.translate(x, y)
            paint_pet(cr, self.app.cfg["pet"], w, h, vertical=self.app.side)
            cr.restore()
        if text:
            cr.save()
            cr.translate(x + w / 2, y + h / 2)
            if self.app.side:
                cr.rotate(-math.pi / 2 if self.app.position == "left" else math.pi / 2)
            layout = PangoCairo.create_layout(cr)
            layout.set_font_description(Pango.FontDescription.from_string(
                f"{self.app.cfg['font']} {max(8, self.app.scaled(10))}"))
            layout.set_text(text, -1)
            available = h if self.app.side else w
            layout.set_width(max(1, int(available - 16)) * Pango.SCALE)
            layout.set_alignment(Pango.Alignment.CENTER)
            layout.set_ellipsize(Pango.EllipsizeMode.END)
            _, th = layout.get_pixel_size()
            cr.move_to(-max(1, available - 16) / 2, -th / 2)
            cr.set_source_rgb(0.96, 0.96, 0.97)
            PangoCairo.show_layout(cr, layout)
            cr.restore()
        return True


class DisplayMirrors:
    def __init__(self, app):
        self.app = app
        self.display = app.get_display()
        self.replicas = {}
        self.pending = None
        self.open_timer = 0
        self.screen = app.get_screen()
        self.screen.connect("monitors-changed", self.sync)
        app.connect("notify::visible", self.sync)
        self.sync()
        GLib.timeout_add(120, self._poll)

    def sync(self, *_):
        display = self.display
        monitors = [display.get_monitor(index) for index in range(display.get_n_monitors())]
        if self.app.monitor not in monitors:
            self.app._place_window()
        others = {monitor for monitor in monitors if monitor is not None and monitor != self.app.monitor}
        for monitor in self.replicas.keys() - others:
            self.replicas.pop(monitor).destroy()
        if self.pending not in others:
            self._cancel_pending()
        for monitor in others - self.replicas.keys():
            self.replicas[monitor] = IdleIsland(self.app, monitor)
        for replica in self.replicas.values():
            replica.update()

    def _cancel_pending(self):
        self.pending = None
        if self.open_timer:
            GLib.source_remove(self.open_timer)
            self.open_timer = 0

    def _poll(self):
        app = self.app
        for replica in self.replicas.values():
            replica.update()
        if not app.get_visible() or app.dragging:
            self._cancel_pending()
            return GLib.SOURCE_CONTINUE
        pointer = self.display.get_default_seat().get_pointer()
        _, x, y = pointer.get_position()
        monitor = next((key for key, replica in self.replicas.items() if replica.contains(x, y)), None)
        if self.pending != monitor:
            self._cancel_pending()
        if monitor is not None and not self.open_timer:
            self.pending = monitor
            self.open_timer = GLib.timeout_add(max(1, app.cfg["hover_delay_ms"]), self._open)
        return GLib.SOURCE_CONTINUE

    def _open(self):
        monitor = self.pending
        self.open_timer = 0
        self.pending = None
        replica = self.replicas.get(monitor)
        pointer = self.display.get_default_seat().get_pointer()
        _, x, y = pointer.get_position()
        if replica is not None and replica.contains(x, y) and self.app.get_visible():
            self.app._transfer_to_monitor(monitor)
            self.sync()
        return GLib.SOURCE_REMOVE
