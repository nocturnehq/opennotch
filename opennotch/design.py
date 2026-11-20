"""OpenNotch's own look: one set of colours, type, radii and motion shared by every surface.

Direction: a near-black, gallery-like surface; hairline edges instead of filled grey boxes; warm off-white
text; one champagne accent used sparingly; light weights for big numbers, tracked small capitals for labels.
"""
import math

# ---- colour (r, g, b in 0..1 for cairo; css strings for GTK)
INK = (0.020, 0.020, 0.024)          # the island and cards: black (user: "black with liquid glass is fine")
INK_RAISED = (0.055, 0.055, 0.062)   # a tile sitting on the island
TEXT = "#ffffff"
TEXT_2 = "rgba(255,255,255,0.60)"    # secondary
TEXT_3 = "rgba(255,255,255,0.40)"    # hints
HAIRLINE = "rgba(255,255,255,0.08)"
HAIRLINE_STRONG = "rgba(255,255,255,0.14)"
FILL = "rgba(255,255,255,0.06)"      # frosted glass tile
FILL_HOVER = "rgba(255,255,255,0.10)"
CHAMPAGNE = "#ffffff"                # the accent: active tab, lit controls, progress are plain white (user's pick)
CHAMPAGNE_RGB = (1.0, 1.0, 1.0)
# playful look: every widget, tab and control has its own bright colour; text on them is dark plum
ON_COLOR = "#1d1424"
COLORS = {"sky": "#7cc6ff", "coral": "#ff8a7a", "sun": "#ffd45e", "mint": "#6fe3c1", "lime": "#c4f06a",
          "lilac": "#b9a3ff", "pink": "#ff8fc7", "peach": "#ffb36b", "cream": "#fff1a8"}
WIDGET_COLORS = {"date": "sky", "timer": "coral", "weather": "sun", "stats": "mint", "battery": "lime",
                 "storage": "lilac", "upnext": "pink", "clock": "peach", "nowplaying": "pink", "notes": "cream"}
TAB_COLORS = {"music": "pink", "web": "sky", "notifications": "sun", "shelf": "peach", "clipboard": "lilac",
              "overview": "mint", "controls": "lime", "claude": "coral"}
TILE_COLORS = {"wifi": "sky", "bt": "lilac", "night": "peach", "dnd": "lime", "mute": "coral", "mic": "mint"}
DANGER = "#ff5a4f"
OK = "#5fd38a"

# ---- shape and type
RADIUS_TILE = 16
RADIUS_CONTROL = 11
TRACKING_LABEL = "0.14em"

# ---- motion
GROW_SECONDS = 0.52
SETTLE_SECONDS = 0.36
CSS_EASE = "cubic-bezier(0.22, 1, 0.36, 1)"  # ease-out-quint: calm
CSS_FAST = "160ms"
CSS_SLOW = "260ms"


def spring(t, damping=0.74, stiffness=12.0):
    """An iOS-like spring from 0 to 1: quick, with a small settle (a few % overshoot)."""
    if t >= 1:
        return 1.0
    w = stiffness
    wd = w * math.sqrt(1 - damping ** 2)
    value = 1 - math.exp(-damping * w * t) * (math.cos(wd * t) + damping * w / wd * math.sin(wd * t))
    return value + (1 - value) * t ** 4  # land exactly on 1 at t=1 without a visible jump


def ease_out_quint(t):
    return 1 - (1 - t) ** 5


def content_fade(p):
    """Opacity of a card's content while its shape morphs: in over the middle of the move, done before it lands."""
    return min(1.0, max(0.0, (p - 0.35) / 0.4))


