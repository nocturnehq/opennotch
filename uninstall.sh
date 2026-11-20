#!/bin/sh
# Removes OpenNotch. Your settings and clipboard history are kept unless you pass --purge.
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}"
pkill -TERM -f "python3 -m opennotch$" 2>/dev/null
rm -f "$HOME/.local/bin/opennotch" "$DATA/applications/opennotch.desktop" "$DATA/applications/opennotch-settings.desktop" "$CONF/autostart/opennotch.desktop" \
      "$DATA/icons/hicolor/scalable/apps/opennotch.svg"
rm -rf "$DATA/opennotch/app"
if [ "$1" = "--purge" ]; then
    rm -rf "$DATA/opennotch" "$CONF/opennotch"
    echo "OpenNotch removed, including settings and clipboard history."
else
    echo "OpenNotch removed. Settings ($CONF/opennotch) and history ($DATA/opennotch) kept; use --purge to delete them."
fi
