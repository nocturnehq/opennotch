"""Scripting API: one JSON object per line over a Unix socket, one reply line back.

Request:  {"cmd": "say", "text": "Build finished", "icon": "ok", "seconds": 5}
          {"cmd": "ping"}
Reply:    {"ok": true} or {"ok": false, "error": "..."}
"""
import json
import os
import socket

MAX_LINE = 8192
ICONS = ("ok", "fail", "info")
MAX_TEXT = 300


def encode(obj):
    return (json.dumps(obj) + "\n").encode("utf-8")


def parse_request(line):
    """Validate one request line (bytes). Returns a clean dict or raises ValueError."""
    try:
        req = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ValueError("not valid JSON")
    if not isinstance(req, dict):
        raise ValueError("request must be an object")
    cmd = req.get("cmd")
    if cmd in ("ping", "screenshot", "record"):
        return {"cmd": cmd}
    if cmd in ("say", "done"):
        text = req.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"{cmd} needs non-empty text")
        icon = req.get("icon", "info")
        if icon not in ICONS:
            raise ValueError(f"icon must be one of {', '.join(ICONS)}")
        seconds = req.get("seconds", 5)
        if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or not 1 <= seconds <= 120:
            raise ValueError("seconds must be between 1 and 120")
        text = " ".join(text.split())  # one line in the pill
        if len(text) > MAX_TEXT:
            text = text[: MAX_TEXT - 1] + "…"
        return {"cmd": cmd, "text": text, "icon": icon, "seconds": float(seconds)}
    raise ValueError("unknown cmd")


def _read_line(conn):
    buf = b""
    while b"\n" not in buf and len(buf) <= MAX_LINE:
        chunk = conn.recv(1024)
        if not chunk:
            break
        buf += chunk
    if len(buf) > MAX_LINE:
        raise ValueError("request too long")
    return buf.split(b"\n", 1)[0]


def handle_connection(conn, handler):
    """Read one request from an accepted socket, run handler(req) and reply. Never raises."""
    try:
        conn.settimeout(1.0)
        req = parse_request(_read_line(conn))
        handler(req)
        reply = {"ok": True}
    except ValueError as e:
        reply = {"ok": False, "error": str(e)}
    except OSError:
        conn.close()
        return
    try:
        conn.sendall(encode(reply))
    except OSError:
        pass
    conn.close()


def listen(path):
    """Bind the server socket (owner-only). Raises RuntimeError if another instance is listening."""
    if os.path.exists(path):
        try:
            request(path, {"cmd": "ping"}, timeout=0.5)
            raise RuntimeError("OpenNotch is already running")
        except OSError:
            os.unlink(path)  # stale socket from a crash
    os.makedirs(os.path.dirname(path), exist_ok=True)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old = os.umask(0o177)
    try:
        srv.bind(path)
    finally:
        os.umask(old)
    srv.listen(8)
    return srv


def request(path, obj, timeout=3.0):
    """Client side: send one request and return the decoded reply."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(path)
        s.sendall(encode(obj))
        line = _read_line(s)
    return json.loads(line.decode("utf-8"))
