# OpenNotch — START HERE (Gemini, from Claude at 97% weekly, 2026-11-20 20:37)

Everything below this section is history, some of it superseded. **This section is the current truth.**

## Run / test / install
- Source: `~/Projects/opennotch` (no git). Installed copy: `~/.local/share/opennotch/app` via `./install.sh`. Restart: `pkill -f "python3 -m opennotch$"; (cd ~ && setsid ~/.local/bin/opennotch >/dev/null 2>&1 &)` — start it from `~`, or `python3 -m` picks the source tree from the cwd.
- Check: `python3 -m opennotch.selftest` (all must pass). Panel screenshots: `~/Documents/Codex/2026-11-20/a-3/work/shoot.sh OUTDIR PREFIX tab1,tab2 KDE 'CONFIG_JSON'`. Fake media player: `work/fake_player.py`.
- User is on **KDE Plasma 5.27 X11**; everything must also work on Cinnamon. Never test on the user's real desktop config; back up anything you change in `work/`.

## Current look (decided with the user in a 13-question interview)
- Black + liquid glass: open card = Glass surface, resting pill = solid black. Active things are solid white with black icons. No per-widget colours. Tokens in `opennotch/design.py` (`island_css`, `type_css`, `settings_css`); `CHAMPAGNE` is white now.
- Font **SF Pro** (installed): 3 sizes only — 32 px bold numbers (SF Pro Display), 14 px semibold titles, 11 px rest. No thin weights, no tracked capitals.
- Compact, Mac-like: card margins 12, gaps 8, card grows to fit its tab bar and re-checks after animating (`_check_card_fit`).
- Calm spring (`design.spring`, ~3% overshoot).
- Pet peeks beside the tab bar in the open card.
- **Taskbar = plain centred Plank, original `OpenNotch-Black` theme** (user rejected the full-width and NotchPixel-style attempts as "horrible"). The OpenNotch "Tray and clock" strip is OFF (`taskbar_status: false`); leave it off.

