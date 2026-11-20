#!/bin/sh
# Installs OpenNotch for the current user only (no sudo): code, command, menu launcher and autostart entry.
set -e
SRC="$(dirname "$(readlink -f "$0")")"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}"
DEST="$DATA/opennotch/app"
BIN="$HOME/.local/bin"

python3 -c 'import gi; gi.require_version("Gtk", "3.0"); from gi.repository import Gtk' \
    || { echo "PyGObject with GTK 3 is required (package python3-gi, gir1.2-gtk-3.0)"; exit 1; }

if [ ! -x "$SRC/bin/opennotch" ] || [ ! -f "$SRC/opennotch.svg" ]; then
    echo "OpenNotch source is missing its launcher or application icon." >&2
    exit 1
fi

mkdir -p "$DEST" "$BIN" "$DATA/applications" "$CONF/autostart" "$DATA/icons/hicolor/scalable/apps"
rm -rf "$DEST/opennotch"
cp -r "$SRC/opennotch" "$DEST/"
rm -rf "$DEST/opennotch/__pycache__"
install -m 755 "$SRC/bin/opennotch" "$BIN/opennotch"
install -m 644 "$SRC/opennotch.svg" "$DATA/icons/hicolor/scalable/apps/opennotch.svg"

desktop() {
cat <<DESK
[Desktop Entry]
Type=Application
Name=OpenNotch
Comment=Dynamic-Island-style notch: music, system, clipboard, shelf, timer
Exec=$BIN/opennotch
Icon=opennotch
Terminal=false
Categories=Utility;
StartupNotify=false
$1
DESK
}
desktop "" > "$DATA/applications/opennotch.desktop"
desktop "" | sed -e 's/^Name=OpenNotch$/Name=OpenNotch Settings/' -e "s|^Exec=.*|Exec=$BIN/opennotch settings|" \
    -e 's/^Comment=.*/Comment=Look, island, taskbar, panels, widgets and keys/' > "$DATA/applications/opennotch-settings.desktop"
desktop "X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=3" > "$CONF/autostart/opennotch.desktop"

echo "Installed. Start it from the menu (OpenNotch) or run: $BIN/opennotch"
echo "It will also start automatically when you log in."
case ":$PATH:" in *":$BIN:"*) ;; *) echo "Note: add $BIN to your PATH to use 'opennotch say ...' from a terminal.";; esac
