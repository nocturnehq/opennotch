"""Read-only Twitch chat for OpenNotch: anonymous IRC over TLS, no account or token needed."""
import random
import re
import socket
import ssl
import threading
import time

HOST, PORT = "irc.chat.twitch.tv", 6697
CHANNEL_RE = re.compile(r"[a-z0-9_]{3,25}")
# @tags :nick!nick@nick.tmi.twitch.tv PRIVMSG #channel :text
PRIVMSG_RE = re.compile(r"^(?:@(?P<tags>\S+) )?:(?P<nick>[^!\s]+)!\S+ PRIVMSG #\S+ :(?P<text>.*)$")


def channel_name(value):
    """'twitch.tv/Foo', '#foo' or 'foo' → 'foo'; None when it can't be a Twitch login."""
    if not isinstance(value, str):
        return None
    name = value.strip().rstrip("/").rsplit("/", 1)[-1].lstrip("#").lower()
    return name if CHANNEL_RE.fullmatch(name) else None


def parse_line(line):
    """One IRC line → ('ping', payload) | ('msg', (author, text)) | None."""
    if line.startswith("PING"):
        return "ping", line[5:]
    m = PRIVMSG_RE.match(line)
    if not m:
        return None
    author = m["nick"]
    for tag in (m["tags"] or "").split(";"):
        key, _, value = tag.partition("=")
        if key == "display-name" and value:
            author = value.replace("\\s", " ")
    text = m["text"]
    if text.startswith("\x01ACTION ") and text.endswith("\x01"):  # /me
        text = text[8:-1]
    return "msg", (author, text.strip())


class TwitchChat:
    """Calls on_message(author, text) on the GTK main loop for each chat line. Reconnects with backoff."""

    def __init__(self, channel, on_message, on_error=None):
        self.channel = channel
        self.on_message = on_message
        self.on_error = on_error
        self._stop = threading.Event()
        self._sock = None

    def start(self):
        threading.Thread(target=self._run, name="twitch-chat", daemon=True).start()

    def close(self):
        self._stop.set()
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    def _dispatch(self, fn, *args):
        from gi.repository import GLib

        GLib.idle_add(lambda: (fn(*args), False)[1])

    def _run(self):
        delay = 2
        while not self._stop.is_set():
            try:
                self._session()
                delay = 2
            except (OSError, ssl.SSLError) as exc:
                if self._stop.is_set():
                    return
                if self.on_error is not None:
                    self._dispatch(self.on_error, str(exc))
            self._stop.wait(delay)
            delay = min(delay * 2, 120)

    def _session(self):
        raw = socket.create_connection((HOST, PORT), timeout=15)
        sock = ssl.create_default_context().wrap_socket(raw, server_hostname=HOST)
        self._sock = sock
        nick = "justinfan%d" % random.randint(10000, 99999)  # Twitch's anonymous read-only login
        sock.sendall(("CAP REQ :twitch.tv/tags\r\nNICK %s\r\nJOIN #%s\r\n" % (nick, self.channel)).encode())
        sock.settimeout(360)  # Twitch pings every ~5 minutes
        buf = b""
        last_shown = 0.0
        while not self._stop.is_set():
            data = sock.recv(4096)
            if not data:
                raise OSError("Twitch closed the connection")
            buf += data
            *lines, buf = buf.split(b"\r\n")
            for raw_line in lines:
                parsed = parse_line(raw_line.decode("utf-8", "replace"))
                if parsed is None:
                    continue
                kind, value = parsed
                if kind == "ping":
                    sock.sendall(("PONG %s\r\n" % value).encode())
                elif value[1] and time.monotonic() - last_shown >= 2:
                    # shortcut: busy chats show at most one line per 2 s; a scrolling chat view would show all
                    last_shown = time.monotonic()
                    self._dispatch(self.on_message, *value)
