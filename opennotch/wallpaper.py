"""Native desktop playback for user-selected local videos on X11."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import gi
from gi.repository import Gio, GLib

PLASMA_PLUGIN = "org.opennotch.local.video"
CINNAMON_EXTENSION = "video-wallpaper@opennotch"

PLASMA_QML = """import QtQuick 2.15
import QtMultimedia 5.15

Item {
    Image {
        anchors.fill: parent
        fillMode: Image.PreserveAspectCrop
        source: wallpaper.configuration.FallbackUri
    }
    Video {
        anchors.fill: parent
        visible: status !== MediaPlayer.InvalidMedia
        muted: true
        fillMode: VideoOutput.PreserveAspectCrop
        loops: MediaPlayer.Infinite
        source: wallpaper.configuration.VideoUri
        autoPlay: true
    }
}
"""

PLASMA_CONFIG = """<kcfg xmlns="http://www.kde.org/standards/kcfg/1.0">
<group name="General">
  <entry name="VideoUri" type="String"><default></default></entry>
  <entry name="FallbackUri" type="String"><default></default></entry>
</group>
</kcfg>
"""

# Cinnamon links its own Clutter ABI. GstApp is safe to use there, but
# ClutterGst is linked against the public Clutter ABI and must not be loaded.
CINNAMON_JS = """const {Clutter, Cogl, Gio, GLib, Gst, GstApp, GstVideo} = imports.gi;
const Main = imports.ui.main;
const ByteArray = imports.byteArray;

let directory;
let player, image, container, bus, sink;
let timer = 0;
let monitorsChanged = 0;
let dimensions = null;
let surfaces = [];
let configMonitor = null;
let reloadTimer = 0;

function init(metadata) {
    directory = metadata.path;
}

function layout() {
    for (const old of surfaces)
        old.frame.destroy();
    surfaces = [];

    for (const monitor of Main.layoutManager.monitors) {
        const frame = new Clutter.Actor({x: monitor.x, y: monitor.y, width: monitor.width,
            height: monitor.height, clip_to_allocation: true, reactive: false});
        const picture = new Clutter.Actor({content: image, reactive: false});
        container.add_child(frame);
        frame.add_child(picture);
        surfaces.push({frame, picture});
    }
    resizeSurfaces();
}

function resizeSurfaces() {
    if (!dimensions)
        return;
    const [width, height] = dimensions;
    for (const {frame, picture} of surfaces) {
        const scale = Math.max(frame.width / width, frame.height / height);
        picture.set_size(width * scale, height * scale);
        picture.set_position((frame.width - picture.width) / 2, (frame.height - picture.height) / 2);
    }
}

function paintFrame() {
    try {
        const message = bus.pop_filtered(Gst.MessageType.ERROR | Gst.MessageType.EOS);
        if (message && message.type === Gst.MessageType.ERROR)
            throw message.parse_error()[0];
        if (message)
            player.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, 0);

        const sample = sink.try_pull_sample(0);
        if (sample) {
            const info = GstVideo.VideoInfo.new_from_caps(sample.get_caps());
            const buffer = sample.get_buffer();
            const data = buffer.extract_dup(info.offset[0], info.stride[0] * info.height);
            image.set_data(data, Cogl.PixelFormat.RGBA_8888, info.width, info.height, info.stride[0]);
            const displayWidth = info.width * info.par_n / info.par_d;
            if (!dimensions || dimensions[0] !== displayWidth || dimensions[1] !== info.height) {
                dimensions = [displayWidth, info.height];
                resizeSurfaces();
            }
            container.show();
        }
    } catch (error) {
        global.logError("OpenNotch wallpaper: " + error);
        timer = 0;
        stopPlayback();
        return GLib.SOURCE_REMOVE;
    }
    return GLib.SOURCE_CONTINUE;
}

