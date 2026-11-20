"""python3 -m opennotch.selftest  -- checks the config loader, clipboard store and socket protocol (no GUI needed)."""
import json
import os
import socket
import sys
import tempfile
import threading

from . import config, protocol, system
from .clipstore import ClipStore


def test_config(tmp):
    path = os.path.join(tmp, "cfg", "config.json")
    cfg = config.load(path)
    assert cfg == config.DEFAULTS and os.path.exists(path), "missing file -> defaults written"
    with open(path, "w") as f:
        json.dump({"pill_width": 9999, "accent": "red", "tabs": ["timer", "bogus", "home"],
                   "hover_delay_ms": True, "corner_radius": 10}, f)
    cfg = config.load(path)
    assert cfg["pill_width"] == 600, "clamped"
    assert cfg["accent"] == config.DEFAULTS["accent"], "bad colour ignored"
    assert cfg["tabs"] == ["music", "overview", "controls"], "old names mapped, unknown dropped, order kept"
    assert cfg["hover_delay_ms"] == config.DEFAULTS["hover_delay_ms"], "bool is not a number"
    assert cfg["corner_radius"] == 10
    with open(path, "w") as f:
        f.write("{broken")
    assert config.load(path) == config.DEFAULTS, "broken JSON -> defaults"
    assert config.validate({"tabs": []})["tabs"] == config.TABS, "empty tab list -> all tabs"
    cfg = config.validate({"clipboard_layout": "list", "position": "left_side", "side_position": 115,
                           "size": 80, "open_size": 150, "show_lock_keys_hud": False})
    assert cfg["clipboard_layout"] == "list" and cfg["position"] == "left_side"
    assert (cfg["size"], cfg["open_size"], cfg["side_position"]) == (80, 140, 100)
    assert not cfg["show_lock_keys_hud"]
    assert cfg["key_timer"] == "<Ctrl><Alt>Y"
    cfg = config.validate({"resting": "pet", "pet": "dog", "obs_port": 80_000,
                           "calendar_file": "test.ics", "live_wallpaper_file": "x\0y"})
    assert (cfg["resting"], cfg["pet"], cfg["obs_port"]) == ("pet", "dog", 65535)
    assert cfg["calendar_file"] == "test.ics" and not cfg["live_wallpaper_file"]


def test_lyrics(_tmp):
    from .extras import line_at, parse_lrc
    lines = parse_lrc("[00:01.00]one\n[00:03.50][00:09.00]two\nno stamp\n[01:00]three")
    assert lines == [(1.0, "one"), (3.5, "two"), (9.0, "two"), (60.0, "three")], lines
    assert line_at(lines, 0.5) == -1 and line_at(lines, 3.6) == 1 and line_at(lines, 99) == 3


def test_clipstore(tmp):
    path = os.path.join(tmp, "data", "clipboard.json")
    s = ClipStore(path, limit=3)
    assert not s.add("   "), "blank clips skipped"
    for t in ("a", "b", "c"):
        assert s.add(t)
    assert not s.add("c"), "same as newest is a no-op"
    s.toggle_pin("a")
    s.add("d")
    s.add("e")
    texts = [it["text"] for it in s.items]
    assert texts == ["e", "d", "c", "a"], texts  # 3 unpinned kept + pinned "a" survives
    s.add("c")
    assert [it["text"] for it in s.items][0] == "c", "re-copy moves to top"
    assert [it["text"] for it in s.search("")][0] == "a", "pinned first"
    assert [it["text"] for it in s.search("D")] == ["d"], "case-insensitive search"
    s.save()
    assert oct(os.stat(path).st_mode & 0o777) == "0o600", "history is private"
    s2 = ClipStore(path, limit=3)
    assert s2.items == s.items, "round-trips through disk"
    s2.clear_unpinned()
    s3 = ClipStore(path, limit=3)
    assert [it["text"] for it in s3.items] == ["a"], "clear keeps pinned clips on disk"
    s3.remove("a")
    assert not s3.items


