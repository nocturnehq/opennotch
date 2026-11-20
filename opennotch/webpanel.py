"""A sleek, lazily created mini-browser inside the island with persistent logins, pins, and search."""
import json
import os
import tempfile
from urllib.parse import quote_plus, urlsplit

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

SITES = (
    ("YouTube Music", "https://music.youtube.com/", "multimedia-player-symbolic"),
    ("Spotify", "https://open.spotify.com/", "audio-x-generic-symbolic"),
    ("SoundCloud", "https://soundcloud.com/", "audio-speakers-symbolic"),
    ("YouTube", "https://www.youtube.com/", "video-display-symbolic"),
    ("ChatGPT", "https://chatgpt.com/", "user-available-symbolic"),
    ("Claude", "https://claude.ai/", "dialog-question-symbolic"),
)

DEFAULT_ZOOM = 0.85


def _data_dir():
    base = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    return os.path.join(base, "opennotch")


def web_address(value, assume_https=False):
    value = (value or "").strip()
    if assume_https and "://" not in value and value:
        value = "https://" + value
    try:
        url = urlsplit(value)
        if url.scheme in ("http", "https") and url.hostname and not url.username and not url.password:
            return value
    except ValueError:
        pass
    return None


def resolve_input(value):
    """Turn a URL/domain into an https URL, or a plain search phrase into a DuckDuckGo search URL."""
    text = (value or "").strip()
    if not text:
        return None
    if "://" in text:
        return web_address(text)
    if " " not in text and ("." in text or text.startswith("localhost")):
        return web_address(text, assume_https=True)
    return f"https://duckduckgo.com/?q={quote_plus(text)}"