function startPlayback() {
    const config = Gio.File.new_for_path(directory + "/clip.json");
    const [, contents] = config.load_contents(null);
    const {uri} = JSON.parse(ByteArray.toString(contents));
    if (!uri || !uri.startsWith("file://"))
        throw new Error("OpenNotch wallpaper requires a local video.");

    Gst.init(null);
    try {
        const background = global.background_actor;
        image = new Clutter.Image();
        container = new Clutter.Actor({reactive: false, visible: false});
        background.get_parent().insert_child_above(container, background);
        layout();
        monitorsChanged = Main.layoutManager.connect("monitors-changed", layout);

        player = Gst.ElementFactory.make("playbin", null);
        const video = Gst.parse_bin_from_description(
            "videoconvert ! videoscale ! videorate drop-only=true " +
            "! video/x-raw,format=RGBA,width=(int)[1,1280],height=(int)[1,720],framerate=(fraction)[0/1,24/1] " +
            "! appsink name=frames max-buffers=1 drop=true wait-on-eos=false", true);
        sink = video.get_by_name("frames");
        player.set_property("flags", 1);
        player.set_property("video-sink", video);
        player.set_property("uri", uri);
        bus = player.get_bus();
        if (player.set_state(Gst.State.PLAYING) === Gst.StateChangeReturn.FAILURE)
            throw new Error("Could not start video playback.");
        timer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 40, paintFrame);
    } catch (error) {
        stopPlayback();
        throw error;
    }
}

function enable() {
    startPlayback();
    const config = Gio.File.new_for_path(directory + "/clip.json");
    configMonitor = config.monitor_file(Gio.FileMonitorFlags.WATCH_MOVES, null);
    configMonitor.connect("changed", () => {
        if (reloadTimer)
            GLib.Source.remove(reloadTimer);
        reloadTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 150, () => {
            reloadTimer = 0;
            stopPlayback();
            try {
                startPlayback();
            } catch (error) {
                global.logError("OpenNotch wallpaper: " + error);
            }
            return GLib.SOURCE_REMOVE;
        });
    });
}

function disable() {
    if (reloadTimer)
        GLib.Source.remove(reloadTimer);
    if (configMonitor)
        configMonitor.cancel();
    reloadTimer = 0;
    configMonitor = null;
    stopPlayback();
}