def island_css(font):
    """Layered after the island's base stylesheet, so these rules win."""
    t = dict(text=TEXT, t2=TEXT_2, t3=TEXT_3, hair=HAIRLINE, hair2=HAIRLINE_STRONG, fill=FILL, fillh=FILL_HOVER,
             gold=CHAMPAGNE, ease=CSS_EASE, fast=CSS_FAST, slow=CSS_SLOW, rt=RADIUS_TILE, rc=RADIUS_CONTROL,
             track=TRACKING_LABEL, font=font, ink="rgb(%d,%d,%d)" % tuple(round(c * 255) for c in INK_RAISED))
    return """
#notch * {{ color: {text}; font-family: "{font}", "Geist", "SF Pro Text", sans-serif; }}
#notch .card {{ background: transparent; border: 1px solid {hair}; border-radius: {rt}px; }}
#notch frame.tile, #notch .notecard {{ background: {fill}; border: 1px solid {hair}; border-radius: {rt}px; }}
#notch .notecard:hover {{ background: {fillh}; border-color: {hair2}; }}
#notch .label, #notch .apptag, #notch .biglabel {{ color: {t3}; font-size: 10px; font-weight: 600; letter-spacing: {track}; }}
#notch .dim, #notch .dim *, #notch .notefoot {{ color: {t2}; }}
#notch .title {{ font-size: 15px; font-weight: 600; letter-spacing: 0.01em; }}
#notch .song {{ font-size: 18px; font-weight: 600; letter-spacing: -0.01em; }}
#notch .big, #notch .bigtime, #notch .bignum {{ font-weight: 200; letter-spacing: -0.02em; }}
#notch .temp, #notch .bigtemp {{ font-weight: 200; }}
#notch .wing {{ font-weight: 600; letter-spacing: 0.02em; }}
#notch .wingdim {{ color: {t2}; font-weight: 500; }}
#notch .lyric {{ color: {t3}; font-weight: 500; }}
#notch .lyric.now {{ color: {text}; font-weight: 600; }}
#notch button {{ background: transparent; border: 1px solid transparent; border-radius: {rc}px;
  transition: background-color {fast} {ease}, border-color {fast} {ease}, color {fast} {ease}; }}
#notch button:hover {{ background: {fill}; border-color: {hair}; }}
#notch button.flat:hover {{ background: {fill}; }}
#notch button.round {{ border: 1px solid {hair2}; }}
#notch button.round.play {{ background-color: {text}; border-color: {text}; }}
#notch button.tab {{ border-radius: 99px; }}
#notch button.tab label {{ color: {t3}; font-weight: 500; letter-spacing: 0.02em; }}
#notch button.tab.active {{ background: transparent; border-color: {hair2}; }}
#notch button.tab.active label, #notch button.tab:hover label {{ color: {text}; }}
#notch button.tabicon image {{ color: {t3}; transition: color {slow} {ease}; }}
#notch button.tabicon.active {{ background-image: radial-gradient(circle at 50% 92%, {gold} 1.5px, transparent 2.1px); }}
#notch button.qtile {{ background: {fill}; border: 1px solid {hair}; border-radius: {rt}px;
  transition: background-color {slow} {ease}, border-color {slow} {ease}; }}
#notch button.qtile:hover {{ background: {fillh}; border-color: {hair2}; }}
#notch button.qtile.on {{ background: #ffffff; border-color: #ffffff; }}
#notch button.qtile.on *, #notch button.qtile.on image {{ color: #000000; }}
#notch .segbar {{ background: transparent; border: 1px solid {hair}; border-radius: 99px; }}
#notch button.seg {{ border-radius: 99px; }}
#notch button.seg.active {{ background: {text}; }}
#notch button.clipfilter {{ border: 1px solid {hair}; }}
#notch button.clipfilter:checked {{ background: {text}; border-color: {text}; }}
#notch .clipcard, #notch .cliprow {{ background: {ink}; border: 1px solid {hair}; }}
#notch .clipcard:hover, #notch .clipcard.pinned {{ border-color: {gold}; }}
#notch .cliphead {{ background: {fill}; }}
#notch row {{ border-radius: {rc}px; transition: background-color {fast} {ease}; }}
#notch row:hover {{ background: {fill}; }}
#notch scale trough {{ background: {hair2}; min-height: 3px; }}
#notch scale highlight {{ background: {text}; }}
#notch scale.big trough {{ background: {fill}; border: 1px solid {hair}; }}
#notch scale.big highlight {{ background: {text}; }}
#notch levelbar trough {{ background: {hair}; min-height: 3px; }}
#notch levelbar block.filled, #notch levelbar block.filled.low, #notch levelbar block.filled.high,
#notch levelbar block.filled.full {{ background: {gold}; border: none; }}
#notch levelbar block:not(.empty) {{ background-color: {gold}; background-image: none; border: none; box-shadow: none; }}
#notch entry {{ background: {fill}; border: 1px solid {hair}; transition: border-color {fast} {ease}; }}
#notch entry:focus {{ border-color: {gold}; }}
#notch .today {{ background: transparent; border: 1px solid {gold}; }}
#notch calendar:selected {{ background: {text}; color: #0b0b0c; }}
#notch .toasticon {{ border-radius: 99px; }}
#notch .toasticon.info {{ background: transparent; border: 1px solid {gold}; color: {gold}; }}
#notch .toasticon.ok {{ background: transparent; border: 1px solid {ok}; color: {ok}; }}
#notch .toasticon.fail {{ background: transparent; border: 1px solid {danger}; color: {danger}; }}
#notch .badge {{ background: {gold}; color: #0b0b0c; }}
#notch .emptyicon {{ color: {t3}; }}
#notch button.bigplay {{ min-width: 40px; min-height: 40px; padding: 0; border-radius: 99px; }}
#notch button.transport {{ border-radius: 99px; padding: 8px; }}
#notch button.transport image {{ color: {t2}; }}
#notch button.transport:hover image {{ color: {text}; }}
#notch button.chip {{ border: 1px solid {hair2}; border-radius: 99px; padding: 3px 12px; }}
#notch button.chip label {{ font-size: 11px; color: {t2}; letter-spacing: 0.04em; }}
#notch .time {{ font-size: 10px; color: {t3}; font-feature-settings: "tnum"; }}
#notch .tabbar {{ background: rgba(242,239,233,0.035); border: 1px solid {hair}; border-radius: 99px; padding: 3px 5px; }}
#notch button.tabicon {{ background-image: none; border: none; border-radius: 99px; padding: 6px 10px; min-width: 18px;
  transition: background-color {slow} {ease}; }}
#notch button.tabicon:hover {{ background-color: {fill}; }}
#notch button.tabicon.active {{ background-image: none; background-color: {gold}; }}
#notch button.tabicon.active image {{ color: #0b0b0c; }}
#notch .bignum {{ font-size: 40px; }}
#notch .bigtemp, #notch .temp {{ font-size: 38px; }}
#notch .bigtime {{ font-size: 40px; }}
#notch .song {{ font-size: 20px; }}
#notch frame.tile, #notch .notecard, #notch .card {{ border-radius: 20px; }}
#notch .clipcard {{ border-radius: 16px; }}
#notch .cliphead {{ background: transparent; border-bottom: 1px solid {hair}; border-radius: 16px 16px 0 0; }}
#notch textview.notes, #notch textview.notes text {{ background: transparent; color: {text}; caret-color: {gold}; }}
#notch .stitle {{ font-size: 13px; font-weight: 500; }}
#notch entry.ask {{ border-radius: 99px; padding: 8px 16px; }}
#notch button.flat {{ color: {t2}; }}
""".format(ok=OK, danger=DANGER, **t)


