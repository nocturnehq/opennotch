"""Session-bus watchers: MPRIS2 media players and a read-only mirror of desktop notifications."""
import html
import re
import time

from gi.repository import Gio, GLib

MPRIS_PREFIX = "org.mpris.MediaPlayer2."
MPRIS_PATH = "/org/mpris/MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"


def media_allowed(bus_name, mode="all", apps=""):
    """Filter MPRIS bus names by allow/ignore list (comma-separated, case-insensitive)."""
    if mode not in ("allow", "ignore"):
        return True
    tokens = [t.strip().lower() for t in (apps or "").split(",") if t.strip()]
    if not tokens:
        return True
    short = bus_name[len(MPRIS_PREFIX):].lower() if bus_name.startswith(MPRIS_PREFIX) else bus_name.lower()
    matched = any(t in short for t in tokens)
    return matched if mode == "allow" else not matched


class Mpris:
    """Tracks every MPRIS2 player; `on_change()` is called whenever the active one changes state."""

    def __init__(self, on_change, mode="all", apps=""):
        self.on_change = on_change
        self.mode = mode
        self.apps = apps
        self.players = {}  # bus name -> Gio.DBusProxy
        self.active = None
        self.dbus = Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SESSION, Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES, None,
            "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", None)
        self.dbus.connect("g-signal", self._on_dbus_signal)
        names = self.dbus.call_sync("ListNames", None, Gio.DBusCallFlags.NONE, -1, None).unpack()[0]
        for name in names:
            if name.startswith(MPRIS_PREFIX) and media_allowed(name, self.mode, self.apps):
                self._add(name)
        self._pick()

    def _on_dbus_signal(self, _proxy, _sender, signal, params):
        if signal != "NameOwnerChanged":
            return
        name, _old, new = params.unpack()
        if not name.startswith(MPRIS_PREFIX):
            return
        self.players.pop(name, None)
        if new and media_allowed(name, self.mode, self.apps):
            self._add(name)
        self._pick()
        self.on_change()

    def _add(self, name):
        try:
            proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION, Gio.DBusProxyFlags.GET_INVALIDATED_PROPERTIES, None,
                name, MPRIS_PATH, PLAYER_IFACE, None)
        except GLib.Error:
            return
        proxy.connect("g-properties-changed", self._on_props, name)
        self.players[name] = proxy

    def _on_props(self, _proxy, _changed, _invalidated, name):
        if self._status(name) == "Playing":
            self.active = name  # the player that just started playing wins
        self._pick()
        self.on_change()

    def _status(self, name):
        v = self.players[name].get_cached_property("PlaybackStatus") if name in self.players else None
        return v.unpack() if v else "Stopped"

    def _pick(self):
        if self.active in self.players and self._status(self.active) == "Playing":
            return
        playing = [n for n in self.players if self._status(n) == "Playing"]
        if playing:
            self.active = playing[0]
        elif self.active not in self.players:
            self.active = next(iter(self.players), None)

    # ---- state of the active player ----
    def info(self):
        p = self.players.get(self.active)
        if not p:
            return None
        md = p.get_cached_property("Metadata")
        md = md.unpack() if md else {}
        artist = md.get("xesam:artist") or []
        return {
            "title": md.get("xesam:title") or self.active[len(MPRIS_PREFIX):].split(".")[0].capitalize(),
            "artist": ", ".join(artist) if isinstance(artist, list) else str(artist),
            "album": md.get("xesam:album") or "",
            "art": md.get("mpris:artUrl") or "",
            "length": int(md.get("mpris:length") or 0),  # microseconds
            "trackid": md.get("mpris:trackid") or "",
            "status": self._status(self.active),
        }

    def call(self, method, params=None):
        p = self.players.get(self.active)
        if p:
            p.call(method, params, Gio.DBusCallFlags.NONE, -1, None, None)

    def position(self, callback):
        """Position is not signalled by players, so it is read on demand (only while the card is open)."""
        p = self.players.get(self.active)
        if not p:
            return

        def done(proxy, res):
            try:
                value = proxy.call_finish(res).unpack()[0]
            except GLib.Error:
                value = None  # some players don't expose Position: the caller estimates it
            callback(value)
        p.call("org.freedesktop.DBus.Properties.Get", GLib.Variant("(ss)", (PLAYER_IFACE, "Position")),
               Gio.DBusCallFlags.NONE, 1000, None, done)

    def seek_to(self, seconds, current_us):
        info = self.info()
        if not info:
            return
        target = int(seconds * 1_000_000)
        if info["trackid"]:
            self.call("SetPosition", GLib.Variant("(ox)", (info["trackid"], target)))
        else:
            self.call("Seek", GLib.Variant("(x)", (target - current_us,)))


class NotificationMirror:
    """Becomes a D-Bus monitor for Notify calls. Read-only: it never replies, forwards or stores anything on disk."""

    RULE = "type='method_call',interface='org.freedesktop.Notifications',member='Notify'"

    def __init__(self, on_notify):
        self.on_notify = on_notify
        addr = Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION, None)
        self.conn = Gio.DBusConnection.new_for_address_sync(
            addr, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None, None)
        self.conn.add_filter(self._filter)
        self.conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus.Monitoring",
                            "BecomeMonitor", GLib.Variant("(asu)", ([self.RULE], 0)), None,
                            Gio.DBusCallFlags.NONE, 3000, None)

    def _filter(self, _conn, msg, incoming):
        # runs in the GDBus worker thread
        mtype = msg.get_message_type()
        if not incoming or mtype in (Gio.DBusMessageType.METHOD_RETURN, Gio.DBusMessageType.ERROR):
            return msg  # our own BecomeMonitor call and its reply
        if incoming and mtype == Gio.DBusMessageType.METHOD_CALL and msg.get_member() == "Notify":
            body = msg.get_body()
            if body is not None and body.get_type_string().startswith("(susss"):
                app, _rid, icon, summary, text = body.unpack()[:5]
                GLib.idle_add(self.on_notify, {
                    "app": app or "Notification", "icon": icon, "summary": strip_markup(summary),
                    "body": strip_markup(text), "time": time.time()})
        return None  # monitors must never answer: drop everything else


def strip_markup(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()
