"""Per-app behaviour rules (e.g. 'vlc:hide, code:slim') for OpenNotch."""
import gi

try:
    gi.require_version("Wnck", "3.0")
    from gi.repository import Wnck
except (ImportError, ValueError):
    Wnck = None


def parse_app_rules(raw):
    """Parse 'vlc:hide, code:slim' into [(pattern_lower, action)]."""
    rules = []
    for entry in (raw or "").split(","):
        if ":" not in entry:
            continue
        pat, act = entry.split(":", 1)
        pat, act = pat.strip().lower(), act.strip().lower()
        if pat and act in ("hide", "slim"):
            rules.append((pat, act))
    return rules


def match_app_rule(wm_class, title, raw_rules):
    """Return 'hide', 'slim', or None for the given window class/title."""
    hay = f"{wm_class or ''} {title or ''}".lower()
    if not hay.strip():
        return None
    for pat, act in parse_app_rules(raw_rules):
        if pat in hay:
            return act
    return None


def active_app_rule(raw_rules):
    """Return the matched rule ('hide' | 'slim' | None) for the currently focused X11 window."""
    if not raw_rules or Wnck is None:
        return None
    screen = Wnck.Screen.get_default()
    active = screen.get_active_window() if screen else None
    if active is None:
        return None
    return match_app_rule(active.get_class_group_name(), active.get_name(), raw_rules)
