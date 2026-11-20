"""A bottom-edge clock and status area that does not reserve screen space."""
import glob
import os
import time

import gi
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk

from .windowstate import coverage

WATCHER = "org.kde.StatusNotifierWatcher"
ITEM = "org.kde.StatusNotifierItem"
MENU = "com.canonical.dbusmenu"
FLAGS = Gio.DBusProxyFlags.DO_NOT_AUTO_START


def cached(proxy, name, default=None):
    value = proxy.get_cached_property(name)
    return value.unpack() if value is not None else default


def set_icon(image, name):
    if name and os.path.isabs(name):
        try:
            image.set_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(name, 16, 16, True))
            return
        except GLib.Error:
            pass
    image.set_from_icon_name(name or "application-x-executable-symbolic", Gtk.IconSize.MENU)
    image.set_pixel_size(16)


class StatusStrip(Gtk.Window):
    def __init__(self, kde, dodge, on_bell=None, on_controls=None):
        super().__init__(title="OpenNotch Status")
        self.set_name("opennotch-status")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_type_hint(Gdk.WindowTypeHint.DOCK)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_above(True)
        self.set_accept_focus(False)
        self.set_focus_on_map(False)
        self.stick()
        self.dodge = dodge
        # sits inside the right end of Plank's full-width bar (alignment "fill"), so the two read as one taskbar
        visual = self.get_screen().get_rgba_visual()
        if visual is not None:
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.connect("draw", self._clear)
        icon = Gio.Settings.new_with_path("net.launchpad.plank.dock.settings", "/net/launchpad/plank/docks/dock1/") \
            if Gio.SettingsSchemaSource.get_default().lookup("net.launchpad.plank.dock.settings", True) else None
        size = icon.get_int("icon-size") if icon else 44
        self.icon_size = size
        self.bar_h = size + round(size * 0.4)  # Plank theme: TopPadding 3 + BottomPadding 1, in tenths of the icon size
        # NotchPixel: the clock section is one shape with the dock, a step taller, joined by an S-curve
        self.step, self.curve_w, self.overlap, self.corner = 10, 30, 22, 18
        self.set_size_request(-1, self.bar_h + self.step)
        self.dock_shifted = False
        style = Gtk.CssProvider()
        style.load_from_data(b"""
            #opennotch-status { background: transparent; color: #fff; }
            #opennotch-status * { font-family: "SF Pro Text", "SF Pro Display", sans-serif; }
            #opennotch-status .clock { font-family: "SF Pro Display"; font-weight: 700; font-size: 14px; color: #ffffff; }
            #opennotch-status .date { color: rgba(255,255,255,0.62); font-size: 11px; }
            #opennotch-status .divider { background: rgba(255,255,255,0.16); min-width: 1px; }
            #opennotch-status button { background: transparent; border: 0; box-shadow: none; padding: 5px; border-radius: 10px; }
            #opennotch-status button:hover { background: rgba(255,255,255,0.10); }
        """)
        Gtk.StyleContext.add_provider_for_screen(self.get_screen(), style, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        row = Gtk.Box(spacing=12, margin_start=self.curve_w + 4, margin_end=14, margin_top=self.step)
        divider = Gtk.Box(valign=Gtk.Align.CENTER)
        divider.get_style_context().add_class("divider")
        divider.set_size_request(1, round(self.bar_h * 0.45))
        row.pack_start(divider, False, False, 0)
        # NotchPixel layout: "<" (the other tray icons, hidden until asked for), network, volume, time/date, bell
        self.icons = Gtk.Box(spacing=4, valign=Gtk.Align.CENTER)
        self.hidden = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_LEFT, transition_duration=220,
                                   reveal_child=False, valign=Gtk.Align.CENTER)
        self.hidden.add(self.icons)
        self.chevron = Gtk.Button.new_from_icon_name("pan-start-symbolic", Gtk.IconSize.BUTTON)
        self.chevron.set_tooltip_text("Show hidden icons")
        self.chevron.set_valign(Gtk.Align.CENTER)
        self.chevron.connect("clicked", lambda *_: self._toggle_hidden())
        row.pack_start(self.chevron, False, False, 0)
        row.pack_start(self.hidden, False, False, 0)
        self.net_icon, self.vol_icon = Gtk.Image(), Gtk.Image()
        for image, tip in ((self.net_icon, "Network"), (self.vol_icon, "Volume")):
            b = Gtk.Button(image=image, valign=Gtk.Align.CENTER)
            b.set_tooltip_text(tip)
            if on_controls is not None:
                b.connect("clicked", lambda *_: on_controls())
            row.pack_start(b, False, False, 0)
        self._status()
        GLib.timeout_add_seconds(2, self._status)
        if on_bell is not None:
            bell = Gtk.Button.new_from_icon_name("preferences-system-notifications-symbolic", Gtk.IconSize.BUTTON)
            bell.set_tooltip_text("Notifications")
            bell.set_valign(Gtk.Align.CENTER)
            bell.connect("clicked", lambda *_: on_bell())
            row.pack_end(bell, False, False, 0)
        calendar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        self.clock = Gtk.Label()
        self.clock.get_style_context().add_class("clock")
        self.date = Gtk.Label(xalign=0.5)
        self.date.get_style_context().add_class("date")
        calendar.pack_start(self.clock, False, False, 0)
        calendar.pack_start(self.date, False, False, 0)
        row.pack_end(calendar, False, False, 0)
        self.add(row)
        row.show_all()
        self.connect("size-allocate", lambda *_: self._place())
        self.get_screen().connect("monitors-changed", lambda *_: self._place())
        self._clock()
        GLib.timeout_add_seconds(1, self._clock)
        self.strip_items = {}
        if kde:
            self.backend = StatusNotifierHost(self)
        else:
            self._watch_xapp()
        self._update_visibility()
        GLib.timeout_add(250, self._update_visibility)

    def _monitor(self):
        display = self.get_display()
        return display.get_primary_monitor() or display.get_monitor(0)

    def _place(self):
        monitor = self._monitor()
        if monitor is None:
            return
        screen = monitor.get_geometry()
        w, h = self.get_size()
        right = self._dock_right(screen)
        if right is None:  # no Plank: sit at the bottom-right as before
            self.move(screen.x + screen.width - w - 18, screen.y + screen.height - h)
            return
        if not self.dock_shifted:  # move the dock left by half our width so dock + clock are centred as one bar
            self.dock_shifted = True
            shift = (w - self.overlap) / 2
            dock = Gio.Settings.new_with_path("net.launchpad.plank.dock.settings", "/net/launchpad/plank/docks/dock1/")
            dock.set_int("offset", -round(145 * shift / (screen.width / 2)))  # measured: Plank's offset unit is ~0.69 of half the screen
            GLib.timeout_add(600, lambda: (self._place(), False)[1])
            return
        self.move(right - self.overlap, screen.y + screen.height - h)

    def _dock_right(self, screen):
        """Right edge of Plank's centred bar, from its own item positions (GetHoverPosition over D-Bus)."""
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

            def call(method, args=None, reply="(as)"):
                return bus.call_sync("net.launchpad.plank", "/net/launchpad/plank/dock1", "net.launchpad.plank.Items",
                                     method, args, GLib.VariantType(reply), Gio.DBusCallFlags.NONE, 300, None).unpack()
            uris = call("GetPersistentApplications")[0] + call("GetTransientApplications")[0]
            xs = [call("GetHoverPosition", GLib.Variant("(s)", (u,)), "(iiib)")[0] for u in uris]
        except GLib.Error:
            return None
        # measured live with the dock shifted: the bar ends ~1.45 icon widths past the last hover anchor; shortcut: estimate, read the real edge if Plank ever exposes it
        return max(xs) + round(self.icon_size * 1.45) if xs else None

    def _clear(self, _w, cr):
        import cairo

        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        w, h = self.get_allocated_width(), self.get_allocated_height()
        s, c, r = self.step, self.curve_w, self.corner
        cr.move_to(0, h)
        cr.line_to(0, s)                                    # dock height where we meet Plank
        cr.curve_to(c * 0.55, s, c * 0.45, 0, c, 0)         # S-curve up to our taller top
        cr.line_to(w - r, 0)
        cr.arc(w - r, r, r, -1.5708, 0)
        cr.line_to(w, h)
        cr.close_path()
        cr.set_source_rgba(11 / 255, 11 / 255, 12 / 255, 250 / 255)  # same fill as the Plank theme
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, 24 / 255)                       # same rim as the Plank theme
        cr.set_line_width(1)
        cr.stroke()
        return False

    def _toggle_hidden(self):
        show = not self.hidden.get_reveal_child()
        self.hidden.set_reveal_child(show)
        self.chevron.set_image(Gtk.Image.new_from_icon_name("pan-end-symbolic" if show else "pan-start-symbolic",
                                                            Gtk.IconSize.BUTTON))

    def _status(self):
        wifi = wired = False
        for path in glob.glob("/sys/class/net/*"):
            try:
                with open(os.path.join(path, "operstate")) as f:
                    up = f.read().strip() == "up"
            except OSError:
                continue
            if up and os.path.isdir(os.path.join(path, "wireless")):
                wifi = True
            elif up and not os.path.basename(path).startswith(("lo", "docker", "veth", "virbr", "br-")):
                wired = True
        self.net_icon.set_from_icon_name("network-wireless-signal-excellent-symbolic" if wifi else
                                         "network-wired-symbolic" if wired else "network-offline-symbolic",
                                         Gtk.IconSize.BUTTON)
        from .system import sink_muted, sink_volume

        vol = sink_volume()
        muted = sink_muted() if vol is not None else False
        name = ("audio-volume-muted-symbolic" if muted or not vol else "audio-volume-low-symbolic" if vol < 34 else
                "audio-volume-medium-symbolic" if vol < 67 else "audio-volume-high-symbolic")
        self.vol_icon.set_from_icon_name(name, Gtk.IconSize.BUTTON)
        return True

    def _clock(self):
        timestamp = time.localtime()
        self.clock.set_text(time.strftime("%H:%M", timestamp))
        self.date.set_text(time.strftime("%x", timestamp))
        return True

    def _update_visibility(self):
        monitor = self._monitor()
        covered = self.dodge and any(coverage(monitor))
        visible = True
        if covered:
            bounds = monitor.get_geometry()
            pointer = self.get_display().get_default_seat().get_pointer()
            _, x, y = pointer.get_position()
            w, h = self.get_size() if self.get_visible() else (
                self.get_preferred_size()[1].width, 0)
            right, bottom = bounds.x + bounds.width, bounds.y + bounds.height
            # Plank (dodge) comes back when the pointer reaches the bottom edge anywhere; follow it, not just the corner
            visible = bounds.x <= x < right and bottom - (self.bar_h if self.get_visible() else 2) <= y < bottom
            visible = visible or self.grabbed_menu()
        if visible != self.get_visible():
            self.set_visible(visible)
            if visible:
                self._place()
        return True

    def grabbed_menu(self):
        current = Gtk.grab_get_current()
        return bool(current and isinstance(current, Gtk.Menu))

    def add_icon(self, key):
        button = Gtk.Button()
        image = Gtk.Image()
        button.set_image(image)
        self.icons.pack_start(button, False, False, 0)
        self.strip_items[key] = button
        return button, image

    def remove_icon(self, key):
        button = self.strip_items.pop(key, None)
        if button:
            button.destroy()

    def _watch_xapp(self):
        try:
            gi.require_version("XApp", "1.0")
            from gi.repository import XApp
        except (ImportError, ValueError):
            return
        self.backend = XApp.StatusIconMonitor.new()
        self.backend.connect("icon-added", lambda _, proxy: self._add_xapp(proxy))
        self.backend.connect("icon-removed", lambda _, proxy: self.remove_icon(self._xapp_key(proxy)))
        for proxy in self.backend.list_icons():
            self._add_xapp(proxy)

    @staticmethod
    def _xapp_key(proxy):
        return proxy.get_name(), proxy.get_object_path()

    def _add_xapp(self, proxy):
        key = self._xapp_key(proxy)
        if key in self.strip_items:
            return
        button, image = self.add_icon(key)

        def refresh(*_):
            set_icon(image, cached(proxy, "IconName"))
            button.set_tooltip_text(cached(proxy, "TooltipText"))
            if cached(proxy, "Visible", True):
                button.show_all()
            else:
                button.hide()

        def mouse(_button, event, press):
            call = proxy.call_button_press if press else proxy.call_button_release
            _, x, y = button.get_window().get_origin()
            offset = button.translate_coordinates(self, 0, 0)
            if offset:
                px, py = offset[-2:]
                _, wx, wy = self.get_window().get_origin()
                x, y = wx + px, wy + py
            call(x, y, event.button, event.time, int(Gtk.PositionType.BOTTOM), None, None, None)
            return True

        signal = proxy.connect("g-properties-changed", refresh)
        button.connect("destroy", lambda *_: proxy.disconnect(signal))
        button.connect("button-press-event", mouse, True)
        button.connect("button-release-event", mouse, False)
        refresh()


