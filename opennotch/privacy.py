"""Report active video sources that PipeWire identifies as a camera or screen share."""
import json
import shutil

from gi.repository import Gio, GLib


def active_video(objects, ignored=""):
    ignore_tokens = [t.strip().lower() for t in (ignored or "").split(",") if t.strip()]
    active = set()
    for node in objects:
        if not isinstance(node, dict) or node.get("type") != "PipeWire:Interface:Node":
            continue
        info = node.get("info") or {}
        if not isinstance(info, dict) or str(info.get("state", "")).casefold() != "running":
            continue
        props = info.get("props") or {}
        if not isinstance(props, dict):
            continue
        if ignore_tokens:
            ident = " ".join(str(props.get(k, "")) for k in ("application.name", "node.name", "node.description")).lower()
            if any(t in ident for t in ignore_tokens):
                continue
        media_class = str(props.get("media.class", "")).casefold()
        role = str(props.get("media.role", "")).casefold()
        factory = str(props.get("factory.name", "")).casefold()
        if "/video" in media_class or media_class.startswith("video/"):
            if role in {"screen", "screencast", "screenshare"}:
                active.add("Screen sharing")
            if role == "camera" or media_class == "video/source" and (
                str(props.get("device.api", "")).casefold() in {"v4l2", "libcamera"} or
                "v4l2" in factory or "libcamera" in factory or props.get("api.v4l2.path")
            ):
                active.add("Camera")
    return active


class VideoPrivacyWatch:
    def __init__(self, changed, ignored=""):
        self.changed = changed
        self.ignored = ignored
        self.command = shutil.which("pw-dump")
        self.process = None
        self.timeout = 0
        self.active = set()
        self._last_raw = None
        if self.command:
            self._poll()
            GLib.timeout_add_seconds(8, self._poll)

    def _poll(self):
        if self.process is not None:
            return GLib.SOURCE_CONTINUE
        try:
            self.process = Gio.Subprocess.new([self.command], Gio.SubprocessFlags.STDOUT_PIPE |
                                              Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error:
            return GLib.SOURCE_CONTINUE
        self.timeout = GLib.timeout_add_seconds(2, self._expire, self.process)
        self.process.communicate_utf8_async(None, None, self._finished)
        return GLib.SOURCE_CONTINUE

    def _expire(self, process):
        self.timeout = 0
        if self.process == process:
            process.force_exit()
        return GLib.SOURCE_REMOVE

    def _finished(self, process, result):
        try:
            _, output, _ = process.communicate_utf8_finish(result)
            if process.get_successful():
                if output == self._last_raw:
                    active = self.active
                else:
                    self._last_raw = output
                    nodes = json.loads(output)
                    active = active_video(nodes, self.ignored) if isinstance(nodes, list) else set()
            else:
                active = set()
        except (GLib.Error, ValueError):
            active = set()
        self.process = None
        if self.timeout:
            GLib.source_remove(self.timeout)
        self.timeout = 0
        if self.active != active:
            self.active = active
            self.changed(active)