def site_label(uri):
    try:
        host = (urlsplit(uri).hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return host.split(".")[0].capitalize() if host else "Site"
    except ValueError:
        return "Site"


class WebPinStore:
    """Atomic JSON store for user-pinned websites in the Web tab."""

    def __init__(self, path=None):
        self.path = path or os.path.join(_data_dir(), "webpins.json")
        self.pins = []
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, list):
                self.pins = [
                    {"title": str(p.get("title") or site_label(p["url"]))[:28], "url": str(p["url"])}
                    for p in raw if isinstance(p, dict) and web_address(str(p.get("url", "")))
                ][:12]
        except (OSError, ValueError):
            pass

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".pins-", dir=os.path.dirname(self.path))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self.pins, f, indent=2)
                os.replace(tmp, self.path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        except OSError:
            pass

    def has(self, url):
        return any(p["url"] == url for p in self.pins)

    def toggle(self, url, title=""):
        url = web_address(url)
        if not url:
            return False
        if self.has(url):
            self.pins = [p for p in self.pins if p["url"] != url]
            self.save()
            return False
        self.pins.insert(0, {"title": (title.strip() or site_label(url))[:28], "url": url})
        del self.pins[12:]
        self.save()
        return True

    def remove(self, url):
        before = len(self.pins)
        self.pins = [p for p in self.pins if p["url"] != url]
        if len(self.pins) != before:
            self.save()


class _LoadBar(Gtk.DrawingArea):
    """2 px crisp white loading bar under the Web tab toolbar."""

    def __init__(self):
        super().__init__()
        self.progress = 0.0
        self.set_size_request(-1, 2)
        self.set_no_show_all(True)
        self.connect("draw", self._draw)

    def set_progress(self, value):
        self.progress = max(0.0, min(1.0, float(value)))
        self.set_visible(0.0 < self.progress < 1.0)
        self.queue_draw()

    def _draw(self, _w, cr):
        w, h = self.get_allocated_width(), self.get_allocated_height()
        cr.set_source_rgba(1, 1, 1, 0.10)
        cr.rectangle(0, 0, w, h)
        cr.fill()
        cr.set_source_rgba(1, 1, 1, 0.90)
        cr.rectangle(0, 0, w * self.progress, h)
        cr.fill()
        return False


class WebPanel(Gtk.Box):
    def __init__(self, keyboard):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.keyboard = keyboard
        self.view = None
        self.webkit = None
        self.loading = False
        self.pins = WebPinStore()

        # Compact single-row pill toolbar
        toolbar = Gtk.Box(spacing=3)
        self.back = self._button("go-previous-symbolic", "Back", self._go_back)
        self.forward = self._button("go-next-symbolic", "Forward", self._go_forward)
        self.reload = self._button("view-refresh-symbolic", "Reload", self._reload_or_stop)
        self.home = self._button("go-home-symbolic", "Start page", self._go_home)
        for button in (self.back, self.forward, self.reload):
            button.set_sensitive(False)
        for button in (self.back, self.forward, self.reload, self.home):
            toolbar.pack_start(button, False, False, 0)

        self.address = Gtk.Entry(placeholder_text="Search or enter website", width_chars=18)
        self.address.get_style_context().add_class("ask")
        self.address.connect("activate", lambda entry: self.open(entry.get_text()))
        self.address.connect("button-press-event", keyboard)
        toolbar.pack_start(self.address, True, True, 2)

        self.pin_btn = self._button("view-pin-symbolic", "Pin to start page", self._toggle_pin)
        self.pin_btn.set_sensitive(False)
        self.ext_btn = self._button("window-new-symbolic", "Open in default browser", self._open_external)
        self.ext_btn.set_sensitive(False)
        toolbar.pack_end(self.ext_btn, False, False, 0)
        toolbar.pack_end(self.pin_btn, False, False, 0)
        self.pack_start(toolbar, False, False, 0)

        self.load_bar = _LoadBar()
        self.pack_start(self.load_bar, False, False, 0)

        self.message = Gtk.Label(no_show_all=True, xalign=0, wrap=True)
        self.message.get_style_context().add_class("dim")
        self.pack_start(self.message, False, False, 0)

        self.content = Gtk.Stack(
            transition_type=Gtk.StackTransitionType.CROSSFADE,
            transition_duration=160,
            vhomogeneous=False,
            hhomogeneous=False,
        )
        self.pack_start(self.content, True, True, 0)

        # Start page: clean 3x2 frosted glass tiles + user pins row
        home_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                           halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        grid = Gtk.Grid(column_spacing=8, row_spacing=8, column_homogeneous=True)
        for idx, (title, url, icon) in enumerate(SITES):
            b = Gtk.Button()
            b.set_can_focus(False)
            b.get_style_context().add_class("tile")
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5, margin=10)
            inner.set_size_request(116, 52)
            inner.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR), False, False, 0)
            lbl = Gtk.Label(label=title, xalign=0.5)
            lbl.set_ellipsize(3)
            inner.pack_start(lbl, False, False, 0)
            b.add(inner)
            b.connect("clicked", lambda _b, u=url: self.open(u))
            grid.attach(b, idx % 3, idx // 3, 1, 1)
        home_box.pack_start(grid, False, False, 0)

        self.pins_box = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            column_spacing=6,
            row_spacing=6,
            halign=Gtk.Align.CENTER,
            max_children_per_line=4,
        )
        home_box.pack_start(self.pins_box, False, False, 0)
        self._refresh_pins()
        self.content.add_named(home_box, "home")

    def _button(self, icon, tooltip, callback):
        button = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.set_can_focus(False)
        button.set_tooltip_text(tooltip)
        button.connect("clicked", lambda *_: callback())
        return button

    def _refresh_pins(self):
        for ch in self.pins_box.get_children():
            ch.destroy()
        for pin in self.pins.pins:
            pill = Gtk.Box(spacing=4)
            go = Gtk.Button(label=pin["title"])
            go.set_can_focus(False)
            go.get_style_context().add_class("chip")
            go.set_tooltip_text(pin["url"])
            go.connect("clicked", lambda _b, u=pin["url"]: self.open(u))
            rm = Gtk.Button(label="×")
            rm.set_relief(Gtk.ReliefStyle.NONE)
            rm.set_can_focus(False)
            rm.set_tooltip_text("Unpin")
            rm.connect("clicked", lambda _b, u=pin["url"]: (self.pins.remove(u), self._refresh_pins(), self._sync_pin_btn()))
            pill.pack_start(go, False, False, 0)
            pill.pack_start(rm, False, False, 0)
            self.pins_box.add(pill)
        self.pins_box.set_visible(bool(self.pins.pins))
        self.pins_box.show_all()

    def _sync_pin_btn(self):
        uri = self.view.get_uri() if self.view else ""
        valid = bool(web_address(uri))
        self.pin_btn.set_sensitive(valid)
        self.ext_btn.set_sensitive(valid)
        ctx = self.pin_btn.get_style_context()
        if valid and self.pins.has(uri):
            ctx.add_class("on")
            self.pin_btn.set_tooltip_text("Pinned — click to unpin")
        else:
            ctx.remove_class("on")
            self.pin_btn.set_tooltip_text("Pin to start page")

    def _go_back(self):
        if self.view and self.view.can_go_back():
            self.view.go_back()

    def _go_forward(self):
        if self.view and self.view.can_go_forward():
            self.view.go_forward()

    def _reload_or_stop(self):
        if not self.view:
            return
        if self.loading:
            self.view.stop_loading()
        else:
            self.view.reload()

    def _go_home(self):
        self._notice()
        self.load_bar.set_progress(0.0)
        self.content.set_visible_child_name("home")
        self.address.set_text("")
        self.pin_btn.set_sensitive(False)
        self.pin_btn.get_style_context().remove_class("on")
        self.ext_btn.set_sensitive(False)

    def _toggle_pin(self):
        if not self.view:
            return
        uri = self.view.get_uri() or ""
        title = self.view.get_title() or ""
        self.pins.toggle(uri, title)
        self._refresh_pins()
        self._sync_pin_btn()

    def _open_external(self):
        uri = (self.view.get_uri() if self.view else "") or self.address.get_text()
        if web_address(uri):
            try:
                Gio.AppInfo.launch_default_for_uri(uri, None)
            except GLib.Error:
                pass

    def _create(self):
        try:
            gi.require_version("WebKit2", "4.1")
            from gi.repository import WebKit2
        except (ImportError, ValueError):
            self._notice("WebKitGTK 4.1 is required for the Web tab.")
            return False
        self.webkit = WebKit2
        data_root = os.path.join(_data_dir(), "webdata")
        cache_root = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "opennotch", "web")
        os.makedirs(data_root, mode=0o700, exist_ok=True)
        os.makedirs(cache_root, mode=0o700, exist_ok=True)
        manager = WebKit2.WebsiteDataManager(base_data_directory=data_root, base_cache_directory=cache_root)
        context = WebKit2.WebContext.new_with_website_data_manager(manager)
        context.connect("download-started", self._cancel_download)
        self.view = WebKit2.WebView.new_with_context(context)
        settings = self.view.get_settings()
        settings.set_javascript_can_access_clipboard(False)
        settings.set_enable_smooth_scrolling(True)
        settings.set_enable_page_cache(True)
        self.view.set_zoom_level(DEFAULT_ZOOM)
        self.view.set_background_color(Gdk.RGBA(0.04, 0.04, 0.05, 1))
        self.view.connect("button-press-event", self.keyboard)
        self.view.connect("key-press-event", self._on_key)
        self.view.connect("permission-request", self._deny_permissions)
        self.view.connect("decide-policy", self._navigation)
        self.view.connect("load-changed", self._load_changed)
        self.view.connect("load-failed", self._load_failed)
        self.view.connect("notify::estimated-load-progress", self._on_progress)
        self.view.connect("web-process-terminated", self._web_process_terminated)
        self.content.add_named(self.view, "view")
        self.view.show()
        self.content.set_visible_child_name("view")
        self.reload.set_sensitive(True)
        return True

    def _on_key(self, _view, ev):
        if not (ev.state & Gdk.ModifierType.CONTROL_MASK) or not self.view:
            return False
        name = Gdk.keyval_name(ev.keyval) or ""
        if name in ("plus", "equal", "KP_Add"):
            self.view.set_zoom_level(min(1.5, self.view.get_zoom_level() + 0.1))
            return True
        if name in ("minus", "KP_Subtract"):
            self.view.set_zoom_level(max(0.5, self.view.get_zoom_level() - 0.1))
            return True
        if name in ("0", "KP_0"):
            self.view.set_zoom_level(DEFAULT_ZOOM)
            return True
        return False

    def _on_progress(self, view, _pspec):
        self.load_bar.set_progress(view.get_estimated_load_progress())

    def _cancel_download(self, _context, download):
        download.cancel()
        self._notice("Downloads are unavailable in the Web tab.")

    def _notice(self, text=""):
        self.message.set_text(text)
        self.message.set_visible(bool(text))

    def open(self, address):
        uri = resolve_input(address)
        if not uri:
            self._notice("Enter a website address or search term.")
            return False
        if self.view is None and not self._create():
            return False
        self.content.set_visible_child_name("view")
        self.address.set_text(uri)
        self.view.load_uri(uri)
        return True

    @staticmethod
    def _deny_permissions(_view, permission):
        permission.deny()
        return True

    def _navigation(self, view, decision, kind):
        policy = self.webkit.PolicyDecisionType
        if kind not in (policy.NAVIGATION_ACTION, policy.NEW_WINDOW_ACTION):
            return False
        uri = decision.get_navigation_action().get_request().get_uri()
        if not web_address(uri):
            decision.ignore()
            return True
        if kind == policy.NEW_WINDOW_ACTION:
            decision.ignore()
            view.load_uri(uri)
            return True
        return False

    def _load_changed(self, view, event):
        if event == self.webkit.LoadEvent.STARTED:
            self._notice()
            self.loading = True
            self.reload.set_image(Gtk.Image.new_from_icon_name("process-stop-symbolic", Gtk.IconSize.BUTTON))
            self.reload.set_tooltip_text("Stop")
        if event in (self.webkit.LoadEvent.COMMITTED, self.webkit.LoadEvent.FINISHED):
            self.address.set_text(view.get_uri() or "")
            self.back.set_sensitive(view.can_go_back())
            self.forward.set_sensitive(view.can_go_forward())
            self._sync_pin_btn()
        if event == self.webkit.LoadEvent.FINISHED:
            self.loading = False
            self.load_bar.set_progress(1.0)
            self.reload.set_image(Gtk.Image.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON))
            self.reload.set_tooltip_text("Reload")

    def _load_failed(self, _view, _event, _uri, error):
        self.loading = False
        self.load_bar.set_progress(1.0)
        if not error.matches(self.webkit.network_error_quark(), self.webkit.NetworkError.CANCELLED):
            self._notice(error.message)
        return True

    def _web_process_terminated(self, _view, _reason):
        self.loading = False
        self.load_bar.set_progress(1.0)
        self._notice("The browser stopped. Reload to reopen the page.")
