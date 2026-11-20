"""User-initiated screenshot and screen recording on X11."""
from datetime import datetime
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from gi.repository import Gdk, GLib

RECORDER_APP = "OpenNotch Recorder"


def capture_dir(kind):
    photos = kind == "screenshot"
    category = GLib.UserDirectory.DIRECTORY_PICTURES if photos else GLib.UserDirectory.DIRECTORY_VIDEOS
    base = GLib.get_user_special_dir(category)
    folder = Path(base) if base else Path.home() / ("Pictures" if photos else "Videos")
    folder /= "OpenNotch"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    return folder


def reserve_capture(kind, suffix):
    stamp = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    prefix = "Screenshot" if kind == "screenshot" else "Recording"
    fd, name = tempfile.mkstemp(prefix=f"{prefix} {stamp} ", suffix=suffix, dir=capture_dir(kind))
    os.close(fd)
    return Path(name)


def screenshot(monitor):
    root = Gdk.get_default_root_window()
    bounds = monitor.get_geometry()
    image = Gdk.pixbuf_get_from_window(root, bounds.x, bounds.y, bounds.width, bounds.height)
    if image is None:
        raise ValueError("Could not read the X11 screen.")
    path = reserve_capture("screenshot", ".png")
    try:
        image.savev(str(path), "png", [], [])
    except (GLib.Error, OSError):
        path.unlink(missing_ok=True)
        raise
    return path


class ScreenRecorder:
    def __init__(self, on_change):
        self.on_change = on_change
        self.process = None
        self.started_at = None
        self.timer = 0
        self.stopping = False

    @property
    def active(self):
        return self.process is not None

    def start(self, monitor, microphone=False, pc_sound=False):
        ffmpeg = shutil.which("ffmpeg")
        display = os.environ.get("DISPLAY")
        if ffmpeg is None:
            raise ValueError("FFmpeg is required for screen recording.")
        if not display:
            raise ValueError("Screen recording requires an X11 display.")
        bounds = monitor.get_geometry()
        scale = monitor.get_scale_factor()
        x, y = bounds.x * scale, bounds.y * scale
        # H.264 with 4:2:0 sampling requires even dimensions.
        width, height = (bounds.width * scale) & ~1, (bounds.height * scale) & ~1
        if x < 0 or y < 0 or width < 2 or height < 2:
            raise ValueError("The selected screen is outside the X11 capture area.")
        argv = [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "x11grab", "-framerate", "30",
                "-video_size", f"{width}x{height}", "-i", f"{display}+{x},{y}"]
        if microphone and pc_sound:
            argv += ["-thread_queue_size", "512", "-f", "pulse", "-name", RECORDER_APP, "-i", "default",
                     "-thread_queue_size", "512", "-f", "pulse", "-name", RECORDER_APP, "-i", "@DEFAULT_SINK@.monitor",
                     "-filter_complex", "[1:a][2:a]amix=inputs=2:duration=longest[a]",
                     "-map", "0:v:0", "-map", "[a]", "-c:a", "aac"]
        elif microphone:
            argv += ["-thread_queue_size", "512", "-f", "pulse", "-name", RECORDER_APP, "-i", "default",
                     "-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac"]
        elif pc_sound:
            argv += ["-thread_queue_size", "512", "-f", "pulse", "-name", RECORDER_APP, "-i", "@DEFAULT_SINK@.monitor",
                     "-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac"]
        else:
            argv += ["-an"]
        argv += ["-c:v", "libx264", "-threads", "2", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                 "-g", "30", "-movflags", "+frag_keyframe+empty_moov+default_base_moof", "-y"]
        self.partial = reserve_capture("recording", ".partial.mp4")
        self.target = self.partial.with_name(self.partial.name.replace(".partial.mp4", ".mp4"))
        self.errors = tempfile.TemporaryFile()
        try:
            guard = [sys.executable, "-m", "opennotch.captureguard", str(os.getpid())]
            self.process = subprocess.Popen([*guard, *argv, str(self.partial)], stdin=subprocess.PIPE,
                                            stdout=subprocess.DEVNULL, stderr=self.errors)
        except OSError:
            self.errors.close()
            self.partial.unlink(missing_ok=True)
            raise
        self.started_at = time.monotonic()
        self.stopping = False
        self.timer = GLib.timeout_add(200, self._poll)
        self.on_change("started", None, None)

    def _request_stop(self):
        if self.stopping or not self.active:
            return
        self.stopping = True
        self.stop_deadline = time.monotonic() + 4
        try:
            self.process.stdin.write(b"q\n")
            self.process.stdin.flush()
        except BrokenPipeError:
            pass

    def stop(self):
        self._request_stop()

    def _poll(self):
        status = self.process.poll()
        if status is not None:
            self.timer = 0
            self._finish(status)
            return GLib.SOURCE_REMOVE
        if self.stopping and time.monotonic() >= self.stop_deadline:
            self.process.kill()
        return GLib.SOURCE_CONTINUE

    def _finish(self, status, notify=True):
        try:
            self.process.stdin.close()
        except BrokenPipeError:
            pass
        self.errors.seek(0)
        lines = self.errors.read(4096).decode("utf-8", errors="replace").strip().splitlines()
        self.errors.close()
        self.process = None
        self.started_at = None
        try:
            has_data = self.partial.stat().st_size > 1024
            if status == 0 and has_data:
                self.partial.replace(self.target)
                event, path, error = "saved", self.target, None
            else:
                path = self.partial if has_data else None
                if path is None:
                    self.partial.unlink(missing_ok=True)
                event, error = "failed", lines[0] if lines else "FFmpeg stopped before saving a complete recording."
        except OSError as exc:
            event, path, error = "failed", self.partial, str(exc)
        if notify:
            self.on_change(event, path, error)

    def close(self):
        """Flush the recording before replacing the app or quitting."""
        if not self.active:
            return
        self._request_stop()
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0
        try:
            self.process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self._finish(self.process.returncode, notify=False)