def settings_css(font="Geist"):
    t = dict(text=TEXT, t2=TEXT_2, t3=TEXT_3, hair=HAIRLINE, hair2=HAIRLINE_STRONG, fill=FILL, fillh=FILL_HOVER,
             gold=CHAMPAGNE, ease=CSS_EASE, fast=CSS_FAST, slow=CSS_SLOW, track=TRACKING_LABEL, font=font)
    return """
#glass * {{ color: {text}; font-family: "{font}", "Geist", "SF Pro Text", sans-serif; }}
#glass .dim {{ color: {t2}; }}
#glass .h1 {{ font-size: 30px; font-weight: 300; letter-spacing: -0.02em; }}
#glass .eyebrow {{ color: {gold}; font-size: 10px; font-weight: 600; letter-spacing: {track}; }}
#glass .stitle {{ font-weight: 500; }}
#glass .soon {{ background: transparent; border: 1px solid {hair2}; color: {t3}; }}
#glass .row {{ border-bottom: 1px solid {hair}; padding: 16px 0; }}
#glass row.side {{ border: 1px solid transparent; transition: background-color {slow} {ease}, border-color {slow} {ease}; }}
#glass row.side:hover {{ background: {fill}; }}
#glass row.side:selected {{ background: {fill}; border-color: {hair2}; }}
#glass entry {{ background: {fill}; border: 1px solid {hair}; transition: border-color {fast} {ease}; }}
#glass entry:focus {{ border-color: {gold}; }}
#glass button {{ background: transparent; border: 1px solid {hair}; transition: background-color {fast} {ease}, border-color {fast} {ease}; }}
#glass button:hover {{ background: {fill}; border-color: {hair2}; }}
#glass .segbar {{ background: transparent; border: 1px solid {hair}; }}
#glass button.seg {{ border: none; transition: background-color {slow} {ease}; }}
#glass button.seg.active {{ background: {text}; }}
#glass switch {{ background: {fill}; border: 1px solid {hair2}; transition: background-color {slow} {ease}; }}
#glass switch:checked {{ background: {gold}; border-color: {gold}; }}
#glass switch slider {{ background: {text}; transition: all {slow} {ease}; }}
#glass switch:checked slider {{ background: #0b0b0c; }}
#glass scale trough {{ background: {hair2}; min-height: 3px; }}
#glass scale highlight {{ background: {gold}; }}
#glass scale slider {{ background: {text}; }}
#glass spinbutton {{ background: {fill}; border: 1px solid {hair}; }}
#glass .orderlist button.seg {{ padding: 2px 6px; }}
""".format(**t)


