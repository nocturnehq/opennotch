"""A lazily created browser for music sites inside the island."""
from urllib.parse import urlsplit

import gi
from gi.repository import Gdk, Gtk

SITES = (
    ("YouTube Music", "https://music.youtube.com/"),
    ("Spotify", "https://open.spotify.com/"),
    ("SoundCloud", "https://soundcloud.com/"),
)


def web_address(value, assume_https=False):
    value = value.strip()
    if assume_https and "://" not in value and value:
        value = "https://" + value
    try:
        url = urlsplit(value)
        if url.scheme in ("http", "https") and url.hostname and not url.username and not url.password:
            return value
    except ValueError:
        pass
    return None


class WebPanel(Gtk.Box):
    def __init__(self, keyboard):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        self.keyboard = keyboard
        self.view = None
        toolbar = Gtk.Box(spacing=4)
        self.back = self._button("go-previous-symbolic", "Back", "go_back")
        self.forward = self._button("go-next-symbolic", "Forward", "go_forward")
        self.reload = self._button("view-refresh-symbolic", "Reload", "reload")
        for button in (self.back, self.forward, self.reload):
            toolbar.pack_start(button, False, False, 0)
            button.set_sensitive(False)
        self.address = Gtk.Entry(placeholder_text="Enter a website", width_chars=17)
        self.address.connect("activate", lambda entry: self.open(entry.get_text()))
        self.address.connect("button-press-event", keyboard)
        toolbar.pack_start(self.address, True, True, 0)
        go = Gtk.Button.new_from_icon_name("go-jump-symbolic", Gtk.IconSize.BUTTON)
        go.set_tooltip_text("Go")
        go.connect("clicked", lambda *_: self.open(self.address.get_text()))
        toolbar.pack_end(go, False, False, 0)
        self.pack_start(toolbar, False, False, 0)

        self.message = Gtk.Label(no_show_all=True, xalign=0, wrap=True)
        self.message.get_style_context().add_class("wingdim")
        self.pack_start(self.message, False, False, 0)

        self.content = Gtk.Stack(vhomogeneous=False, hhomogeneous=False)
        self.pack_start(self.content, True, True, 0)
        links = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        for title, address in SITES:
            button = Gtk.Button(label=title)
            button.connect("clicked", lambda _b, url=address: self.open(url))
            links.pack_start(button, False, False, 0)
        self.content.add_named(links, "home")

    def _button(self, icon, tooltip, action):
        button = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
        button.set_tooltip_text(tooltip)
        button.connect("clicked", lambda *_: getattr(self.view, action)() if self.view else None)
        return button

    def _create(self):
        try:
            gi.require_version("WebKit2", "4.1")
            from gi.repository import WebKit2
        except (ImportError, ValueError):
            self._notice("WebKitGTK 4.1 is required for the Web tab.")
            return False
        self.webkit = WebKit2
        context = WebKit2.WebContext.new_ephemeral()
        context.connect("download-started", self._cancel_download)
        self.view = WebKit2.WebView.new_with_context(context)
        settings = self.view.get_settings()
        settings.set_javascript_can_access_clipboard(False)
        settings.set_enable_page_cache(False)
        self.view.set_background_color(Gdk.RGBA(0.07, 0.07, 0.08, 1))
        self.view.connect("button-press-event", self.keyboard)
        self.view.connect("permission-request", self._deny_permissions)
        self.view.connect("decide-policy", self._navigation)
        self.view.connect("load-changed", self._load_changed)
        self.view.connect("load-failed", self._load_failed)
        self.view.connect("web-process-terminated", self._web_process_terminated)
        self.content.add_named(self.view, "view")
        self.view.show()
        self.content.set_visible_child_name("view")
        self.reload.set_sensitive(True)
        return True

    def _cancel_download(self, _context, download):
        download.cancel()
        self._notice("Downloads are unavailable in the Web tab.")

    def _notice(self, text=""):
        self.message.set_text(text)
        self.message.set_visible(bool(text))

    def open(self, address):
        uri = web_address(address, assume_https=True)
        if not uri:
            self._notice("Enter an HTTP or HTTPS website address.")
            return False
        if self.view is None and not self._create():
            return False
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
        if event in (self.webkit.LoadEvent.COMMITTED, self.webkit.LoadEvent.FINISHED):
            self.address.set_text(view.get_uri() or "")
            self.back.set_sensitive(view.can_go_back())
            self.forward.set_sensitive(view.can_go_forward())

    def _load_failed(self, _view, _event, _uri, error):
        if not error.matches(self.webkit.network_error_quark(), self.webkit.NetworkError.CANCELLED):
            self._notice(error.message)
        return True

    def _web_process_terminated(self, _view, _reason):
        self._notice("The browser stopped. Reload to reopen the page.")