## TOP TASK: dock background that waves with the icons, in liquid glass
User: "make the black around it wave with the apps like that effect we have, and integrate liquid glass there too." The "effect" is Plank's zoom (icons magnify up to 150% under the pointer); today Plank's black background stays flat.
Plank can't bend its own background, so:
1. Make Plank's background invisible: in `tools/OpenNotch-Black/dock.theme` (and the live copy in `~/.local/share/plank/themes/OpenNotch-Black/`) set `FillStartColor`, `FillEndColor` and `OuterStrokeColor` alpha to 0. Keep a backup.
2. New module `opennotch/dockbg.py`: a transparent, click-through (empty input shape) DOCK-type window spanning the bottom edge, stacked just under Plank (map it before Plank; check stacking on KWin and Muffin; Plank must stay above it).
3. Each frame while the pointer is over the dock, draw the bar path in cairo: base height = Plank bar height (icon 44 → ~62 px), and the top edge raised by Plank's zoom curve around the pointer x. Plank's zoom per item ≈ `1 + (zoom-1) * cos²(π·d/(2·R))` for distance d < R, where R ≈ 3 icon widths and zoom = `zoom-percent`/100 (read it from Plank's gsettings). Raise the top edge by `(scale-1)·icon_size` with a smooth curve so the black "waves" up under the magnified icons. Ease it back down when the pointer leaves (calm spring, `design.spring`). Bar left/right edges: compute from Plank item positions (`net.launchpad.plank.Items.GetHoverPosition`). The earlier strip calibration found the bar ends about 1.45 icon widths past the last anchor; re-measure, it was not reliable.
4. Liquid glass: on KDE set `_KDE_NET_WM_BLUR_BEHIND_REGION` to the bar path (reuse `opennotch/kwinblur.py`, as the notch's glass card does), fill with a smoked tint (`design.INK` at ~0.7) plus a faint white rim. On Cinnamon there is no live blur: fall back to the snapshot-blur approach the notch uses (`_capture_glass`) or a solid tint.
5. Hide and show with Plank's dodge (pointer at the bottom edge or no maximized window), respect Reduce motion (no wave), keep it off in fullscreen.
6. Verify with real screenshots at 60 Hz: pointer sweeping across the dock, on both desktops.

## Other open items
- Pet jobs and roaming (full spec further down, "Not built yet: the pet's jobs").
- Re-shoot after the black/SF Pro pass: web tab, timer page, side placement, volume pop-up, Settings, previews card, Alt+Tab.
- Super+1…9 and Alt+Tab are still owned by KDE; ask the user before changing KDE shortcuts.

---

# OpenNotch: handoff to Gemini (2026-11-20, evening)

Claude Code worked from where Codex stopped (Codex finished at 18:50 with 11 of 18 "Soon" items done). Claude added the other 7. **All 18 items are done**; what is left is testing and two questions for the user.

Read first: `~/.local/share/opennotch/HANDOFF.md` (architecture, desktop state, user preferences) and `tasks/todo.md` (the checklist, with notes on each ticked item).

## Where things are

| What | Path |
|---|---|
| Source (edit here) | `~/Projects/opennotch` (no git repo) |
| Installed copy (runs at login) | `~/.local/share/opennotch/app/`, launcher `~/.local/bin/opennotch` |
| User config | `~/.config/opennotch/config.json` |
| NotchPixel reference | `~/.local/share/opennotch/reference/` |
| Test helpers and screenshots | `~/Documents/Codex/2026-11-20/a-3/work/` (`run-gui-check.sh`, `nested-x.sh`, `gui-check.py`) |

Workflow: edit the source → `python3 -m opennotch.selftest` → `./install.sh` → `pkill -f "python3 -m opennotch$"; ~/.local/bin/opennotch &` → `opennotch say "ok"` to confirm the socket answers.
Test in isolation: set `XDG_CONFIG_HOME`, `XDG_DATA_HOME` and `XDG_RUNTIME_DIR` to temporary folders, then run `dbus-run-session -- xvfb-run -a …`. For window-manager behaviour, start `kwin_x11 &` inside the xvfb. Never test on the user's real desktop config.

## What Claude added this session

Every new setting is **off by default** except Language (`auto`). All of them pass `python3 -m opennotch.selftest` (each has its own check), and all are installed and running.

1. **Twitch chat**: `opennotch/twitchchat.py`. Anonymous read-only IRC over TLS (`justinfan…`), no token. Setting `chat_twitch` takes a channel name or URL; blank turns it off. Reconnects with backoff. Shows at most one line every 2 s as a notch notice. A live join to #twitch was verified.
2. **Fullscreen game strip**: `_update_coverage()` / `_tick_game()` in `app.py`, setting `game_strip_fullscreen`. In fullscreen it shows CPU, GPU and RAM instead of hiding; the pill grows to fit the widest reading. Verified top and side placement on KDE and Cinnamon modes, plus leaving fullscreen. **No FPS**: X11 gives no frame rate for other apps without MangoHud.
3. **Taskbar number shortcuts**: `opennotch/taskkeys.py`, setting `taskbar_number_keys`. Super+1…9 raise, cycle or launch Plank's pinned app at that position. **On the user's Plasma, Meta+1…9 are still held by plasmashell** ("Activate Task Manager Entry 1…9" in `~/.config/kglobalshortcutsrc`). The notch shows a notice saying where to free them. Claude did not change KDE's shortcuts; that is the user's call.
4. **Language**: `opennotch/i18n.py` + `opennotch/lang_el.py` (Greek table, keyed by English text). Settings offers `auto` (Same as system) and `en`. **The user wants no Greek UI anywhere** (Greek only for typing), so the Greek button was removed; the table is used only if the system language is Greek. Do not add translations.
5. **Window previews**: `opennotch/previews.py`, setting `taskbar_previews`. Uses Plank's D-Bus `GetHoverPosition` for exact icon positions and Wnck for windows. Rest on an icon for 450 ms to get a black card of thumbnails; click one to switch. Verified live on the user's Plasma, and with real Plank + a moved pointer in xvfb (card shows on hover, closes when the pointer leaves).
6. **Alt+Tab styles**: `opennotch/alttab.py`, settings `alt_tab_animation` + `alt_tab_style` (ring / fan / flip). Full-screen dimmed switcher drawn with cairo. Tab / Shift+Tab / arrows / Escape / Enter work, Alt release switches, and a quick tap switches to the previous window. Verified on nested KWin in xvfb with synthetic keys (screenshots in the work folder: `alttab-*.png`). **KWin owns Alt+Tab on the real session** ("Walk Through Windows"), so the notch shows a notice until the user frees it. Also verified on nested Muffin (Cinnamon's WM): Tab then Alt release switched windows.
7. **YouTube chat**: `opennotch/youtubechat.py`, setting `chat_youtube` (a channel `@name`, channel link or live video link; blank = off). Reads chat the way YouTube's own popout chat page does, with no API key; waits and retries every 60 s while the channel is offline. Newest line only per check (every 5–10 s). Verified live on @LofiGirl.

## Left to do

1. YouTube chat runs on YouTube's unofficial web chat endpoint (the user chose that over an API key). If it stops working, check `opennotch/youtubechat.py` first: YouTube changes that page now and then.
2. Ask the user whether to free Meta+1…9 and Alt+Tab in KDE so the new keys can take them.

## House rules (from the user)
- Match NotchPixel one-to-one in look and settings; no empty space, overflow, low-contrast text, or red/tinted top-bar elements.
- Every feature works on both KDE Plasma (X11) and Cinnamon, with no trade-offs.
- Don't change the user's real desktop settings without asking.

## Redesign: OpenNotch's own look (2026-11-20, late evening)

The user asked for a modern, minimal, luxurious look **of OpenNotch's own**: matching NotchPixel's look is no longer the goal (its settings and features stay). Keep this direction for anything new.

**Single source of truth: `opennotch/design.py`.** Colour, type, radius and motion tokens, plus `island_css()` and `settings_css()`. Those stylesheets are layered after the old ones in `app.py` / `settings.py`, so their rules win. Change the look there, not in scattered CSS.
- Palette: near-black ink `INK` (#050506), warm off-white text `#f2efe9` (62% / 38% for secondary / labels), hairlines at 9% / 16%, one champagne accent `#d8c3a0` used sparingly (active marks, progress, focus rings, the island's lower rim, the dock's edge). The default accent in `config.py` is now champagne.
- Shape: hairline-bordered tiles (radius 16) instead of filled grey boxes; pill-shaped tabs and segmented controls; switched-on control tiles are a champagne edge with a faint champagne tint, not a white slab.
- Type: light weight (200) for big numbers and times, letter-spaced small capitals for labels (`.label`, `.eyebrow`).
- Motion: the island grows with a nearly critically damped spring (`design.spring`, 0.52 s) and settles or closes with ease-out-quint (0.36 s); content fades in between 35% and 75% of the move (`design.content_fade`). CSS transitions use `cubic-bezier(0.22,1,0.36,1)`. The dock theme no longer bounces and has slower, softer slide and hide timings.
- Surface: `_draw()` in `app.py` paints a faint vertical gradient on the ink, with a champagne hairline that fades out toward the top so the notch still merges with the bezel.

Restyled and checked in screenshots (`~/Documents/Codex/2026-11-20/a-3/work/luxe/`): pill, notices, music, overview, controls, clipboard, Settings, window previews card, Alt+Tab (selected card gets a champagne edge), dock theme (`tools/OpenNotch-Black/dock.theme`, copied live to `~/.local/share/plank/themes/OpenNotch-Black/`; the old one is saved as `work/dock.theme.before`).

**New widgets** (Settings › Widgets, off by default): Battery, Storage (free space on home), Up next (next meeting from the calendar file; loading it no longer turns on the pill countdown unless Meeting countdown is on). The overview is a 2-column grid; the card grows to fit.

**Second pass (done):**
- Notifications, Shelf and Ask Claude panels reworked: `panel_head()` (tracked title left, actions right), `empty_state()` (icon, line, hint), `fitted_scroller()` (panel is exactly as tall as its content, scrolls past a max). "Clear" buttons only show when there is something to clear. Ask Claude shows an empty state until the first question, a pill input and a round send button.
- Glass mode on the tokens: smoked warm tint, champagne sheen and rim.
- Level bars are champagne at every value (GTK colours `.low/.high/.full` fills differently by default).
- New widgets: World clock (`world_clock_zone`, validated with `zoneinfo`), Now playing (title, artist, previous/play/next), Notes (saved to `~/.local/share/opennotch/notes.txt`, atomic write, 600 ms after typing stops). Settings › Widgets has an **Order** list (up/down) stored as `widget_order`; unknown names are dropped and missing ones appended. Selftest covers it.
- Motion: spring stiffness 10 (90% of the move by ~170 ms, 0.4% overshoot, lands exactly at 1).
- Screenshot harness: `~/Documents/Codex/2026-11-20/a-3/work/shoot.sh OUTDIR PREFIX tab1,tab2,…,toast,osd DESKTOP 'CONFIG_JSON'` (isolated XDG dirs, xvfb, pointer via XTest). Shots in `work/after/`.

**Still to do on the redesign:**
1. Web tab, timer page and side placement were not screenshotted after the changes.
2. Volume/brightness pop-up was not captured (a toast was up; pop-ups never cover a message). Shoot it alone.
3. Notes widget has no placeholder text (GTK 3 TextView has none); consider a dim overlay label when empty.
4. Watch the spring on a real 144 Hz screen.

**Music card (latest):** progress bar always visible (full track drawn in champagne at 28%, playhead dot even at 0:00 or with nothing playing); unknown length (streams) shows a quiet track instead of a fake full bar; players that refuse `Position` (some browsers) get an estimated position that advances only while playing (`dbuswatch.position` now calls back with `None` on error). New track resets to 0. Card: 128 px art, big round play button (`.bigplay`), small `.transport` prev/next, `.chip` Lyrics, `.time` labels. Test player for this: `work/fake_player.py`.

## Direction changed again: PLAYFUL & BOUNCY (user's pick, 2026-11-20 ~19:50)
The user found the minimal/luxury look "bland, like a work app" and chose **playful & bouncy**. This supersedes the champagne/luxury notes above (the tokens still live in `design.py`; `CHAMPAGNE` is now the pink accent `#ff8fc7`).
- `design.playful_css()` / `playful_settings_css()` are layered last. Every widget tile has its own bright colour (`WIDGET_COLORS`, class `w-<name>`), every tab icon its colour with a filled blob when active (`TAB_COLORS`, class `t-<name>`), every quick-control tile a soft tint that fills solid when on (`TILE_COLORS`, class `q-<key>`). Text on colour is dark plum `ON_COLOR`.
- Surface: deep plum ink, pink glow and rim. Tiles radius 26, card radius +14.
- Motion: underdamped spring (`damping 0.5, stiffness 12`, ~16% overshoot, lands exactly); CSS transitions use an ease-out-back curve.
- Font: **Nunito** (rounded, OFL) installed in `~/.local/share/fonts/Nunito`, now the default and the user's setting; heavy (800) weights for numbers and titles. Note: isolated test runs that set `XDG_DATA_HOME` can't see user fonts and fall back to Noto.
- The pet peeks into the open card left of the tab bar when "When resting, show" = Pet.
- Previous config saved as `work/config-before-playful.json`.
Done: Settings, previews card, Alt+Tab (thick pink ring on the selection, bold title) and the dock (plum with a pink edge) are on the playful palette; tooltips are lilac; work/shoot.sh links user fonts into isolated runs. Not re-shot: previews card, Alt+Tab, dock.

## FINAL DIRECTION (user interview, 2026-11-20 ~20:20) — this supersedes the playful and champagne notes above
Decisions from a 13-question interview with the user:
- **Colours:** black + liquid glass. No per-widget colours. Active things (current tab, lit controls, play button, progress) are **solid white with black icons**. `design.CHAMPAGNE` is now `#ffffff` (name kept for compatibility); `design.playful_css()` is no longer loaded.
- **Surface:** the open card uses the Glass surface by default (`config.DEFAULTS["surface"] = "glass"`); the resting pill/notch stays solid black (already how `_draw` works).
- **Font:** SF Pro (installed): SF Pro Display for numbers and titles, SF Pro Text for the rest. `design.type_css()` enforces **3 sizes only**: 32 px bold numbers, 14 px semibold titles, 11 px everything else. No thin weights, no letter-spaced capitals (labels are sentence case now).
- **Size:** Mac-like, "as big as needed but not too big": card margins 12, gaps 8, smaller tab bar, card radius = pill radius + 4. The card grows to fit its tab bar and re-checks its fit after animating (`_check_card_fit`).
- **Motion:** calm iOS-like spring, `design.spring(damping=0.74, stiffness=12)`, ~3% overshoot.
- **Taskbar (done):** one continuous NotchPixel-style bar. Plank `alignment` is `fill` (was `center`; old values in `work/plank-before.txt`), and `tray.py`'s StatusStrip sits transparent inside its right end: divider, tray icons, bold time over the date, and a bell that opens the Notifications tab. It shows/hides with the dodging dock (pointer at the bottom edge anywhere). The "KDE bottom-right menu" the user wanted gone was this strip floating alone in the corner.

### Not built yet: the pet's jobs (user chose ALL of these)
Keep the pet beside the tab bar in the open card (already there) and on the pill, and give it roles:
1. **Status mood:** naps when idle; bobs to music while MPRIS is Playing; sits still during a focus timer; stretches on a break. `pet.py` has poses (`POSES`, `paint_pet(... pose=...)`); add poses or map states to existing ones, driven from `app._update_pill()`.
2. **Notification messenger:** hops up with a small badge when a notification arrives (`_on_notification`).
3. **Health nudges:** yawns when CPU or RAM > ~85% for a while, looks worried at battery ≤ 15% (`system.CpuMeter`, `ram_percent`, `battery`).
4. **Smart click:** unread notice → open it; health warning → show the stat; otherwise start/pause the focus timer (`_pomo_toggle`).
5. **Roaming, "now and then":** every few minutes while the user is idle (no input ~2 min), a small transparent always-on-top DOCK-type window with the pet hops out of the notch, strolls along the top edge of the Plank bar, and jumps onto any notice that pops up; returns home after ~20 s. Never over fullscreen apps (`windowstate.coverage`) and never while the user is typing in a window it would cover. Respect Reduce motion (no roaming).

**Taskbar = NotchPixel layout (done, 20:28):** Plank `alignment=fill`, `items-alignment=start`, first item `docklet://applications` (Start menu; `~/.config/plank/dock1/launchers/applications.dockitem`). StatusStrip right cluster: divider, "<" chevron revealing the KDE/XApp tray icons (hidden by default), network icon, volume icon (both open the Controls tab), bold time over date, bell (Notifications tab). Old Plank values in `work/plank-before.txt`. The Start docklet's icon comes from the icon theme's `start-here` (looks like a gear in WhiteSur); NotchPixel uses a 2×2 grid — swap the icon if wanted.

**Taskbar, take 2 (20:33) — matches the real NotchPixel bar in `work/vm-taskbar.png` (captured from the Windows VM):** NotchPixel's taskbar is NOT full width. It is a compact, centred black island sized to its content: Start + apps, then a clock section that rises a step taller through an S-curve, with a rounded top-right corner. Now: Plank `alignment=center`, `items-alignment=center`, `offset` set by the strip so dock + clock section are centred together (about 30 px right of centre still; the offset unit is calibrated by eye: `round(145 * shift / (W/2))`). `tray.py` StatusStrip draws its own shape (`_clear`): Plank's fill and rim, `step` 10 px taller, `curve_w` 30 px S-curve, `corner` 18, and it overlaps Plank's right end by `overlap` 22. It finds Plank's right edge from `GetHoverPosition` of the last item + 1.45 icon widths. That factor is an estimate measured live; if icons or theme change, re-measure (shortcut noted in code). Remaining differences from NotchPixel: Start icon is a gear (theme `start-here`), the clock is 24-hour, and there is no "show desktop" sliver at the far right.

**Taskbar REVERTED (20:35, user: "genuinely horrible"):** back to the final pre-KDE taskbar: plain centred Plank, original `OpenNotch-Black` theme (restored from `work/dock.theme.before` into both `tools/` and `~/.local/share/plank/themes/`), original dock items (no Start docklet), `offset 0`, and the OpenNotch "Tray and clock" strip turned OFF (`taskbar_status: false`). The strip code in `tray.py` (NotchPixel-style shape, chevron, network/volume, bell) is still there but unused; don't turn it back on unless the user asks.