def playful_css():
    """The playful layer, after island_css: bright tiles, colour blob tabs, chunky shapes."""
    c, on = COLORS, ON_COLOR
    rules = [f"#notch .card, #notch frame.tile, #notch .notecard {{ border-radius: {RADIUS_TILE}px; }}",
             f"#notch .tabbar {{ background: rgba(255,255,255,0.06); border: none; padding: 4px 6px; }}",
             f"#notch button.tabicon {{ padding: 7px 11px; }}",
             f"#notch button.round.play.bigplay {{ background-color: {c['pink']}; border-color: {c['pink']}; min-width: 46px; min-height: 46px; }}",
             f"#notch button.round.play.bigplay image {{ color: {on}; }}",
             f"#notch scale.big trough {{ background: rgba(255,255,255,0.06); border: none; border-radius: 22px; }}",
             f"#notch scale.big highlight {{ background: {c['sky']}; border-radius: 22px; }}",
             f"#notch button.chip {{ border-color: {c['pink']}; }}",
             f"#notch button.chip label {{ color: {c['pink']}; font-weight: 700; }}",
             f"#notch .toasticon.ok {{ background: {c['mint']}; border: none; color: {on}; }}",
             f"#notch .toasticon.fail {{ background: {c['coral']}; border: none; color: {on}; }}",
             f"#notch .toasticon.info {{ background: {c['sky']}; border: none; color: {on}; }}",
             f"#notch .song {{ font-size: 22px; font-weight: 800; }}",
             f"#notch .big, #notch .bigtime, #notch .bignum, #notch .bigtemp, #notch .temp {{ font-weight: 800; letter-spacing: -0.01em; }}",
             f"#notch .label, #notch .apptag, #notch .biglabel {{ font-weight: 800; }}",
             f"#notch .wing {{ font-weight: 800; }}",
             f"#notch .title {{ font-weight: 800; }}",
             f"#notch .notecard {{ background: rgba(185,163,255,0.10); border: none; }}",
             f"#notch .clipcard, #notch .cliprow {{ border: none; background: rgba(255,255,255,0.06); }}",
             f"#notch .clipcard:hover, #notch .clipcard.pinned {{ background: {c['lilac']}; }}",
             f"#notch .clipcard:hover *, #notch .clipcard.pinned * {{ color: {on}; }}",
             f"#notch button.clipfilter:checked, #notch button.seg.active {{ background: {c['sun']}; border-color: {c['sun']}; }}",
             f"#notch button.clipfilter:checked label, #notch button.seg.active label {{ color: {on}; }}",
             f"#notch entry {{ border-radius: 99px; }}",
             f"#notch .mono {{ font-family: \"Nunito\", sans-serif; font-size: 11px; font-weight: 700; }}",
             f"#notch tooltip, tooltip {{ background: {c['lilac']}; border-radius: 12px; }}",
             f"#notch tooltip *, tooltip * {{ color: {on}; font-weight: 700; }}",
             f"#notch .badge {{ background: {c['coral']}; color: {on}; }}",
             f"#notch entry:focus {{ border-color: {c['pink']}; }}"]
    for name, colour in WIDGET_COLORS.items():
        col = c[colour]
        rules += [f"#notch .w-{name} {{ background: {col}; border: none; }}",
                  f"#notch .w-{name} *, #notch .w-{name} .dim, #notch .w-{name} .label {{ color: {on}; }}",
                  f"#notch .w-{name} .dim, #notch .w-{name} .label, #notch .w-{name} .time {{ color: rgba(29,20,36,0.62); }}",
                  f"#notch .w-{name} button.round {{ border-color: rgba(29,20,36,0.35); }}",
                  f"#notch .w-{name} button.round.play {{ background-color: {on}; border-color: {on}; }}",
                  f"#notch .w-{name} button.round.play image {{ color: {col}; }}",
                  f"#notch .w-{name} .today {{ border-color: {on}; }}",
                  f"#notch .w-{name} levelbar trough {{ background: rgba(29,20,36,0.15); }}",
                  f"#notch .w-{name} levelbar block:not(.empty) {{ background-color: {on}; }}",
                  f"#notch .w-{name} textview.notes, #notch .w-{name} textview.notes text {{ color: {on}; caret-color: {on}; }}"]
    for name, colour in TAB_COLORS.items():
        rules += [f"#notch button.t-{name} image {{ color: {c[colour]}; }}",
                  f"#notch button.t-{name}.active {{ background-color: {c[colour]}; }}",
                  f"#notch button.t-{name}.active image {{ color: {on}; }}"]
    for name, colour in TILE_COLORS.items():
        r, g, b = (int(c[colour][i:i + 2], 16) for i in (1, 3, 5))
        rules += [f"#notch button.qtile.q-{name} {{ background: rgba({r},{g},{b},0.13); border: none; }}",
                  f"#notch button.qtile.q-{name}:hover {{ background: rgba({r},{g},{b},0.22); }}",
                  f"#notch button.qtile.q-{name} image {{ color: {c[colour]}; }}",
                  f"#notch button.qtile.q-{name}.on {{ background: {c[colour]}; border-color: {c[colour]}; }}",
                  f"#notch button.qtile.q-{name}.on *, #notch button.qtile.q-{name}.on image {{ color: {on}; }}"]
    return "\n".join(rules) + "\n"


