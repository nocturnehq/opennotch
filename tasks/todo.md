# OpenNotch Soon checklist

- [x] **Screenshots and Capture Shelf.** An explicit screenshot action saves a PNG and shelves it when enabled. Test on isolated X11 and verify the saved URI appears in the Shelf.
- [x] **Screen recording and Record microphone.** The shortcut starts and stops recording, optional microphone follows the switch, and exit or config reload leaves a playable file. Validate with FFmpeg/ffprobe on isolated X11 and test the audio selection.
- [x] **Privacy dot.** Show and clear the indicator for OpenNotch recordings and detectable camera or screen-share sessions. Test controlled start/stop and disclose capture methods the desktop cannot report.
- [x] **Web tab.** Open and navigate an embedded music-site browser with bounded card dimensions and no startup browser process. Test with a local page, remote error handling and a reopened card.
- [x] **Every screen.** Each connected display has a pill with correct placement and opens the shared card. Test two monitors, side placement, and disconnect/reconnect.
- [x] **Send to phone.** Share an explicitly selected file or clip with an expiring local URL and QR code. Verify expiry, download success and rejection of unrelated paths.
- [x] **Live wallpaper and video file.** Choose a local video, start and stop it behind windows on each desktop, and verify the previous wallpaper and desktop icons recover.
- [x] **Taskbar window previews.** Preview and activate open windows from the taskbar. Verify title, icon, and correct window activation on Plasma and Cinnamon. (Plank D-Bus GetHoverPosition anchors + Wnck windows; card verified live on Plasma. The hover timing was not driven with a real pointer.)
- [x] **Taskbar number shortcuts.** Open or switch to each pinned position without breaking existing desktop shortcuts. Test pinned order, duplicate windows, and conflicts. (On this Plasma, Meta+1…9 still belong to plasmashell's Activate Task Manager Entry; the notch says so until they are freed.)
- [x] **Alt+Tab animation and style.** Choose ring, fan, or Flip 3D and preserve transient-window filtering, keyboard cycling and Escape cancellation. Verify each style and the disabled path on both desktops. (Drawn on nested KWin: Ring, Fan, Flip 3D; Tab, Shift+Tab, Escape and the quick-tap switch verified with synthetic keys. KWin owns Alt+Tab on the real session, so the notch says so until Walk Through Windows is freed. Not tried on Cinnamon/Muffin.)
- [x] **Meeting countdown.** Show the time to the next event from an explicitly configured calendar source. Verify timed and all-day events, time zones and an empty calendar.
- [x] **OBS.** Display recording or streaming state and wire the reference shortcut using OBS's supported interface. Test disconnected, recording and streaming states.
- [x] **Twitch chat.** Show messages for the chosen channel. Test retry, switching channels and a blank setting.
- [x] **YouTube chat.** Show messages for the chosen livestream. Test inactive streams, switching and a blank setting. (Unofficial web chat endpoint, the user's choice over an API key; may break if YouTube changes it. Verified live: 4 messages in 45 s from @LofiGirl.)
- [x] **Fullscreen game strip.** Show frame rate, CPU, GPU and RAM while a supported fullscreen app is active. Verify HUD hide/restore and missing metrics. (FPS not shown: X11 gives no frame rate for other apps without MangoHud.)
- [x] **AI agent completion.** Make the existing message integration honor its completion switch independently of general notices. Test both settings and existing callers.
- [x] **Pet.** Cat, dog and bunny appear on the resting island and yield to live activity. Verify all choices and narrow placements.
- [x] **Language.** Use the desktop language automatically and apply explicit choices to Settings and island notices. Verify switching and untranslated fallback. (Settings offers Same as system and English only: the user wants no Greek UI. A Greek table exists in lang_el.py and is used only if the system language is Greek.)

After each group of related changes run `python3 -m opennotch.selftest`, smoke the affected UI on X11, and verify that the installed app still answers its socket.

## First verification pass

- Screenshot and recording save, capture-on-exit, audio from a virtual source, and process cleanup passed. The privacy indicator covers OpenNotch and PipeWire-reported activity.
- Web, pets and startup passed in isolated Plasma and Cinnamon modes. Display positioning and reconnection used two simulated monitors. File sharing used a loopback phone substitute and verified expiry.
- Video wallpaper played and restored its old background in isolated native Plasma 5.27 and Cinnamon 6.6 sessions. OBS was tested against a local mock. Calendar countdown used local exports.
- Twitch and YouTube research identified a supported OAuth path for Twitch and a YouTube Data API credential requirement. Account integration and real streams remain pending.