function stopPlayback() {
    if (timer)
        GLib.Source.remove(timer);
    if (monitorsChanged)
        Main.layoutManager.disconnect(monitorsChanged);
    if (player)
        player.set_state(Gst.State.NULL);
    if (container)
        container.destroy();
    timer = monitorsChanged = 0;
    player = image = container = bus = sink = dimensions = null;
    surfaces = [];
}
"""


def _atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        return
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as out:
        staging = Path(out.name)
        try:
            out.write(content)
            out.close()
            staging.replace(path)
        finally:
            staging.unlink(missing_ok=True)


def _video_uri(file):
    try:
        path = Path(file).expanduser().resolve(strict=True)
    except OSError as error:
        raise ValueError("Choose an existing local video.") from error
    if not path.is_file():
        raise ValueError("Choose an existing local video.")

    gi.require_version("Gst", "1.0")
    gi.require_version("GstPbutils", "1.0")
    from gi.repository import Gst, GstPbutils

    Gst.init(None)
    uri = path.as_uri()
    info = GstPbutils.Discoverer.new(2 * Gst.SECOND).discover_uri(uri)
    if info.get_result() != GstPbutils.DiscovererResult.OK or not info.get_video_streams():
        raise ValueError("This file could not be opened as a video.")
    if info.get_duration() in (0, Gst.CLOCK_TIME_NONE):
        raise ValueError("Choose a finite video file.")
    return uri


class LiveWallpaper:
    """Opt-in wallpaper session. Call close() before stopping OpenNotch."""

    def __init__(self, file):
        desktops = os.environ.get("XDG_CURRENT_DESKTOP", "").upper().split(":")
        self.desktop = ("plasma" if "KDE" in desktops else
                        "cinnamon" if "X-CINNAMON" in desktops or "CINNAMON" in desktops else None)
        self.file = file
        self.data = Path(GLib.get_user_data_dir())
        self.snapshot = Path(GLib.get_user_state_dir()) / "opennotch" / "wallpaper-plasma.json"
        self.started = False
        self.settings = None

    def start(self):
        if self.started:
            return
        if not os.environ.get("DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland":
            raise ValueError("Video wallpaper requires an X11 session.")
        if self.desktop is None:
            raise ValueError("Video wallpaper requires Plasma or Cinnamon.")
        uri = _video_uri(self.file)
        if self.desktop == "plasma":
            self._start_plasma(uri)
        else:
            self._start_cinnamon(uri)
        self.started = True

    def close(self):
        if not self.started:
            return
        if self.desktop == "plasma":
            self._restore_plasma()
        else:
            self._stop_cinnamon(self.settings)
        self.started = False

    @staticmethod
    def _plasma_eval(script):
        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        reply = bus.call_sync(
            "org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell", "evaluateScript",
            GLib.Variant("(s)", (script,)), GLib.VariantType.new("(s)"),
            Gio.DBusCallFlags.NO_AUTO_START, 3000, None,
        )
        return reply.unpack()[0].strip()

    def _plasma_desktops(self):
        result = self._plasma_eval("""
            print(JSON.stringify(desktops().map(d => {
                const plugin = d.wallpaperPlugin;
                d.currentConfigGroup = ["Wallpaper", plugin, "General"];
                return [d.id, plugin, plugin === "org.kde.image" ? d.readConfig("Image", "") : ""];
            })));
        """)
        try:
            desktops = json.loads(result)
        except ValueError as error:
            raise RuntimeError("Plasma did not return its current wallpaper layout.") from error
        if not desktops:
            raise RuntimeError("Plasma has not created a desktop yet.")
        return desktops

    def _restore_plasma(self):
        try:
            saved = json.loads(self.snapshot.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        expected = json.dumps(PLASMA_PLUGIN)
        changed = self._plasma_eval(f"""
            const previous = {json.dumps(saved)};
            const restored = [];
            for (const desktop of desktops()) {{
                if (previous[desktop.id]) {{
                    if (desktop.wallpaperPlugin === {expected})
                        desktop.wallpaperPlugin = previous[desktop.id];
                    if (desktop.wallpaperPlugin !== {expected})
                        restored.push(String(desktop.id));
                }}
            }}
            print(JSON.stringify(restored));
        """)
        try:
            restored = json.loads(changed)
        except ValueError as error:
            raise RuntimeError("Plasma did not confirm the wallpaper restore.") from error
        # Plasma saves its configuration asynchronously. Keep enough recovery
        # data if plasmashell is killed before it flushes the restored plugin.
        persisted = self._persisted_plasma_video_desktops()
        remaining = {identifier: plugin for identifier, plugin in saved.items()
                     if identifier not in restored or identifier in persisted}
        if remaining:
            _atomic_write(self.snapshot, json.dumps(remaining))
        else:
            self.snapshot.unlink(missing_ok=True)

    @staticmethod
    def _persisted_plasma_video_desktops():
        config = Path(GLib.get_user_config_dir()) / "plasma-org.kde.plasma.desktop-appletsrc"
        try:
            contents = config.read_text(encoding="utf-8")
        except (FileNotFoundError, UnicodeError):
            return set()
        pattern = (r"^\[Containments\]\[(\d+)\]\n(?:(?!^\[).+\n)*?"
                   r"^wallpaperplugin=" + re.escape(PLASMA_PLUGIN) + r"$")
        return set(re.findall(pattern, contents, re.M))

    def _start_plasma(self, uri):
        desktops = self._plasma_desktops()
        package = self.data / "plasma" / "wallpapers" / PLASMA_PLUGIN
        metadata = {"KPackageStructure": "Plasma/Wallpaper",
                    "KPlugin": {"Id": PLASMA_PLUGIN, "Name": "OpenNotch Video", "Version": "1.0"},
                    "X-Plasma-API": "declarativeappletscript"}
        _atomic_write(package / "metadata.json", json.dumps(metadata))
        _atomic_write(package / "contents" / "ui" / "main.qml", PLASMA_QML)
        _atomic_write(package / "contents" / "config" / "main.xml", PLASMA_CONFIG)
        try:
            previous = json.loads(self.snapshot.read_text(encoding="utf-8"))
        except FileNotFoundError:
            previous = {}
        for identifier, plugin, _ in desktops:
            if plugin != PLASMA_PLUGIN:
                previous[str(identifier)] = plugin
        _atomic_write(self.snapshot, json.dumps(previous))

        fallbacks = {str(identifier): image for identifier, _, image in desktops if image}
        plugin = json.dumps(PLASMA_PLUGIN)
        try:
            result = self._plasma_eval(f"""
                const fallbacks = {json.dumps(fallbacks)};
                let count = 0;
                for (const d of desktops()) {{
                    d.currentConfigGroup = ["Wallpaper", {plugin}, "General"];
                    d.writeConfig("VideoUri", {json.dumps(uri)});
                    if (fallbacks[d.id])
                        d.writeConfig("FallbackUri", fallbacks[d.id]);
                    if (d.wallpaperPlugin !== {plugin})
                        d.wallpaperPlugin = {plugin};
                    if (d.wallpaperPlugin === {plugin})
                        count++;
                }}
                print(JSON.stringify(count));
            """)
            if not result.isdecimal() or int(result) != len(desktops):
                raise RuntimeError("Plasma did not activate the video wallpaper on every desktop.")
        except (GLib.Error, RuntimeError):
            self._restore_plasma()
            raise

    @staticmethod
    def _stop_cinnamon(settings):
        extensions = settings.get_strv("enabled-extensions")
        if CINNAMON_EXTENSION in extensions:
            if not settings.set_strv("enabled-extensions", [uuid for uuid in extensions if uuid != CINNAMON_EXTENSION]):
                raise ValueError("Cinnamon could not disable video wallpaper.")
            Gio.Settings.sync()

    @staticmethod
    def _cinnamon_package(data):
        return data / "cinnamon" / "extensions" / CINNAMON_EXTENSION

    def _start_cinnamon(self, uri):
        program = shutil.which("cinnamon")
        if not program:
            raise ValueError("Cinnamon is unavailable.")
        version = subprocess.run([program, "--version"], capture_output=True, text=True,
                                 timeout=3, check=True).stdout
        match = re.search(r"Cinnamon (\d+\.\d+)\.", version)
        if not match or match[1] != "6.6":
            raise ValueError("The video wallpaper adapter requires Cinnamon 6.6.")

        settings = Gio.Settings.new("org.cinnamon")
        if not settings.is_writable("enabled-extensions"):
            raise ValueError("Cinnamon extensions are locked.")
        package = self._cinnamon_package(self.data)
        metadata = {"uuid": CINNAMON_EXTENSION, "name": "OpenNotch Video",
                    "description": "Local video wallpaper for OpenNotch",
                    "cinnamon-version": [match[1]], "version": 1}
        _atomic_write(package / "metadata.json", json.dumps(metadata))
        _atomic_write(package / "extension.js", CINNAMON_JS)
        _atomic_write(package / "clip.json", json.dumps({"uri": uri}))
        extensions = settings.get_strv("enabled-extensions")
        if CINNAMON_EXTENSION not in extensions:
            if not settings.set_strv("enabled-extensions", [*extensions, CINNAMON_EXTENSION]):
                raise ValueError("Cinnamon could not enable video wallpaper.")
            Gio.Settings.sync()
        self.settings = settings


def recover_pending_wallpaper():
    """Restore settings left by a previously interrupted wallpaper session."""
    wallpaper = LiveWallpaper(None)
    if wallpaper.desktop == "plasma" and wallpaper.snapshot.is_file():
        wallpaper._restore_plasma()
    elif wallpaper.desktop == "cinnamon" and wallpaper._cinnamon_package(wallpaper.data).is_dir():
        wallpaper._stop_cinnamon(Gio.Settings.new("org.cinnamon"))
