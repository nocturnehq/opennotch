"""Extra Overview widgets for OpenNotch: To-dos, Calculator, Countdown, Reminders, Ping, Currency, Photos."""
import ast
from datetime import datetime, timedelta
import glob
import json
import math
import operator
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk  # noqa: E402

from . import config  # noqa: E402

DATA_DIR = os.path.join(os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")), "opennotch")

# ---- Pure helpers (unit-tested in selftest.py) ---------------------------------

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}
_FUNCS = {"sqrt": math.sqrt, "abs": abs, "round": round, "sin": math.sin, "cos": math.cos, "tan": math.tan}
_CONSTS = {"pi": math.pi, "e": math.e}


def safe_eval_math(expr):
    """Evaluate a basic arithmetic expression safely via AST; returns formatted string or None."""
    text = (expr or "").strip().replace("×", "*").replace("÷", "/").replace("^", "**")
    if not text or len(text) > 120:
        return None
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        return None

    def _ev(node):
        if isinstance(node, ast.Expression):
            return _ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        if isinstance(node, ast.Name) and node.id.lower() in _CONSTS:
            return _CONSTS[node.id.lower()]
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](_ev(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            left, right = _ev(node.left), _ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 1000:
                raise ValueError("exponent too large")
            return _OPS[type(node.op)](left, right)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id.lower() in _FUNCS:
            args = [_ev(a) for a in node.args]
            return float(_FUNCS[node.func.id.lower()](*args))
        raise ValueError("unsupported")

    try:
        val = _ev(tree)
        if not math.isfinite(val):
            return None
        if abs(val - round(val)) < 1e-9 and abs(val) < 1e12:
            return str(int(round(val)))
        return f"{val:.6g}"
    except (ValueError, ZeroDivisionError, OverflowError, TypeError):
        return None


def countdown_parts(date_str, now=None):
    """Parse 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM' and return (headline, subtitle) relative to now."""
    raw = (date_str or "").strip()
    if not raw:
        return "–", "Set a date in Settings › Widgets"
    now = now or datetime.now()
    target = None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            target = datetime.strptime(raw, fmt)
            break
        except ValueError:
            continue
    if target is None:
        return "–", "Use YYYY-MM-DD"
    delta = target - now
    secs = int(delta.total_seconds())
    if secs <= 0:
        return "Done", target.strftime("%b %d, %Y")
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    if days >= 1:
        return f"{days}d", f"{hours}h left · {target.strftime('%b %d')}"
    if hours >= 1:
        return f"{hours}h {mins}m", target.strftime("Today %H:%M")
    return f"{max(1, mins)}m", target.strftime("Today %H:%M")


def parse_reminder(text, now=None):
    """Parse '15m Stretch' or '14:30 Standup' into (due_timestamp, message) or None."""
    raw = (text or "").strip()
    if not raw:
        return None
    now = now or datetime.now()
    m = re.match(r"^(\d+)\s*([smhd])\s+(.+)$", raw, re.IGNORECASE)
    if m:
        n, unit, msg = int(m.group(1)), m.group(2).lower(), m.group(3).strip()
        mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
        return (now + timedelta(seconds=n * mult)).timestamp(), msg
    m = re.match(r"^(\d{1,2}):(\d{2})\s+(.+)$", raw)
    if m:
        hh, mm, msg = int(m.group(1)), int(m.group(2)), m.group(3).strip()
        if 0 <= hh < 24 and 0 <= mm < 60:
            due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if due <= now:
                due += timedelta(days=1)
            return due.timestamp(), msg
    return None


def _atomic_write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class TodoStore:
    def __init__(self, path=None):
        self.path = path or os.path.join(DATA_DIR, "todos.json")
        self.items = []
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, list):
                self.items = [{"text": str(i["text"])[:160], "done": bool(i.get("done"))}
                              for i in raw if isinstance(i, dict) and i.get("text")][:40]
        except (OSError, ValueError):
            pass

    def save(self):
        try:
            _atomic_write_json(self.path, self.items)
        except OSError:
            pass

    def add(self, text):
        t = (text or "").strip()
        if not t:
            return False
        self.items.insert(0, {"text": t[:160], "done": False})
        del self.items[40:]
        self.save()
        return True

    def toggle(self, idx):
        if 0 <= idx < len(self.items):
            self.items[idx]["done"] = not self.items[idx]["done"]
            self.save()

    def clear_done(self):
        before = len(self.items)
        self.items = [i for i in self.items if not i["done"]]
        if len(self.items) != before:
            self.save()


class ReminderStore:
    def __init__(self, path=None):
        self.path = path or os.path.join(DATA_DIR, "reminders.json")
        self.items = []
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, list):
                self.items = [{"due": float(i["due"]), "text": str(i["text"])[:160]}
                              for i in raw if isinstance(i, dict) and i.get("text")][:30]
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def save(self):
        try:
            _atomic_write_json(self.path, self.items)
        except OSError:
            pass

    def add(self, text, now=None):
        parsed = parse_reminder(text, now=now)
        if not parsed:
            return False
        due, msg = parsed
        self.items.append({"due": due, "text": msg})
        self.items.sort(key=lambda x: x["due"])
        self.save()
        return True

    def pop_due(self, now_ts=None):
        now_ts = time.time() if now_ts is None else now_ts
        due = [i for i in self.items if i["due"] <= now_ts]
        if due:
            self.items = [i for i in self.items if i["due"] > now_ts]
            self.save()
        return due