def test_protocol(tmp):
    ok = protocol.parse_request(b'{"cmd":"say","text":"  Build\\n finished ","icon":"ok","seconds":3}')
    assert ok == {"cmd": "say", "text": "Build finished", "icon": "ok", "seconds": 3.0}, ok
    assert protocol.parse_request(b'{"cmd":"say","text":"hi"}')["icon"] == "info"
    assert protocol.parse_request(b'{"cmd":"done","text":"Ready"}')["cmd"] == "done"
    assert protocol.parse_request(b'{"cmd":"screenshot","path":"/arbitrary"}') == {"cmd": "screenshot"}
    assert protocol.parse_request(b'{"cmd":"record"}') == {"cmd": "record"}
    for bad in (b"nope", b"[]", b'{"cmd":"rm"}', b'{"cmd":"say","text":""}',
                b'{"cmd":"say","text":"x","icon":"skull"}', b'{"cmd":"say","text":"x","seconds":0}'):
        try:
            protocol.parse_request(bad)
            raise AssertionError(f"accepted {bad!r}")
        except ValueError:
            pass
    assert len(protocol.parse_request(json.dumps({"cmd": "say", "text": "x" * 999}).encode())["text"]) == 300

    path = os.path.join(tmp, "run", "opennotch.sock")
    srv = protocol.listen(path)
    assert os.stat(path).st_mode & 0o077 == 0, "socket is owner-only"
    got = []

    def serve(n):
        for _ in range(n):
            conn, _ = srv.accept()
            protocol.handle_connection(conn, got.append)
    t = threading.Thread(target=serve, args=(4,), daemon=True)
    t.start()
    assert protocol.request(path, {"cmd": "say", "text": "Done", "icon": "fail", "seconds": 2}) == {"ok": True}
    assert got[-1]["text"] == "Done" and got[-1]["icon"] == "fail"
    assert protocol.request(path, {"cmd": "say"})["ok"] is False
    with socket.socket(socket.AF_UNIX) as c:  # raw client: garbage line
        c.connect(path)
        c.sendall(b"garbage\n")
        assert json.loads(c.recv(1024))["ok"] is False
    try:
        protocol.listen(path)  # 4th connection is the ping from the second instance
        raise AssertionError("second instance allowed")
    except RuntimeError:
        pass
    t.join(2)
    srv.close()
    protocol.listen(path).close()  # stale socket (nobody listening) is replaced


def test_source_outputs():
    sample = """Source Output #1
\tSource: 5
\tCorked: no
\tProperties:
\t\tmedia.name = "WebRTC"
\t\tapplication.name = "Firefox"
Source Output #2
\tSource: 7
\tCorked: no
\tProperties:
\t\tapplication.name = "OBS"
Source Output #3
\tSource: 5
\tCorked: no
\tProperties:
\t\tmedia.name = "Peak detect"
\t\tapplication.name = "Volume Control"
"""
    assert system.parse_source_outputs(sample, {"7"}) == ["Firefox"]


def test_twitch():
    from .twitchchat import channel_name, parse_line
    assert channel_name("https://www.twitch.tv/Some_Streamer/") == "some_streamer"
    assert channel_name("#abc") == "abc" and channel_name("") is None and channel_name("a b") is None
    assert parse_line("PING :tmi.twitch.tv") == ("ping", ":tmi.twitch.tv")
    line = "@badge-info=;display-name=Some\\sOne;color= :someone!someone@someone.tmi.twitch.tv PRIVMSG #abc :hello there"
    assert parse_line(line) == ("msg", ("Some One", "hello there")), parse_line(line)
    assert parse_line(":x!x@x.tmi.twitch.tv PRIVMSG #abc :\x01ACTION waves\x01") == ("msg", ("x", "waves"))
    assert parse_line(":tmi.twitch.tv 001 justinfan1 :Welcome") is None
    cfg = config.validate({"chat_twitch": "twitch.tv/Abc_1"})
    assert cfg["chat_twitch"] == "abc_1" and config.validate({"chat_twitch": "no way!"})["chat_twitch"] == ""


def test_taskkeys():
    from .taskkeys import launcher_path, pick_window
    item = "[PlankDockItemPreferences]\nLauncher=file:///home/u/.local/share/applications/My%20App.desktop\n"
    assert launcher_path(item) == "/home/u/.local/share/applications/My App.desktop"
    assert launcher_path("[PlankDockItemPreferences]\nLauncher=docklet://clock\n") is None
    assert launcher_path("garbage") is None
    assert pick_window([], None) is None
    assert pick_window(["a", "b"], None) == "b"  # topmost when the app isn't focused
    assert pick_window(["a", "b"], "a") == "b" and pick_window(["a", "b"], "b") == "a"  # cycle


