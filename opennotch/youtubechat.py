"""Read-only YouTube live chat for OpenNotch, read the way YouTube's own popout chat page reads it (no API key).

shortcut: YouTube's internal web chat endpoint, which YouTube can change without notice (the user chose this
over an API key); if it breaks, switch to the Data API's liveChatMessages.list with a user-made key.
"""
import json
import re
import threading
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept-Language": "en", "Cookie": "SOCS=CAI"}  # SOCS=CAI: consent page answered "reject all"
VIDEO_RE = re.compile(r"[A-Za-z0-9_-]{11}")
HANDLE_RE = re.compile(r"@[A-Za-z0-9._-]{3,30}")


class NotLive(Exception):
    pass


def target(value):
    """What the setting names: ('video', id), ('handle', '@name'), ('channel', 'UC…') or None."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if VIDEO_RE.fullmatch(value):
        return "video", value
    if HANDLE_RE.fullmatch(value):
        return "handle", value
    url = urllib.parse.urlparse(value if "//" in value else "https://" + value)
    host = url.hostname or ""
    if not (host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")):
        return None
    parts = [p for p in url.path.split("/") if p]
    vid = urllib.parse.parse_qs(url.query).get("v", [None])[0]
    if host == "youtu.be" and parts:
        vid = parts[0]
    elif len(parts) >= 2 and parts[0] in ("live", "shorts", "embed"):
        vid = parts[1]
    if vid and VIDEO_RE.fullmatch(vid):
        return "video", vid
    if parts and HANDLE_RE.fullmatch(parts[0]):
        return "handle", parts[0]
    if len(parts) >= 2 and parts[0] == "channel" and re.fullmatch(r"UC[A-Za-z0-9_-]{22}", parts[1]):
        return "channel", parts[1]
    return None


def _get(url, data=None, timeout=15):
    headers = dict(HEADERS)
    if data is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(data).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data, headers), timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def live_video_id(kind, value):
    if kind == "video":
        return value
    page = _get(f"https://www.youtube.com/{value}/live" if kind == "handle"
                else f"https://www.youtube.com/channel/{value}/live")
    m = re.search(r'<link rel="canonical" href="https://www\.youtube\.com/watch\?v=([A-Za-z0-9_-]{11})"', page)
    if not m:
        raise NotLive("This channel is not live.")
    return m.group(1)


def messages(actions):
    """liveChatContinuation actions → [(author, text)] for plain chat messages."""
    out = []
    for action in actions or ():
        item = action.get("addChatItemAction", {}).get("item", {}).get("liveChatTextMessageRenderer")
        if not item:
            continue
        author = item.get("authorName", {}).get("simpleText", "")
        text = "".join(run.get("text") or (run.get("emoji", {}).get("shortcuts") or [""])[0]
                       for run in item.get("message", {}).get("runs", []))
        if author and text.strip():
            out.append((author, text.strip()))
    return out


def next_continuation(chat):
    for c in chat.get("continuations", []):
        for kind in ("invalidationContinuationData", "timedContinuationData", "reloadContinuationData"):
            if kind in c:
                return c[kind]["continuation"], max(1000, min(int(c[kind].get("timeoutMs", 5000)), 20000))
    return None, 0


class YouTubeChat:
    """Calls on_message(author, text) on the GTK main loop. Waits and retries while the stream is off."""

    def __init__(self, setting, on_message, on_error=None):
        self.target = target(setting)
        self.on_message = on_message
        self.on_error = on_error
        self._stop = threading.Event()

    def start(self):
        if self.target is not None:
            threading.Thread(target=self._run, name="youtube-chat", daemon=True).start()

    def close(self):
        self._stop.set()

    def _dispatch(self, fn, *args):
        from gi.repository import GLib

        GLib.idle_add(lambda: (fn(*args), False)[1])

    def _run(self):
        while not self._stop.is_set():
            try:
                self._session()
            except (NotLive, OSError, ValueError, KeyError) as exc:  # URLError is an OSError
                if self.on_error is not None:
                    self._dispatch(self.on_error, str(exc))
            self._stop.wait(60)

    def _session(self):
        vid = live_video_id(*self.target)
        page = _get(f"https://www.youtube.com/live_chat?is_popout=1&v={vid}")
        key = re.search(r'"INNERTUBE_API_KEY":"([^"]+)"', page)
        version = re.search(r'"INNERTUBE_CLIENT_VERSION":"([^"]+)"', page)
        cont = re.search(r'"continuation":"([^"]+)"', page)
        if not (key and version and cont):
            raise NotLive("This stream has no live chat now.")
        url = f"https://www.youtube.com/youtubei/v1/live_chat/get_live_chat?key={key.group(1)}&prettyPrint=false"
        body = {"context": {"client": {"clientName": "WEB", "clientVersion": version.group(1)}}}
        continuation, first = cont.group(1), True
        while continuation and not self._stop.is_set():
            reply = json.loads(_get(url, dict(body, continuation=continuation)))
            chat = reply.get("continuationContents", {}).get("liveChatContinuation")
            if chat is None:
                raise NotLive("The live chat ended.")
            found = messages(chat.get("actions"))
            if found and not first:  # the first batch is backlog
                self._dispatch(self.on_message, *found[-1])  # newest line only: a busy chat can't flood the notch
            first = False
            continuation, timeout = next_continuation(chat)
            self._stop.wait(timeout / 1000)