def play_chime():
    """Play a subtle desktop notification sound if available (non-blocking)."""
    for cmd in (["canberra-gtk-play", "-i", "bell"],
                ["paplay", "/usr/share/sounds/freedesktop/stereo/message.oga"]):
        if shutil.which(cmd[0]) and (len(cmd) < 2 or not cmd[1].startswith("/") or os.path.exists(cmd[1])):
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except OSError:
                pass


def parse_currency_spec(spec):
    """Parse 'USD: EUR, GBP' into ('USD', ['EUR', 'GBP'])."""
    raw = (spec or "USD: EUR, GBP").upper()
    if ":" in raw:
        base, rest = raw.split(":", 1)
    else:
        base, rest = "USD", raw
    base = re.sub(r"[^A-Z]", "", base)[:3] or "USD"
    targets = [re.sub(r"[^A-Z]", "", t)[:3] for t in rest.split(",")]
    targets = [t for t in targets if len(t) == 3 and t != base][:4]
    return base, targets or ["EUR", "GBP"]


def fetch_currency(spec):
    """Fetch latest exchange rates from api.frankfurter.app (free, no key)."""
    base, targets = parse_currency_spec(spec)
    url = f"https://api.frankfurter.app/latest?from={base}&to={','.join(targets)}"
    req = urllib.request.Request(url, headers={"User-Agent": "OpenNotch/1"})
    with urllib.request.urlopen(req, timeout=6) as r:
        data = json.loads(r.read().decode("utf-8"))
    rates = data.get("rates") or {}
    lines = [f"1 {base} = {rates[t]:.2f} {t}" for t in targets if t in rates]
    return lines or [f"{base} unavailable"]


def probe_ping(host):
    """Return latency in ms (float) or None."""
    host = (host or "1.1.1.1").strip()
    if not host or not re.fullmatch(r"[A-Za-z0-9._:-]{1,120}", host):
        return None
    if not shutil.which("ping"):
        return None
    try:
        r = subprocess.run(["ping", "-c", "1", "-W", "2", host], capture_output=True, text=True, timeout=3)
        if r.returncode != 0:
            return None
        m = re.search(r"time[=<]\s*([0-9.]+)\s*ms", r.stdout)
        return float(m.group(1)) if m else 0.0
    except (OSError, subprocess.SubprocessError):
        return None


def list_photos(folder):
    if not folder or not os.path.isdir(folder):
        return []
    exts = ("*.jpg", "*.jpeg", "*.png", "*.webp", "*.JPG", "*.JPEG", "*.PNG")
    out = []
    for pat in exts:
        out.extend(glob.glob(os.path.join(folder, pat)))
    return sorted(out)[:200]


# ---- GTK widget builders (used by Notch._build_overview) -----------------------

def _lbl(text, css="", xalign=0.0, ellipsize=True):
    lb = Gtk.Label(label=text, xalign=xalign)
    if ellipsize:
        lb.set_ellipsize(3)
    for c in css.split():
        lb.get_style_context().add_class(c)
    return lb


def build_todo_widget(want_keyboard):
    store = TodoStore()
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    head = Gtk.Box()
    head.pack_start(_lbl("To-do", "label", ellipsize=False), False, False, 0)
    clr = Gtk.Button(label="Clear done")
    clr.set_can_focus(False)
    clr.get_style_context().add_class("chip")
    head.pack_end(clr, False, False, 0)
    box.pack_start(head, False, False, 0)

    entry = Gtk.Entry(placeholder_text="Add a task…")
    entry.connect("button-press-event", want_keyboard)
    box.pack_start(entry, False, False, 0)

    lst = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
    sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, min_content_height=58, max_content_height=96)
    sw.add(lst)
    box.pack_start(sw, True, True, 0)

    def refresh():
        for ch in lst.get_children():
            ch.destroy()
        clr.set_visible(any(i["done"] for i in store.items))
        if not store.items:
            lst.pack_start(_lbl("Nothing on your list", "dim"), False, False, 0)
        for idx, item in enumerate(store.items[:12]):
            row = Gtk.CheckButton(label=item["text"])
            row.set_active(item["done"])
            row.set_can_focus(False)
            row.connect("toggled", lambda _b, i=idx: (store.toggle(i), refresh()))
            lst.pack_start(row, False, False, 0)
        lst.show_all()

    entry.connect("activate", lambda e: (store.add(e.get_text()), e.set_text(""), refresh()))
    clr.connect("clicked", lambda *_: (store.clear_done(), refresh()))
    refresh()
    return box