def test_language():
    from . import i18n
    from .lang_el import EL
    old = os.environ.get("LANGUAGE")
    try:
        i18n.setup("el")
        assert i18n.tr("Language") == "Γλώσσα" and i18n.caps("Γλώσσα") == "ΓΛΩΣΣΑ" and i18n.caps("General") == "GENERAL"
        assert i18n.tr("Not a known string") == "Not a known string"  # untranslated falls back to English
        i18n.setup("en")
        assert i18n.tr("Language") == "Language"
        os.environ["LANGUAGE"] = "el_GR:en"
        i18n.setup("auto")
        assert i18n.tr("Language") == "Γλώσσα"
        os.environ["LANGUAGE"] = "fr_FR"
        i18n.setup("auto")
        assert i18n.tr("Language") == "Language"
    finally:
        if old is None:
            os.environ.pop("LANGUAGE", None)
        else:
            os.environ["LANGUAGE"] = old
        i18n.setup("en")
    assert all(isinstance(v, str) and v for v in EL.values())
    assert config.validate({"language": "el"})["language"] == "el" and config.validate({"language": "xx"})["language"] == "auto"


def test_previews():
    from .previews import nearest_item
    anchors = [("a", 100), ("b", 160), ("c", 220)]
    assert nearest_item(105, anchors) == "a" and nearest_item(190, anchors, reach=29) is None
    assert nearest_item(225, anchors) == "c" and nearest_item(5, []) is None


def test_alttab():
    from .alttab import draw_order, layout
    for style in ("ring", "fan", "flip"):
        x, y, scale, alpha, _ = layout(style, 0, 5, 500, 300)
        assert (x, y) == (500, 300) and scale == 1 and alpha == 1, style  # selection: centred, full size
        assert draw_order(style, [-1, 0, 1, 2])[-1] == 1, style  # selection drawn last, on top
        assert layout(style, 2, 5, 500, 300)[3] < 1, style  # others dimmer


def test_youtube():
    from .youtubechat import messages, next_continuation, target
    assert target("https://www.youtube.com/watch?v=jfKfPfyJRdk") == ("video", "jfKfPfyJRdk")
    assert target("youtu.be/jfKfPfyJRdk") == ("video", "jfKfPfyJRdk")
    assert target("https://www.youtube.com/live/jfKfPfyJRdk?si=x") == ("video", "jfKfPfyJRdk")
    assert target("@LofiGirl") == ("handle", "@LofiGirl") and target("youtube.com/@LofiGirl") == ("handle", "@LofiGirl")
    assert target("https://evil.example/@x") is None and target("") is None and target("hello world") is None
    item = {"addChatItemAction": {"item": {"liveChatTextMessageRenderer": {
        "authorName": {"simpleText": "Ann"},
        "message": {"runs": [{"text": "hi "}, {"emoji": {"shortcuts": [":wave:"]}}]}}}}}
    assert messages([item, {"addChatItemAction": {"item": {"liveChatPaidMessageRenderer": {}}}}]) == [("Ann", "hi :wave:")]
    assert next_continuation({"continuations": [{"timedContinuationData": {"continuation": "c", "timeoutMs": 50}}]}) == ("c", 1000)
    assert next_continuation({}) == (None, 0)
    assert config.validate({"chat_youtube": "@LofiGirl"})["chat_youtube"] == "@LofiGirl"
    assert config.validate({"chat_youtube": "not a channel"})["chat_youtube"] == ""


def test_widget_order():
    order = config.validate({"widget_order": ["notes", "bogus", "date", "notes"]})["widget_order"]
    assert order[:2] == ["notes", "date"] and "bogus" not in order and len(order) == len(set(order))
    assert set(order) == set(config.DEFAULTS["widget_order"])  # widgets left out are kept, at the end
    assert config.validate({"world_clock_zone": "Asia/Tokyo"})["world_clock_zone"] == "Asia/Tokyo"
    assert config.validate({"world_clock_zone": "Mars/Base"})["world_clock_zone"] == config.DEFAULTS["world_clock_zone"]


def test_dockbg():
    from .dockbg import bar_edges, blur_rects, wave_bump
    assert abs(wave_bump(500, 500, 100, 22) - 22.0) < 1e-6
    assert abs(wave_bump(550, 500, 100, 22) - 11.0) < 1e-6
    assert wave_bump(600, 500, 100, 22) == 0.0 and wave_bump(500, 500, 100, 0) == 0.0
    assert bar_edges(500, 1400, 950, 44, 1.5, 0.0) == (500.0, 1400.0)
    l, r = bar_edges(500, 1400, 950, 44, 1.5, 1.0)
    assert abs((500 - l) - 22.0) < 0.5 and abs((r - 1400) - 22.0) < 0.5, (l, r)
    l2, r2 = bar_edges(500, 1400, 500, 44, 1.5, 1.0)
    assert l2 == 500.0 and r2 > 1420.0, (l2, r2)
    rects = blur_rects(500, 1400, 97, 160, 20, 580, 114, 22, scale=1)
    assert rects and len(rects) % 4 == 0
    ys = [rects[i + 1] for i in range(0, len(rects), 4)]
    assert min(ys) < 80 and max(ys[i] + rects[i * 4 + 3] for i in range(len(ys))) == 160
    assert blur_rects(500, 500, 97, 160, 20, 500, 114, 0) == []


