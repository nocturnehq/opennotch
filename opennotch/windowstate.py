"""Read the active X11 window's coverage using libwnck when available."""
import gi

from gi.repository import Gdk

try:
    gi.require_version("Wnck", "3.0")
    from gi.repository import Wnck
except (ImportError, ValueError):
    Wnck = None


def coverage(monitor):
    if monitor is None:
        return False, False
    if Wnck is None:
        active = monitor.get_display().get_default_screen().get_active_window()
        state = active.get_state() if active else Gdk.WindowState(0)
        return bool(state & Gdk.WindowState.MAXIMIZED), bool(state & Gdk.WindowState.FULLSCREEN)
    screen = Wnck.Screen.get_default()
    active = screen.get_active_window() if screen else None
    if active is None:
        return False, False
    bounds = monitor.get_geometry()
    x, y, w, h = active.get_geometry()
    overlap_w = max(0, min(x + w, bounds.x + bounds.width) - max(x, bounds.x))
    overlap_h = max(0, min(y + h, bounds.y + bounds.height) - max(y, bounds.y))
    if overlap_w * overlap_h < bounds.width * bounds.height / 2:
        return False, False
    return active.is_maximized(), active.is_fullscreen()