def build_calc_widget(want_keyboard, on_copy):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    box.pack_start(_lbl("Calculator", "label", ellipsize=False), False, False, 0)
    entry = Gtk.Entry(placeholder_text="25 * 4 + 12")
    entry.connect("button-press-event", want_keyboard)
    ans_btn = Gtk.Button()
    ans_btn.set_can_focus(False)
    ans_btn.get_style_context().add_class("flat")
    ans_lbl = _lbl("–", "bignum", ellipsize=False)
    ans_btn.add(ans_lbl)
    ans_btn.set_tooltip_text("Click to copy result")
    state = {"val": None}

    def update(*_):
        res = safe_eval_math(entry.get_text())
        state["val"] = res
        ans_lbl.set_text(res if res is not None else "–")

    entry.connect("changed", update)
    ans_btn.connect("clicked", lambda *_: state["val"] and on_copy(state["val"]))
    box.pack_start(entry, False, False, 0)
    box.pack_start(ans_btn, False, False, 0)
    return box


def build_countdown_widget(cfg):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    title = cfg.get("countdown_title") or "Countdown"
    box.pack_start(_lbl(title, "label"), False, False, 0)
    val = _lbl("–", "bignum", ellipsize=False)
    sub = _lbl("", "dim")
    box.pack_start(val, False, False, 0)
    box.pack_start(sub, False, False, 0)

    def refresh():
        h, s = countdown_parts(cfg.get("countdown_date", ""))
        val.set_text(h)
        sub.set_text(s)
        return True

    refresh()
    return box, refresh


def build_reminders_widget(want_keyboard, on_fire):
    store = ReminderStore()
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    box.pack_start(_lbl("Reminders", "label", ellipsize=False), False, False, 0)
    entry = Gtk.Entry(placeholder_text="10m Stretch  or  15:00 Call")
    entry.connect("button-press-event", want_keyboard)
    box.pack_start(entry, False, False, 0)
    lst = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    box.pack_start(lst, True, True, 0)

    def refresh():
        for ch in lst.get_children():
            ch.destroy()
        if not store.items:
            lst.pack_start(_lbl("No upcoming reminders", "dim"), False, False, 0)
        for item in store.items[:4]:
            when = time.strftime("%H:%M", time.localtime(item["due"]))
            lst.pack_start(_lbl(f"{when} · {item['text']}", "dim"), False, False, 0)
        lst.show_all()

    def check_due():
        for item in store.pop_due():
            play_chime()
            on_fire(item["text"])
            refresh()
        return True

    entry.connect("activate", lambda e: (store.add(e.get_text()) and e.set_text(""), refresh()))
    refresh()
    GLib.timeout_add_seconds(5, check_due)
    return box


def build_ping_widget(cfg):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    host = cfg.get("ping_host") or "1.1.1.1"
    box.pack_start(_lbl("Ping", "label", ellipsize=False), False, False, 0)
    val = _lbl("–", "bignum", ellipsize=False)
    sub = _lbl(host, "dim")
    box.pack_start(val, False, False, 0)
    box.pack_start(sub, False, False, 0)

    def refresh():
        def worker():
            ms = probe_ping(host)
            def apply():
                val.set_text(f"{ms:.0f} ms" if ms is not None else "Off")
                sub.set_text(f"Online · {host}" if ms is not None else f"Unreachable · {host}")
                return False
            GLib.idle_add(apply)
        threading.Thread(target=worker, daemon=True).start()
        return True

    refresh()
    GLib.timeout_add_seconds(30, refresh)
    return box


def build_currency_widget(cfg):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    spec = cfg.get("currency_watch") or "USD: EUR, GBP"
    box.pack_start(_lbl("Currency", "label", ellipsize=False), False, False, 0)
    lines_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    lines_box.pack_start(_lbl("Loading…", "dim"), False, False, 0)
    box.pack_start(lines_box, True, True, 0)

    def refresh():
        def worker():
            try:
                lines = fetch_currency(spec)
            except (OSError, urllib.error.URLError, ValueError):
                lines = ["Offline"]
            def apply():
                for ch in lines_box.get_children():
                    ch.destroy()
                for line in lines:
                    lines_box.pack_start(_lbl(line, "dim"), False, False, 0)
                lines_box.show_all()
                return False
            GLib.idle_add(apply)
        threading.Thread(target=worker, daemon=True).start()
        return True

    refresh()
    GLib.timeout_add_seconds(1800, refresh)
    return box


def build_photos_widget(cfg):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    box.pack_start(_lbl("Photos", "label", ellipsize=False), False, False, 0)
    img = Gtk.Image()
    img.set_size_request(180, 90)
    sub = _lbl("", "dim")
    box.pack_start(img, True, True, 0)
    box.pack_start(sub, False, False, 0)
    state = {"idx": 0}

    def refresh():
        paths = list_photos(cfg.get("photos_folder", ""))
        if not paths:
            img.clear()
            sub.set_text("Pick a folder in Settings › Widgets")
            return True
        path = paths[state["idx"] % len(paths)]
        state["idx"] += 1
        try:
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 220, 100, True)
            img.set_from_pixbuf(pb)
            sub.set_text(os.path.basename(path))
        except GLib.Error:
            sub.set_text("Unable to load photo")
        return True

    refresh()
    GLib.timeout_add_seconds(30, refresh)
    return box