def type_css():
    """Three sizes only: 32 px bold numbers (SF Pro Display), 14 px semibold titles, 11 px for everything else."""
    return f"""
#notch * {{ font-family: "SF Pro Text", "SF Pro Display", sans-serif; font-size: 11px; letter-spacing: 0; }}
#notch .big, #notch .bigtime, #notch .bignum, #notch .bigtemp, #notch .temp {{ font-family: "SF Pro Display";
  font-size: 32px; font-weight: 700; letter-spacing: -0.02em; }}
#notch .title, #notch .song, #notch .stitle, #notch .lyric.now {{ font-family: "SF Pro Display"; font-size: 14px; font-weight: 600; }}
#notch .label, #notch .apptag, #notch .biglabel, #notch .eyebrow {{ font-size: 11px; font-weight: 500; letter-spacing: 0; color: {TEXT_3}; }}
#notch .wing {{ font-size: 11px; font-weight: 600; }}
#notch .tabbar {{ padding: 2px 3px; background: rgba(255,255,255,0.05); border: none; }}
#notch button.tabicon {{ padding: 4px 7px; }}
#notch button.tabicon.active {{ background-color: #ffffff; }}
#notch button.tabicon.active image {{ color: #000000; }}
#notch button.round.play.bigplay {{ background-color: #ffffff; min-width: 38px; min-height: 38px; }}
#notch button.round.play.bigplay image {{ color: #000000; }}
#notch button.chip label {{ font-size: 11px; }}
#notch frame.tile, #notch .notecard, #notch .card {{ border-radius: {RADIUS_TILE}px; }}
"""


def playful_settings_css():
    c, on = COLORS, ON_COLOR
    return f"""
#glass .eyebrow {{ color: {c['coral']}; }}
#glass .h1 {{ font-weight: 900; letter-spacing: -0.01em; }}
#glass .stitle {{ font-weight: 700; }}
#glass row.side:selected {{ background: {c['lilac']}; border-color: {c['lilac']}; }}
#glass row.side:selected * {{ color: {on}; }}
#glass button.seg.active {{ background: {c['sun']}; }}
#glass button.seg.active label {{ color: {on}; }}
#glass switch:checked {{ background: {c['mint']}; border-color: {c['mint']}; }}
#glass scale highlight {{ background: {c['pink']}; }}
#glass entry:focus {{ border-color: {c['pink']}; }}
#glass .row {{ border-bottom: none; }}
#glass row.side {{ border-radius: 14px; }}
#glass row.side:hover {{ background: rgba(185,163,255,0.14); }}
#glass button.seg {{ border-radius: 99px; }}
#glass .segbar {{ border-radius: 99px; background: rgba(255,255,255,0.05); border: none; }}
#glass switch {{ min-height: 26px; }}
#glass .soon {{ border-color: {c['peach']}; color: {c['peach']}; }}
#glass button.swatch.active {{ box-shadow: 0 0 0 2px #140f19, 0 0 0 4px {c['pink']}; }}
"""
