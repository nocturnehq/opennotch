#!/bin/sh
# OpenNotch desktop look for Cinnamon.
#   tools/desktop-look.sh apply [ember|mist]   back up current settings once, then apply the look
#   tools/desktop-look.sh restore              put back the settings saved by the first apply
set -e
BK="${XDG_DATA_HOME:-$HOME/.local/share}/opennotch/desktop-backup"
WALL="$HOME/Pictures/OpenNotch"

case "$1" in
apply)
    if [ ! -d "$BK" ]; then  # only the first apply backs up, so restore always returns to the original setup
        mkdir -p "$BK"
        gsettings get org.cinnamon panels-enabled > "$BK/panels-enabled"
        gsettings get org.cinnamon panels-autohide > "$BK/panels-autohide"
        gsettings get org.cinnamon.desktop.background picture-uri > "$BK/picture-uri"
        gsettings get org.cinnamon.desktop.interface cursor-theme > "$BK/cursor-theme"
        gsettings get org.cinnamon show-media-keys-osd > "$BK/show-media-keys-osd"
        gsettings get org.cinnamon.theme name > "$BK/cinnamon-theme"
        gsettings get org.cinnamon enabled-applets > "$BK/enabled-applets"
        dconf dump /net/launchpad/plank/ > "$BK/plank.dconf"
    fi
    name="${2:-ember}"
    [ -f "$WALL/$name.png" ] || python3 -I "$(dirname "$0")/wallpapers.py" "$WALL"
    gsettings set org.cinnamon.desktop.background picture-uri "file://$WALL/$name.png"
    gsettings set org.cinnamon.desktop.background picture-options zoom
    # top bar: an empty, transparent, auto-hidden panel = no visible bar. Not removed: Cinnamon nags at every
    # login when no panel exists (panel.js). The notch shows time, battery, weather and controls instead.
    gsettings set org.cinnamon enabled-applets "[]"
    gsettings set org.cinnamon panels-autohide "['1:true']"
    [ -d "$HOME/.themes/OpenNotch-Glass" ] && gsettings set org.cinnamon.theme name OpenNotch-Glass
    [ -d "$HOME/.local/share/plank/themes/OpenNotch-Glass" ] || cp -r "$(dirname "$0")/OpenNotch-Glass" "$HOME/.local/share/plank/themes/"
    dconf write /net/launchpad/plank/docks/dock1/theme "'OpenNotch-Glass'"
    gsettings set org.cinnamon show-media-keys-osd false             # the notch shows volume/brightness instead
    gsettings set org.cinnamon.desktop.interface cursor-theme Bibata-Modern-Classic
    dconf write /net/launchpad/plank/docks/dock1/icon-size 44
    dconf write /net/launchpad/plank/docks/dock1/zoom-percent 135
    echo "Applied. Undo with: $0 restore"
    ;;
restore)
    [ -d "$BK" ] || { echo "No backup found at $BK"; exit 1; }
    gsettings set org.cinnamon panels-enabled "$(cat "$BK/panels-enabled")"
    [ -f "$BK/panels-autohide" ] && gsettings set org.cinnamon panels-autohide "$(cat "$BK/panels-autohide")"
    gsettings set org.cinnamon.desktop.background picture-uri "$(cat "$BK/picture-uri")"
    gsettings set org.cinnamon.desktop.interface cursor-theme "$(cat "$BK/cursor-theme")"
    gsettings set org.cinnamon show-media-keys-osd "$(cat "$BK/show-media-keys-osd")"
    [ -f "$BK/cinnamon-theme" ] && gsettings set org.cinnamon.theme name "$(cat "$BK/cinnamon-theme")"
    [ -f "$BK/enabled-applets" ] && gsettings set org.cinnamon enabled-applets "$(cat "$BK/enabled-applets")"
    dconf load /net/launchpad/plank/ < "$BK/plank.dconf"
    echo "Restored your previous desktop settings."
    ;;
*)
    echo "usage: $0 apply [ember|mist] | restore"; exit 2 ;;
esac