class StatusNotifierHost:
    def __init__(self, strip):
        self.strip = strip
        self.pending = {}
        self.host_name = f"org.kde.StatusNotifierHost-{os.getpid()}"
        self.host_id = Gio.bus_own_name(Gio.BusType.SESSION, self.host_name, Gio.BusNameOwnerFlags.NONE,
                                        None, self._host_ready, None)

    def _host_ready(self, connection, _name):
        self.bus = connection
        self.watch_id = Gio.bus_watch_name_on_connection(connection, WATCHER, Gio.BusNameWatcherFlags.NONE,
                                                        self._watcher_appeared, self._watcher_lost)

    def _watcher_appeared(self, _bus, _name, owner):
        self.owner = owner
        Gio.DBusProxy.new(self.bus, FLAGS, None, owner, "/StatusNotifierWatcher", WATCHER,
                          None, self._watcher_ready, owner)

    def _watcher_ready(self, _bus, result, owner):
        try:
            watcher = Gio.DBusProxy.new_finish(result)
        except GLib.Error:
            return
        if owner != self.owner:
            return
        watcher.connect("g-signal", self._watcher_signal)
        watcher.call("RegisterStatusNotifierHost", GLib.Variant("(s)", (self.host_name,)),
                     Gio.DBusCallFlags.NONE, 1500, None, None, None)
        self.watcher = watcher
        for key in cached(watcher, "RegisteredStatusNotifierItems", []):
            self._add_item(key)

    def _watcher_lost(self, *_):
        self.owner = None
        if getattr(self, "watcher", None):
            self.watcher.disconnect_by_func(self._watcher_signal)
            self.watcher = None
        self.pending.clear()
        for key in tuple(self.strip.strip_items):
            self.strip.remove_icon(key)

    def _watcher_signal(self, _proxy, _sender, signal, args):
        if signal == "StatusNotifierItemRegistered":
            self._add_item(args[0])
        elif signal == "StatusNotifierItemUnregistered":
            self.pending.pop(args[0], None)
            self.strip.remove_icon(args[0])

    def _add_item(self, key):
        if key in self.pending or key in self.strip.strip_items:
            return
        name, _, path = key.partition("/")
        if not Gio.dbus_is_name(name):
            return
        path = "/" + path if path else "/StatusNotifierItem"
        if not GLib.Variant.is_object_path(path):
            return
        token = self.pending[key] = object()
        Gio.DBusProxy.new(self.bus, FLAGS, None, name, path, ITEM, None, self._item_ready, (key, token))

    def _item_ready(self, _bus, result, request):
        key, token = request
        try:
            proxy = Gio.DBusProxy.new_finish(result)
        except GLib.Error:
            if self.pending.get(key) is token:
                del self.pending[key]
            return
        if self.pending.get(key) is not token:
            return
        del self.pending[key]
        button, image = self.strip.add_icon(key)

        def refresh(*_):
            if self.strip.strip_items.get(key) is not button:
                return
            attention = cached(proxy, "Status") == "NeedsAttention"
            name = cached(proxy, "AttentionIconName" if attention else "IconName")
            pixmaps = cached(proxy, "AttentionIconPixmap" if attention else "IconPixmap", [])
            if name:
                set_icon(image, name)
            elif pixmaps:
                self._set_pixmap(image, pixmaps)
            else:
                set_icon(image, None)
            button.set_tooltip_text(cached(proxy, "Title") or cached(proxy, "Id"))
            if cached(proxy, "Status") != "Passive":
                button.show_all()
            else:
                button.hide()

        def activate(_button, event):
            method = {1: "Activate", 2: "SecondaryActivate", 3: "ContextMenu"}.get(event.button)
            if not method:
                return False
            menu = cached(proxy, "Menu")
            if menu and menu != "/" and (event.button == 3 or cached(proxy, "ItemIsMenu")):
                self._menu(proxy, menu, button)
            else:
                proxy.call(method, GLib.Variant("(ii)", (int(event.x_root), int(event.y_root))),
                           Gio.DBusCallFlags.NONE, 1500, None, None, None)
            return True

        def new_icon(_proxy, _sender, name, _args):
            suffix = {"NewIcon": "Icon", "NewAttentionIcon": "AttentionIcon", "NewStatus": "Status",
                      "NewTitle": "Title"}.get(name)
            if suffix:
                self._refresh_sni(proxy, refresh)

        handlers = [proxy.connect("g-properties-changed", refresh), proxy.connect("g-signal", new_icon)]
        button.connect("destroy", lambda *_: [proxy.disconnect(handler) for handler in handlers])
        button.connect("button-release-event", activate)
        refresh()

    def _refresh_sni(self, proxy, refresh):
        def done(bus, result, _data):
            try:
                values = bus.call_finish(result).get_child_value(0)
            except GLib.Error:
                return
            for index in range(values.n_children()):
                entry = values.get_child_value(index)
                key, value = entry.get_child_value(0).unpack(), entry.get_child_value(1).get_variant()
                proxy.set_cached_property(key, value)
            refresh()

        self.bus.call(proxy.get_name(), proxy.get_object_path(), "org.freedesktop.DBus.Properties", "GetAll",
                      GLib.Variant("(s)", (ITEM,)), None, Gio.DBusCallFlags.NONE, 1500, None, done, None)

    @staticmethod
    def _set_pixmap(image, pixmaps):
        valid = [p for p in pixmaps if 0 < p[0] <= 256 and 0 < p[1] <= 256 and len(p[2]) == p[0] * p[1] * 4]
        if not valid:
            set_icon(image, None)
            return
        w, h, raw = min(valid, key=lambda p: abs(p[0] - 16))
        argb = bytes(raw)
        rgba = bytearray(len(argb))
        rgba[0::4], rgba[1::4], rgba[2::4], rgba[3::4] = argb[1::4], argb[2::4], argb[3::4], argb[0::4]
        pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(bytes(rgba)), GdkPixbuf.Colorspace.RGB,
                                                True, 8, w, h, 4 * w)
        image.set_from_pixbuf(pixbuf.scale_simple(16, 16, GdkPixbuf.InterpType.BILINEAR))

    def _menu(self, proxy, path, button):
        name = proxy.get_name()

        def send(item_id):
            self.bus.call(name, path, MENU, "Event",
                          GLib.Variant("(isvu)", (item_id, "clicked", GLib.Variant("i", 0), Gtk.get_current_event_time())),
                          None, Gio.DBusCallFlags.NONE, 1500, None, None, None)

        def build(layout):
            menu = Gtk.Menu()
            for item_id, properties, children in layout:
                if not properties.get("visible", True):
                    continue
                if properties.get("type") == "separator":
                    item = Gtk.SeparatorMenuItem()
                else:
                    item = Gtk.MenuItem.new_with_mnemonic(properties.get("label", ""))
                    item.set_sensitive(properties.get("enabled", True))
                    if children:
                        item.set_submenu(build(children))
                    else:
                        item.connect("activate", lambda _, value=item_id: send(value))
                menu.append(item)
            return menu

        def loaded(bus, result, _data):
            try:
                _, (_, _, children) = bus.call_finish(result).unpack()
            except GLib.Error:
                return
            if not button.get_mapped():
                return
            menu = build(children)
            menu.attach_to_widget(button, None)
            menu.show_all()
            menu.popup_at_widget(button, Gdk.Gravity.NORTH, Gdk.Gravity.SOUTH, None)

        self.bus.call(name, path, MENU, "GetLayout", GLib.Variant("(iias)", (0, -1, [])), None,
                      Gio.DBusCallFlags.NONE, 1500, None, loaded, None)
