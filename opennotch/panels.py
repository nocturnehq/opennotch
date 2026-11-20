"""Extra island panels & media helpers: Quick Launcher / Deck, Camera Mirror, and Media Info on Drop."""
import json
import os
import shlex
import shutil
import subprocess
import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

MEDIA_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".mp3", ".flac", ".wav", ".ogg", ".m4a", ".opus"}


def probe_media_info(path):
    """Return a concise one-line summary for a video/audio file via ffprobe, or None."""
    if not path or not os.path.isfile(path):
        return None
    if os.path.splitext(path)[1].lower() not in MEDIA_EXTS:
        return None
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        out = subprocess.check_output(
            [ffprobe, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", path],
            text=True, timeout=4,
        )
        data = json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    parts = [os.path.basename(path)]
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if v and v.get("width") and v.get("height"):
        parts.append(f"{v['width']}×{v['height']}")
    dur = float(fmt.get("duration") or 0)
    if dur > 0:
        m, s = divmod(int(round(dur)), 60)
        parts.append(f"{m}:{s:02d}")
    codec = (v or a or {}).get("codec_name")
    if codec:
        parts.append(codec)
    return " · ".join(parts)


def parse_launch_apps(raw):
    """Parse comma-separated commands or .desktop names into a clean list (max 6)."""
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()][:6]


def _launch_entry(spec):
    """Launch a .desktop app id or shell command safely (detached)."""
    for candidate in (spec, spec + ".desktop"):
        app = Gio.DesktopAppInfo.new(candidate)
        if app is not None:
            try:
                app.launch([], None)
                return True
            except GLib.Error:
                pass
    try:
        argv = shlex.split(spec)
        if argv and shutil.which(argv[0]):
            subprocess.Popen(argv, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
    except (OSError, ValueError):
        pass
    return False


def _default_apps():
    """Pick up to 6 installed everyday apps when the user hasn't customized launch_apps."""
    candidates = [
        ("Files", "folder-symbolic", ["nemo", "dolphin", "nautilus", "thunar"]),
        ("Browser", "web-browser-symbolic", ["brave-browser", "firefox", "chromium", "google-chrome"]),
        ("Terminal", "utilities-terminal-symbolic", ["gnome-terminal", "konsole", "kitty", "alacritty", "xterm"]),
        ("Editor", "accessories-text-editor-symbolic", ["code", "kate", "xed", "gedit"]),
        ("Calculator", "accessories-calculator-symbolic", ["kcalc", "gnome-calculator", "galculator"]),
        ("Settings", "emblem-system-symbolic", ["systemsettings5", "systemsettings", "cinnamon-settings"]),
    ]
    found = []
    for title, icon, cmds in candidates:
        cmd = next((c for c in cmds if shutil.which(c)), None)
        if cmd:
            found.append((title, icon, cmd))
    return found


def build_launcher_panel(cfg, actions, on_launched):
    """Build the Launcher & Deck tab: quick app tiles + Deck macro buttons."""
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, valign=Gtk.Align.CENTER)

    custom = parse_launch_apps(cfg.get("launch_apps", ""))
    if custom:
        apps = [(os.path.basename(c).replace(".desktop", "").capitalize()[:14], "application-x-executable-symbolic", c)
                for c in custom]
    else:
        apps = _default_apps()

    grid = Gtk.Grid(column_spacing=8, row_spacing=8, column_homogeneous=True)
    for idx, (title, icon, cmd) in enumerate(apps[:6]):
        btn = Gtk.Button()
        btn.set_can_focus(False)
        btn.get_style_context().add_class("tile")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin=8)
        img = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR)
        lbl = Gtk.Label(label=title, xalign=0.5)
        lbl.set_ellipsize(3)
        box.pack_start(img, False, False, 0)
        box.pack_start(lbl, False, False, 0)
        btn.add(box)
        btn.connect("clicked", lambda _b, c=cmd: (_launch_entry(c), on_launched()))
        grid.attach(btn, idx % 3, idx // 3, 1, 1)
    outer.pack_start(grid, False, False, 0)

    # Deck macro row
    deck = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
    for label_txt, icon_name, cb in actions:
        b = Gtk.Button()
        b.set_can_focus(False)
        b.get_style_context().add_class("chip")
        row = Gtk.Box(spacing=5)
        row.pack_start(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU), False, False, 0)
        row.pack_start(Gtk.Label(label=label_txt), False, False, 0)
        b.add(row)
        b.connect("clicked", lambda _b, f=cb: (f(), on_launched()))
        deck.pack_start(b, False, False, 0)
    outer.pack_start(deck, False, False, 0)
    return outer


class CameraMirror(Gtk.Box):
    """On-demand webcam mirror inside the island: opens /dev/video0 ONLY while active."""

    W, H = 320, 180

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6, valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        self.img = Gtk.Image()
        self.img.set_size_request(self.W, self.H)
        self.status = Gtk.Label(label="Camera off")
        self.status.get_style_context().add_class("dim")
        self.pack_start(self.img, False, False, 0)
        self.pack_start(self.status, False, False, 0)
        self.proc = None
        self.running = False

    def start(self):
        if self.running:
            return
        if not os.path.exists("/dev/video0") or not shutil.which("ffmpeg"):
            self.status.set_text("No camera found (/dev/video0)")
            return
        self.running = True
        self.status.set_text("Live mirror")
        threading.Thread(target=self._reader, daemon=True).start()

    def stop(self):
        self.running = False
        proc, self.proc = self.proc, None
        if proc is not None:
            try:
                proc.terminate()
            except OSError:
                pass
        self.img.clear()
        self.status.set_text("Camera off")

    def _reader(self):
        frame_bytes = self.W * self.H * 3
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "v4l2", "-i", "/dev/video0",
            "-vf", f"hflip,scale={self.W}:{self.H}:force_original_aspect_ratio=increase,crop={self.W}:{self.H}",
            "-r", "15", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ]
        try:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError:
            GLib.idle_add(lambda: (self.status.set_text("Unable to open camera"), False)[1])
            self.running = False
            return
        try:
            while self.running and self.proc and self.proc.stdout:
                raw = self.proc.stdout.read(frame_bytes)
                if len(raw) < frame_bytes:
                    break
                pb = GdkPixbuf.Pixbuf.new_from_bytes(
                    GLib.Bytes.new(raw), GdkPixbuf.Colorspace.RGB, False, 8, self.W, self.H, self.W * 3
                )
                GLib.idle_add(self._set_frame, pb)
        finally:
            self.stop()

    def _set_frame(self, pb):
        if self.running:
            self.img.set_from_pixbuf(pb)
        return False