def test_pet_jobs():
    import cairo
    from .pet import SPECIES, can_roam, choose_mood, paint_pet, smart_click_action

    assert choose_mood(unread=2, low_battery=True, playing=True) == "notice"
    assert choose_mood(low_battery=True, high_load=True, playing=True) == "worried"
    assert choose_mood(high_load=True, playing=True) == "yawn"
    assert choose_mood(pomo_running=True, pomo_phase="focus", playing=True) == "focus"
    assert choose_mood(pomo_running=True, pomo_phase="break", playing=True) == "stretch"
    assert choose_mood(playing=True, idle_s=120) == "bob"
    assert choose_mood(idle_s=65) == "nap"
    assert choose_mood(idle_s=5) == "idle"

    assert smart_click_action(unread=1, health_issue=("battery", 10)) == "notifications"
    assert smart_click_action(unread=0, health_issue=("cpu", 92)) == "stats"
    assert smart_click_action(unread=0, health_issue=None) == "timer"

    assert can_roam(enabled=True, reduce_motion=False, fullscreen=False, idle_s=130, since_last_s=300)
    assert not can_roam(enabled=True, reduce_motion=True, fullscreen=False, idle_s=130, since_last_s=300)
    assert not can_roam(enabled=True, reduce_motion=False, fullscreen=True, idle_s=130, since_last_s=300)
    assert not can_roam(enabled=True, reduce_motion=False, fullscreen=False, idle_s=130, since_last_s=300, typing_covered=True)
    assert not can_roam(enabled=True, reduce_motion=False, fullscreen=False, idle_s=30, since_last_s=300)
    assert not can_roam(enabled=True, reduce_motion=False, fullscreen=False, idle_s=130, since_last_s=60)

    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 64, 32)
    cr = cairo.Context(surf)
    for sp in SPECIES:
        for pose in ("sit", "blink", "walk", "nap", "bob", "stretch", "hop", "yawn", "worried"):
            paint_pet(cr, sp, 64, 32, pose=pose, badge=2 if pose == "hop" else 0, phase=1.0)


def test_milestone1():
    from .dbuswatch import media_allowed
    from .system import format_duration_hm

    assert media_allowed("org.mpris.MediaPlayer2.spotify", "all", "firefox")
    assert media_allowed("org.mpris.MediaPlayer2.spotify", "allow", "spotify, vlc")
    assert not media_allowed("org.mpris.MediaPlayer2.firefox.instance1", "allow", "spotify, vlc")
    assert not media_allowed("org.mpris.MediaPlayer2.firefox.instance1", "ignore", "firefox")
    assert media_allowed("org.mpris.MediaPlayer2.spotify", "ignore", "firefox")
    assert format_duration_hm(2.5) == "2h 30m" and format_duration_hm(0.25) == "15m"
    cfg = config.validate({"title_in_pill": True, "media_source_mode": "ignore", "media_source_apps": "firefox",
                           "key_output": "<Ctrl><Alt>O", "record_pc_sound": False, "game_strip_everywhere": True})
    assert cfg["title_in_pill"] and cfg["media_source_mode"] == "ignore" and cfg["media_source_apps"] == "firefox"
    assert cfg["key_output"] == "<Ctrl><Alt>O" and not cfg["record_pc_sound"] and cfg["game_strip_everywhere"]


