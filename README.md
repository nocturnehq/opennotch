# OpenNotch

A free, open-source, Dynamic-Island-style notch & Now Playing bar for **Linux (X11)** and **Windows 10/11**. Everything stays local on your machine — no telemetry, no accounts, no cloud sync.

## Features

- **Dynamic Island & Attached Notch** — floating glass island or top-edge notch with smooth spring morphing.
- **Now Playing Music Bar** — 60 fps fluid progress bar (**Glass**, **Comet**, and **Wave** styles), custom SF-Symbols-style vector transport icons, ambient album-art glow, synced lyrics (LRCLIB), optional inline volume slider, and 60 fps idle pill visualizers (**Bars**, **Pixels**, **Dots**).
- **Overview Widgets** — Today calendar, Focus timer ring, Weather, live CPU/GPU/RAM/Network stats, Battery, Storage, Calculator, Countdown, To-do, Reminders, and World Clock.
- **Controls** — System volume (PipeWire / PulseAudio on Linux, CoreAudio on Windows), screen brightness (KDE PowerDevil, Cinnamon SettingsDaemon, `brightnessctl`, and Windows WMI), and quick toggles.
- **Built-in Web Tab** (Linux) — Persistent browser inside the island for YouTube Music, Spotify, SoundCloud, YouTube, ChatGPT, and Claude.
- **Clipboard History & File Shelf** — Quick text clipboard history (ignoring password manager hints) and drag-and-drop file shelf.
- **Notifications, Screenshots (`PrtSc`), Screen Recording, Camera Mirror & Floating Chat Drawer.**
- **Liquid-Glass Dock & Companion Pet** (Linux + Plank) — Waving glass dock backdrop and interactive companion pet.
- **Bilingual UI** — English and Greek (`en` / `el`).

---

## Install on Linux

### Arch Linux (Manjaro, EndeavourOS, CachyOS)
```bash
cd packaging/arch
makepkg -si
```
Or install dependencies automatically and use the user installer:
```bash
./packaging/install-deps.sh
./install.sh
```

### Ubuntu, Linux Mint, Debian & Fedora
```bash
./packaging/install-deps.sh   # installs GTK 3, PyGObject, Xlib, Wnck, WebKit2, PulseAudio utils
./install.sh                  # installs launcher, desktop entries & login autostart
```

To uninstall:
```bash
./uninstall.sh          # add --purge to also remove settings and clipboard history
```

Run directly from a checkout without installing:
```bash
./bin/opennotch
```

---

## Install / Build on Windows 10 & 11

The Windows edition lives in [`windows/`](windows/) (Python + PySide6 / Qt6 with Win32 topmost toolwindow, Windows 11 DWM Acrylic glass, native SMTC media controls, CoreAudio volume, and WMI brightness):

```powershell
cd windows
pip install -r requirements.txt
python -m opennotch_win        # run directly
python build_exe.py            # builds standalone dist\OpenNotch.exe
```

To build a full Windows installer (`OpenNotch-Setup.exe`), open [`windows/opennotch.iss`](windows/opennotch.iss) in Inno Setup after running `build_exe.py`.

Prebuilt **Windows `.exe`** and **Arch `.pkg.tar.zst`** artifacts are also built automatically by GitHub Actions in [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

---

## CLI & Scripting (Linux)

Send quick status toasts from any build script or terminal:
```bash
opennotch say "Build finished" --icon ok --seconds 6
make && opennotch say "Build OK" --icon ok || opennotch say "Build failed" --icon fail
```

Protocol: connect to `$XDG_RUNTIME_DIR/opennotch.sock`, send one JSON line such as `{"cmd": "say", "text": "Done", "icon": "ok|fail|info", "seconds": 5}`, and read `{"ok": true}`.

---

## Development & Tests

```bash
# Linux test suite
python3 -m opennotch.selftest

# Windows package test suite (runs on Linux and Windows)
python3 windows/selftest_win.py
```

## License

[MIT](LICENSE)
