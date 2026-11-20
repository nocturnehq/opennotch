"""Super+1…9: open or switch to the app pinned at that position in the Plank dock."""
import configparser
import os
from urllib.parse import unquote, urlparse

from gi.repository import Gio

PLANK_SCHEMA = "net.launchpad.plank.dock.settings"
PLANK_PATH = "/net/launchpad/plank/docks/dock1/"
LAUNCHERS = os.path.expanduser("~/.config/plank/dock1/launchers")


def launcher_path(dockitem_text):
    """A .dockitem's Launcher=file://… → local .desktop path, or None."""
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(dockitem_text)
        url = parser["PlankDockItemPreferences"]["Launcher"]
    except (configparser.Error, KeyError):
        return None
    parsed = urlparse(url)
    return unquote(parsed.path) if parsed.scheme == "file" and parsed.path.endswith(".desktop") else None


def pinned():
    """The dock's .desktop files in dock order."""
    source = Gio.SettingsSchemaSource.get_default()
    if source is None or source.lookup(PLANK_SCHEMA, True) is None:
        return []
    paths = []
    for item in Gio.Settings.new_with_path(PLANK_SCHEMA, PLANK_PATH).get_strv("dock-items"):
        try:
            with open(os.path.join(LAUNCHERS, os.path.basename(item))) as f:
                path = launcher_path(f.read())
        except OSError:
            continue
        if path:
            paths.append(path)
    return paths


def window_keys(app):
    """Lower-case names a window of this app may carry as its WM_CLASS."""
    stem = os.path.basename(app.get_filename() or "").removesuffix(".desktop").lower()
    exe = (app.get_executable() or "").rsplit("/", 1)[-1].lower()
    keys = {stem} | ({exe} - {"flatpak", "snap", "env", "sh", "bash", "python3"})  # wrappers name no app
    wm_class = app.get_startup_wm_class()
    if wm_class:
        keys.add(wm_class.lower())
    return keys - {""}


def pick_window(windows, active):
    """The window to raise: the app's next window after the active one, else its first. Windows are in stacking order."""
    if not windows:
        return None
    if active in windows:
        return windows[(windows.index(active) + 1) % len(windows)]
    return windows[-1]  # topmost


def open_position(n, timestamp):
    """Raise or start the app pinned at position n (1-based). Returns a reason string when nothing happened."""
    apps = pinned()
    if not 1 <= n <= len(apps):
        return f"Nothing pinned at position {n}."
    app = Gio.DesktopAppInfo.new_from_filename(apps[n - 1])
    if app is None:
        return f"The app pinned at position {n} is missing."
    try:
        import gi

        gi.require_version("Wnck", "3.0")
        from gi.repository import Wnck
    except (ImportError, ValueError):
        Wnck = None
    if Wnck is not None:
        screen = Wnck.Screen.get_default()
        screen.force_update()
        keys = window_keys(app)
        windows = [w for w in screen.get_windows_stacked()
                   if not w.is_skip_tasklist() and {(w.get_class_group_name() or "").lower(),
                                                    (w.get_class_instance_name() or "").lower()} & keys]
        window = pick_window(windows, screen.get_active_window())
        if window is not None:
            window.activate(timestamp)
            return None
    app.launch([], None)
    return None