def test_extra_widgets(tmp):
    from datetime import datetime
    from .widgets import ReminderStore, TodoStore, countdown_parts, parse_currency_spec, parse_reminder, safe_eval_math

    assert safe_eval_math("25 * 4 + 12") == "112"
    assert safe_eval_math("sqrt(81) + 2^3") == "17"
    assert safe_eval_math("__import__('os').system('id')") is None

    now = datetime(2026, 11, 20, 10, 0)
    assert countdown_parts("2026-11-25", now=now)[0] == "4d"
    assert countdown_parts("2026-11-20 12:30", now=now)[0] == "2h 30m"
    assert countdown_parts("2020-01-01", now=now)[0] == "Done"

    due, msg = parse_reminder("15m Stretch", now=now)
    assert msg == "Stretch" and round(due - now.timestamp()) == 900
    due2, msg2 = parse_reminder("14:30 Standup", now=now)
    assert msg2 == "Standup" and due2 > now.timestamp()

    ts = TodoStore(os.path.join(tmp, "todos.json"))
    assert ts.add("Buy milk") and ts.add("Ship release")
    ts.toggle(0)
    ts.clear_done()
    assert [i["text"] for i in ts.items] == ["Buy milk"]

    rs = ReminderStore(os.path.join(tmp, "rem.json"))
    assert rs.add("1s Ping", now=now)
    assert len(rs.pop_due(now_ts=now.timestamp() + 5)) == 1
    assert rs.pop_due(now_ts=now.timestamp() + 5) == []

    assert parse_currency_spec("EUR: USD, JPY") == ("EUR", ["USD", "JPY"])


def test_panels_and_rules():
    from .apprules import match_app_rule, parse_app_rules
    from .panels import parse_launch_apps

    assert parse_app_rules("vlc:hide, code:slim, bad:nope") == [("vlc", "hide"), ("code", "slim")]
    assert match_app_rule("vlc", "Movie.mkv", "vlc:hide, code:slim") == "hide"
    assert match_app_rule("Code", "app.py - VS Code", "vlc:hide, code:slim") == "slim"
    assert match_app_rule("firefox", "Docs", "vlc:hide, code:slim") is None
    assert parse_launch_apps("nemo, firefox, konsole") == ["nemo", "firefox", "konsole"]
    cfg = config.validate({"launcher_panel": True, "camera_panel": True, "chat_overlay": True,
                           "app_rules": "vlc:hide", "key_chat_drawer": "<Ctrl><Alt><Shift>C"})
    assert cfg["launcher_panel"] and cfg["camera_panel"] and cfg["chat_overlay"] and cfg["app_rules"] == "vlc:hide"


def test_parity_settings():
    import time as _t
    from .privacy import active_video
    from .system import format_clock, human_rate

    assert human_rate(125_000, bits=False) == "125.0 KB/s"
    assert human_rate(125_000, bits=True) == "1.0 Mb/s"
    lt = _t.struct_time((2026, 11, 20, 14, 5, 0, 4, 324, 0))
    assert format_clock("24h", lt) == "14:05" and format_clock("12h", lt) == "2:05 PM"
    nodes = [{"type": "PipeWire:Interface:Node", "info": {"state": "running", "props": {
        "media.class": "Video/Source", "media.role": "Camera", "application.name": "OBS Studio"}}}]
    assert active_video(nodes) == {"Camera"}
    assert active_video(nodes, ignored="obs") == set()
    cfg = config.validate({"network_in_bits": True, "time_format": "12h", "day_clock_size": 140,
                           "day_clock_color": "black", "chat_opacity": 75, "chat_text_size": 14,
                           "reminder_sound": "repeat", "overlay_upload": True, "sites_watch": "example.com"})
    assert cfg["network_in_bits"] and cfg["time_format"] == "12h" and cfg["day_clock_size"] == 140
    assert cfg["day_clock_color"] == "black" and cfg["chat_opacity"] == 75 and cfg["reminder_sound"] == "repeat"


def main():
    tests = [("config loader", test_config), ("lyrics parser", test_lyrics), ("clipboard store", test_clipstore),
             ("socket protocol", test_protocol), ("mic recording parser", lambda _t: test_source_outputs()),
             ("twitch chat parser", lambda _t: test_twitch()), ("taskbar keys", lambda _t: test_taskkeys()), ("language", lambda _t: test_language()), ("dock previews", lambda _t: test_previews()), ("alt+tab layout", lambda _t: test_alttab()), ("youtube chat parser", lambda _t: test_youtube()), ("widget order", lambda _t: test_widget_order()), ("dock background", lambda _t: test_dockbg()), ("pet jobs", lambda _t: test_pet_jobs()), ("media & audio essentials", lambda _t: test_milestone1()), ("extra widgets", test_extra_widgets), ("panels & app rules", lambda _t: test_panels_and_rules()), ("notchpixel parity settings", lambda _t: test_parity_settings())]
    failed = 0
    for name, fn in tests:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                fn(tmp)
                print(f"ok    {name}")
            except Exception as e:  # report every test, then exit non-zero
                failed += 1
                print(f"FAIL  {name}: {type(e).__name__}: {e}")
    print("all tests passed" if not failed else f"{failed} test(s) failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
