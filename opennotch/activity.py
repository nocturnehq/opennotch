"""Battery, Bluetooth and keyboard state notices shared by both X11 desktops."""
from gi.repository import Gdk, Gio, GLib

from . import system

DEVICE = "org.bluez.Device1"
BATTERY = "org.bluez.Battery1"


class ActivityWatch:
    def __init__(self, cfg, show):
        self.show = show
        if cfg["show_lock_keys_hud"]:
            keymap = Gdk.Keymap.get_for_display(Gdk.Display.get_default())
            self.locks = self._lock_state(keymap)
            keymap.connect("state-changed", self._lock_changed)
        if cfg["show_battery_hud"]:
            self.power = system.battery_alert_state()
            GLib.timeout_add_seconds(2, self._check_battery)
        if cfg["show_download_activity"]:
            self._watch_downloads()
        if cfg["show_bluetooth_hud"]:
            self.bluez = None
            self.connected = {}
            self.bluetooth_update = 0
            Gio.DBusObjectManagerClient.new_for_bus(
                Gio.BusType.SYSTEM, Gio.DBusObjectManagerClientFlags.DO_NOT_AUTO_START,
                "org.bluez", "/", None, None, None, self._bluez_ready, None,
            )

    @staticmethod
    def _lock_state(keymap):
        return keymap.get_caps_lock_state(), keymap.get_num_lock_state()

    def _lock_changed(self, keymap):
        state = self._lock_state(keymap)
        old, self.locks = self.locks, state
        for was_on, is_on, name, icon in zip(
            old, state, ("Caps Lock", "Num Lock"),
            ("go-up-symbolic", "input-keyboard-symbolic"),
        ):
            if was_on != is_on:
                self.show(f"{name} {'on' if is_on else 'off'}", icon, is_on)

    def _check_battery(self):
        state = system.battery_alert_state()
        old, self.power = self.power, state
        if old is None or state is None:
            return True
        percent, plugged = state
        if plugged != old[1]:
            name = "Plugged in" if plugged else "Unplugged"
        elif not plugged and percent <= 20 < old[0]:
            name = "Low battery"
        else:
            return True
        level = min(100, (percent + 5) // 10 * 10)
        icon = f"battery-level-{level}{'-charging' if plugged else ''}-symbolic"
        self.show(f"{name} · {percent}%", icon, plugged)
        return True

    @staticmethod
    def _property(proxy, name):
        value = proxy.get_cached_property(name) if proxy else None
        return value.unpack() if value is not None else None

    def _devices(self):
        connected = {}
        for obj in self.bluez.get_objects():
            device = obj.get_interface(DEVICE)
            if self._property(device, "Connected"):
                name = self._property(device, "Alias") or "Bluetooth device"
                percent = self._property(obj.get_interface(BATTERY), "Percentage")
                connected[obj.get_object_path()] = (name, percent)
        return connected

    def _bluez_ready(self, _source, result, _data):
        try:
            self.bluez = Gio.DBusObjectManagerClient.new_for_bus_finish(result)
        except GLib.Error as error:
            print(f"opennotch: Bluetooth alerts unavailable: {error.message}")
            return
        self.connected = self._devices()
        for signal in ("object-added", "object-removed", "interface-added", "interface-removed",
                       "interface-proxy-properties-changed"):
            self.bluez.connect(signal, self._schedule_bluetooth)

    def _schedule_bluetooth(self, *_args):
        if not self.bluetooth_update:
            # Battery1 may appear just after Connected changes.
            self.bluetooth_update = GLib.timeout_add(350, self._check_bluetooth)

    def _check_bluetooth(self):
        self.bluetooth_update = 0
        current = self._devices()
        old, self.connected = self.connected, current
        for path, (name, percent) in current.items():
            if path not in old:
                battery = f" · {percent}%" if percent is not None else ""
                self.show(f"{name} connected{battery}", "bluetooth-active-symbolic", True)
        for path, (name, _) in old.items():
            if path not in current:
                self.show(f"{name} disconnected", "bluetooth-disabled-symbolic", False)
        return GLib.SOURCE_REMOVE


    def _watch_downloads(self):
        downloads = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD)
        if not downloads or downloads == GLib.get_home_dir():
            return
        try:
            self.downloads = Gio.File.new_for_path(downloads).monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES)
        except GLib.Error:
            return
        self.pending_downloads = set()
        self.downloads.connect("changed", self._download_event)

    def _download_event(self, _monitor, file, other, event):
        kind = Gio.FileMonitorEvent
        name = file.get_basename()
        if event == kind.CREATED:
            self.pending_downloads.add(name)
            return
        if event in (kind.RENAMED, kind.DELETED, kind.MOVED_OUT):
            self.pending_downloads.discard(name)
        if event == kind.RENAMED and other:
            file, name = other, other.get_basename()
        elif event == kind.CHANGES_DONE_HINT:
            if name not in self.pending_downloads:
                return
            self.pending_downloads.remove(name)
        elif event != kind.MOVED_IN:
            return
        if name.startswith(".") or name.lower().endswith((".part", ".crdownload", ".download", ".tmp")):
            return
        if file.query_file_type(Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS) == Gio.FileType.REGULAR:
            self.show(f"Downloaded · {name}", "folder-download-symbolic", True)
