#!/bin/sh
# Installs OpenNotch system dependencies on Arch Linux, Ubuntu/Mint/Debian, or Fedora.
set -e

if command -v pacman >/dev/null 2>&1; then
    echo "Detected Arch Linux (pacman)..."
    sudo pacman -S --needed \
        python python-gobject python-cairo python-xlib \
        gtk3 libwnck3 libkeybinder3 webkit2gtk libpulse \
        brightnessctl ffmpeg
elif command -v apt-get >/dev/null 2>&1; then
    echo "Detected Debian/Ubuntu/Mint (apt)..."
    sudo apt-get update
    sudo apt-get install -y \
        python3 python3-gi python3-gi-cairo python3-xlib \
        gir1.2-gtk-3.0 gir1.2-wnck-3.0 gir1.2-keybinder-3.0 gir1.2-webkit2-4.1 \
        pulseaudio-utils ffmpeg
elif command -v dnf >/dev/null 2>&1; then
    echo "Detected Fedora (dnf)..."
    sudo dnf install -y \
        python3 python3-gobject python3-cairo python3-xlib \
        gtk3 libwnck3 keybinder3 webkit2gtk4.1 pulseaudio-utils \
        brightnessctl ffmpeg
else
    echo "Unsupported package manager. Install Python 3, PyGObject (GTK 3), pycairo, python-xlib, libwnck3, and pulseaudio-utils manually." >&2
    exit 1
fi

echo "Dependencies installed! Now run ./install.sh from the OpenNotch directory."
