# OpenNotch

A free, open-source, Dynamic-Island-style notch for Linux (X11, tested on Cinnamon). Python 3 + GTK 3, no extra packages. Everything stays on your machine: no telemetry, no accounts, notifications are mirrored read-only and kept in memory only.

## Install (Linux)

### Arch Linux (and Manjaro / EndeavourOS / CachyOS)
```bash
cd packaging/arch && makepkg -si
```
Or install dependencies via `packaging/install-deps.sh` and run `./install.sh`.

### Ubuntu / Linux Mint / Debian / Fedora
```bash
./packaging/install-deps.sh   # installs GTK 3, PyGObject, Xlib, Wnck, WebKit2, PulseAudio utils
./install.sh                  # menu launcher + starts at login
./uninstall.sh                # add --purge to also delete settings and clipboard history
```

Run without installing: `bin/opennotch`.

## Install / Build (Windows 10 & 11)

The Windows build lives in `windows/` (Python + PySide6 / Qt6, native Win32 topmost toolwindow, Win11 DWM Acrylic glass, SMTC media controls, CoreAudio volume, WMI brightness):

```powershell
cd windows
pip install -r requirements.txt
python -m opennotch_win        # run directly
python build_exe.py            # builds standalone dist\OpenNotch.exe
```

Optional installer: open `windows/opennotch.iss` in Inno Setup to produce `dist\OpenNotch-Setup.exe` (or run the GitHub Actions workflow `.github/workflows/build-windows.yml`).

## Use

- Rest the pointer on the black pill at the top of the screen to open the card; move away to close it.
- Tabs: **Home** (music, CPU/RAM/GPU/battery, volume, brightness, mic), **Clipboard** (last 50 text clips, search, click to copy, pin to keep), **Shelf** (drop files on the notch, drag them back out), **Alerts** (latest notifications), **Focus** (25/5 timer).
- **Ctrl+Alt+M** mutes/unmutes the microphone. A red dot and timer appear on the pill while any app records from a mic.

## Tell me when it's done

    opennotch say "Build finished" --icon ok --seconds 6
    make && opennotch say "Build OK" --icon ok || opennotch say "Build failed" --icon fail

Protocol (for other tools): connect to `$XDG_RUNTIME_DIR/opennotch.sock`, send one JSON line such as
`{"cmd": "say", "text": "Done", "icon": "ok|fail|info", "seconds": 5}`, read one reply line `{"ok": true}`.

## Settings

`~/.config/opennotch/config.json` (created on first run; restart OpenNotch after editing):

| key | default | meaning |
|---|---|---|
| pill_width / pill_height | 230 / 34 | collapsed pill size (px) |
| corner_radius | 22 | rounding of the card's bottom corners |
| card_width / card_height | 580 / 350 | opened card size |
| accent | "#8b7bff" | highlight colour |
| hover_delay_ms | 150 | how long to rest the pointer before it opens |
| tabs | all five | any of "home", "clipboard", "shelf", "notifications", "timer" |
| focus_minutes / break_minutes | 25 / 5 | focus timer lengths |

## Notes

- Brightness needs write access to `/sys/class/backlight/*/brightness`; without it the slider is shown read-only.
- Clips copied by password managers that set `x-kde-passwordManagerHint` are never stored.
- Self-test: `python3 -m opennotch.selftest`
