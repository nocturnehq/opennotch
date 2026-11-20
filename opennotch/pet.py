"""Small monochrome pets for the island, with moods, health nudges, smart click and roaming."""
import ctypes
import ctypes.util
import math
import time

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import design  # noqa: E402
from .windowstate import coverage  # noqa: E402

SPECIES = ("cat", "dog", "bunny")
FUR = (0.96, 0.96, 0.97)
MARKS = (0.08, 0.08, 0.09)
POSES = (("sit", 1800), ("blink", 140), ("sit", 2100),
         ("walk", 1800), ("sit", 1400), ("nap", 3200))

IDLE_NAP_S = 60.0       # nap on the pill after 1 min idle
ROAM_IDLE_S = 120.0     # roam after ~2 min idle
ROAM_COOLDOWN_S = 240.0 # at most once every ~4 min
ROAM_DURATION_S = 20.0  # stroll for ~20 s then return home
ROAM_SIZE = 42


def choose_mood(*, unread=0, low_battery=False, high_load=False,
                pomo_running=False, pomo_phase="focus", playing=False, idle_s=0.0):
    """Pick the pet's current mood by priority."""
    if unread > 0:
        return "notice"
    if low_battery:
        return "worried"
    if high_load:
        return "yawn"
    if pomo_running:
        return "focus" if pomo_phase == "focus" else "stretch"
    if playing:
        return "bob"
    if idle_s >= IDLE_NAP_S:
        return "nap"
    return "idle"


def smart_click_action(unread=0, health_issue=None):
    """Decide what clicking the pet does: unread notice -> health stat -> focus timer."""
    if unread > 0:
        return "notifications"
    if health_issue:
        return "stats"
    return "timer"


def can_roam(*, enabled, reduce_motion, fullscreen, idle_s, since_last_s, typing_covered=False):
    """Guard for starting a roaming stroll."""
    if not enabled or reduce_motion or fullscreen or typing_covered:
        return False
    return idle_s >= ROAM_IDLE_S and since_last_s >= ROAM_COOLDOWN_S


# ---- X11 idle time via libXss (works on both KDE Plasma X11 and Cinnamon) ----

class _XScreenSaverInfo(ctypes.Structure):
    _fields_ = [("window", ctypes.c_ulong), ("state", ctypes.c_int), ("kind", ctypes.c_int),
                ("til_or_since", ctypes.c_ulong), ("idle", ctypes.c_ulong), ("event_mask", ctypes.c_ulong)]


class IdleClock:
    """Query X11 user idle time in seconds (falls back to 0.0 if libXss is unavailable)."""

    def __init__(self):
        self._x11 = None
        self._xss = None
        self._disp = None
        self._info = None
        try:
            x11_name = ctypes.util.find_library("X11")
            xss_name = ctypes.util.find_library("Xss")
            if not x11_name or not xss_name:
                return
            self._x11 = ctypes.cdll.LoadLibrary(x11_name)
            self._xss = ctypes.cdll.LoadLibrary(xss_name)
            self._x11.XOpenDisplay.restype = ctypes.c_void_p
            self._x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            self._x11.XDefaultRootWindow.restype = ctypes.c_ulong
            self._x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
            self._x11.XFree.argtypes = [ctypes.c_void_p]
            self._xss.XScreenSaverAllocInfo.restype = ctypes.POINTER(_XScreenSaverInfo)
            self._xss.XScreenSaverQueryInfo.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(_XScreenSaverInfo)
            ]
            self._disp = self._x11.XOpenDisplay(None)
            if self._disp:
                self._info = self._xss.XScreenSaverAllocInfo()
        except OSError:
            self._disp = None

    def seconds(self):
        if not self._disp or not self._info:
            return 0.0
        try:
            root = self._x11.XDefaultRootWindow(self._disp)
            if self._xss.XScreenSaverQueryInfo(self._disp, root, self._info):
                return self._info.contents.idle / 1000.0
        except Exception:
            pass
        return 0.0

    def close(self):
        if self._info and self._x11:
            try:
                self._x11.XFree(self._info)
            except Exception:
                pass
            self._info = None
        if self._disp and self._x11:
            try:
                self._x11.XCloseDisplay(self._disp)
            except Exception:
                pass
            self._disp = None


# ---- Cairo drawing ----

def _oval(cr, x, y, rx, ry):
    cr.new_sub_path()
    cr.save()
    cr.translate(x, y)
    cr.scale(rx, ry)
    cr.arc(0, 0, 1, 0, math.tau)
    cr.restore()
    cr.fill()


def _line(cr, points, width):
    cr.set_line_width(width)
    cr.move_to(*points[0])
    for point in points[1:]:
        cr.line_to(*point)
    cr.stroke()


def _ears(cr, species, x, y):
    if species == "cat":
        for direction in (-1, 1):
            cr.move_to(x + 2 * direction, y + 1)
            cr.line_to(x + 4.8 * direction, y - 4)
            cr.line_to(x + 6 * direction, y + 2)
            cr.close_path()
        cr.fill()
    elif species == "dog":
        for direction in (-1, 1):
            _oval(cr, x + 5 * direction, y + 1.5, 1.9, 3.5)
    else:
        for direction in (-1, 1):
            _oval(cr, x + 2.4 * direction, y - 3.6, 1.65, 4.5)


def _face(cr, species, x, y, sleepy=False, worried=False, yawning=False):
    cr.set_source_rgb(*FUR)
    _ears(cr, species, x, y)
    _oval(cr, x, y + 1.7, 5.1, 4.0)
    cr.set_source_rgb(*MARKS)
    if sleepy or yawning:
        for offset in (-2, 2):
            _line(cr, ((x + offset - 0.7, y + 1.5), (x + offset + 0.7, y + 1.5)), 0.75)
    else:
        for offset in (-2, 2):
            _oval(cr, x + offset, y + 1.45, 0.65, 0.85)
    if worried:
        # angled worried brows
        _line(cr, ((x - 2.9, y + 0.5), (x - 1.2, y - 0.1)), 0.65)
        _line(cr, ((x + 2.9, y + 0.5), (x + 1.2, y - 0.1)), 0.65)
    if yawning:
        _oval(cr, x, y + 3.45, 1.15, 1.35)
    elif species == "dog":
        _oval(cr, x, y + 3.1, 1.0, 0.7)
    else:
        _oval(cr, x, y + 3.05, 0.58, 0.45)
        if species == "cat":
            for direction in (-1, 1):
                _line(cr, ((x + 3 * direction, y + 3), (x + 4 * direction, y + 3.25)), 0.6)


def _tail(cr, species):
    if species == "cat":
        cr.set_line_width(1.55)
        cr.move_to(12, 16.1)
        cr.curve_to(16.3, 17.7, 18.2, 15.3, 16.1, 13.7)
        cr.stroke()
    elif species == "bunny":
        _oval(cr, 14.35, 15.75, 1.45, 1.4)


def _sitting(cr, species, blink=False, worried=False, yawning=False, dy=0.0):
    cr.save()
    cr.translate(0, dy)
    cr.set_source_rgb(*FUR)
    _oval(cr, 10, 14.1, 4.4, 3.65)
    _tail(cr, species)
    _face(cr, species, 10, 8.8, sleepy=blink, worried=worried, yawning=yawning)
    cr.restore()


def _walking(cr, species, stride):
    cr.set_source_rgb(*FUR)
    _oval(cr, 8, 12.7, 5.1, 3.1)
    if species == "bunny":
        _oval(cr, 3.25, 11.75, 1.5, 1.35)
    else:
        cr.set_line_width(1.5)
        cr.move_to(4, 12.5)
        cr.curve_to(1.6, 12.3, 1.7, 8.9, 1.25, 8.5)
        cr.stroke()
    for x, direction in ((6.1, -1), (11, 1)):
        _line(cr, ((x, 14.3), (x + direction * stride, 17.2)), 1.55)
    _face(cr, species, 13.0, 8.5)


def _napping(cr, species):
    cr.set_source_rgb(*FUR)
    _oval(cr, 8.1, 14.2, 6.4, 3.55)
    _face(cr, species, 13.0, 10.9, sleepy=True)


def _stretching(cr, species):
    cr.set_source_rgb(*FUR)
    # arched back higher on the left, front paws extended forward low
    _oval(cr, 6.6, 12.4, 4.3, 3.2)
    _line(cr, ((10.0, 14.8), (15.8, 16.9)), 1.6)
    _line(cr, ((5.2, 14.0), (4.4, 17.2)), 1.5)
    if species == "bunny":
        _oval(cr, 2.6, 10.8, 1.45, 1.35)
    else:
        cr.set_line_width(1.45)
        cr.move_to(3.2, 11.5)
        cr.curve_to(1.5, 9.5, 2.2, 7.2, 3.8, 6.8)
        cr.stroke()
    _face(cr, species, 12.2, 10.6, sleepy=True)


def _hopping(cr, species, lift=2.2):
    cr.save()
    cr.translate(0, -lift)
    cr.set_source_rgb(*FUR)
    _oval(cr, 10, 13.6, 4.2, 3.5)
    # tucked little paws
    _line(cr, ((7.5, 16.3), (6.5, 17.8)), 1.4)
    _line(cr, ((12.5, 16.3), (13.5, 17.8)), 1.4)
    _tail(cr, species)
    _face(cr, species, 10, 8.3)
    cr.restore()


def _badge(cr, count):
    """Small crisp white circular notification badge with dark mark at top-right."""
    if count <= 0:
        return
    cx, cy, r = 16.4, 3.8, 3.1
    cr.set_source_rgb(*MARKS)
    cr.arc(cx, cy, r + 0.7, 0, math.tau)
    cr.fill()
    cr.set_source_rgb(*FUR)
    cr.arc(cx, cy, r, 0, math.tau)
    cr.fill()
    cr.set_source_rgb(*MARKS)
    _line(cr, ((cx, cy - 1.3), (cx, cy + 0.3)), 1.0)
    _oval(cr, cx, cy + 1.45, 0.55, 0.55)


def _music_note(cr, dy):
    """Tiny monochrome eighth-note floating beside a bobbing pet."""
    cr.save()
    cr.translate(16.2, 4.2 + dy * 0.6)
    cr.set_source_rgba(*FUR, 0.85)
    _oval(cr, 0, 2.4, 1.15, 0.85)
    _line(cr, ((1.0, 2.2), (1.0, -1.6), (2.7, -0.9)), 0.9)
    cr.restore()


def paint_pet(cr, species, width, height, *, pose="sit", location=0.5,
              facing=1, stride=0, vertical=False, badge=0, phase=0.0):
    """Paint the pet in the given box. Location is along the long axis."""
    length = height if vertical else width
    thickness = width if vertical else height
    size = min(length, thickness)
    if size <= 0:
        return
    offset = (length - size) * location
    x, y = ((width - size) / 2, offset) if vertical else (offset, (height - size) / 2)
    cr.save()
    cr.translate(x, y)
    cr.scale(size / 20, size / 20)
    if facing < 0:
        cr.translate(20, 0)
        cr.scale(-1, 1)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    if pose == "walk":
        _walking(cr, species, stride)
    elif pose == "nap":
        _napping(cr, species)
    elif pose == "stretch":
        _stretching(cr, species)
    elif pose == "bob":
        dy = -1.1 * abs(math.sin(phase))
        _sitting(cr, species, dy=dy)
        _music_note(cr, dy)
    elif pose == "hop":
        lift = 1.0 + 1.8 * abs(math.sin(phase))
        _hopping(cr, species, lift=lift)
    elif pose == "yawn":
        _sitting(cr, species, yawning=True)
    elif pose == "worried":
        _sitting(cr, species, worried=True)
    else:
        _sitting(cr, species, blink=(pose == "blink"))
    if badge > 0:
        if facing < 0:
            cr.translate(20, 0)
            cr.scale(-1, 1)
        _badge(cr, badge)
    cr.restore()


class IdlePet(Gtk.DrawingArea):
    """Compact reactive pet for the pill and open card, with moods, badge and smart click."""

    def __init__(self, species, size=24, reduce_motion=False, vertical=False, on_click=None):
        super().__init__()
        self.species = species
        self.vertical = vertical
        self.reduce_motion = reduce_motion
        self.on_click = on_click
        self.mood = "idle"
        self.badge = 0
        self._hop_until = 0.0
        self._timer = 0
        self._index = 0
        self._started = 0
        self._location = 0.5
        self._target = 0.84
        self._facing = 1
        self._stride = 0
        self._phase = 0.0
        self._stretch_on = True
        size = max(1, size)
        self.set_size_request(size if vertical else size * 2, size * 2 if vertical else size)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        if on_click is not None:
            self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.ENTER_NOTIFY_MASK)
            self.connect("button-press-event", self._on_press)
            self.connect("realize", self._on_realize_cursor)
        self.connect("draw", self._draw)
        self.connect("map", self._map_pet)
        self.connect("unmap", self._unmap_pet)
        self.connect("destroy", self._unmap_pet)

    def _on_realize_cursor(self, *_):
        win = self.get_window()
        if win is not None:
            win.set_cursor(Gdk.Cursor.new_from_name(self.get_display(), "pointer"))

    def _on_press(self, _widget, event):
        if event.button == 1 and self.on_click is not None:
            self.on_click()
            return True
        return False

    def set_mood(self, mood, badge=0, tooltip=None):
        changed = (mood != self.mood or badge != self.badge)
        self.mood = mood
        self.badge = max(0, int(badge))
        if tooltip is not None:
            self.set_tooltip_text(tooltip)
        if changed:
            self._location = 0.5
            self._facing = 1
            self._phase = 0.0
            if self.get_mapped():
                self._restart_timer()
            self.queue_draw()

    def trigger_hop(self, badge=1):
        """Hop excitedly when a notification arrives."""
        self.badge = max(self.badge, int(badge))
        self._hop_until = time.monotonic() + 2.4
        self._phase = 0.0
        if self.get_mapped():
            self._restart_timer()
        self.queue_draw()

    def _animated(self):
        return (not self.reduce_motion and self.get_mapped() and
                bool(self.get_settings().get_property("gtk-enable-animations")))

    def _restart_timer(self):
        self._unmap_pet(self)
        if not self._animated():
            return
        if time.monotonic() < self._hop_until or self.mood == "notice":
            self._schedule(110)
        elif self.mood == "bob":
            self._schedule(120)
        elif self.mood == "stretch":
            self._stretch_on = True
            self._schedule(2200)
        elif self.mood in ("focus", "nap", "yawn", "worried"):
            pass  # calm steady pose
        else:
            self._index = 0
            self._schedule(POSES[0][1])

    def _map_pet(self, _widget):
        self._index = 0
        self._location = 0.5
        self._target = 0.84
        self._facing = 1
        self._restart_timer()

    def _unmap_pet(self, _widget):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    def _schedule(self, duration):
        self._timer = GLib.timeout_add(duration, self._advance)

    def _current_pose(self):
        if time.monotonic() < self._hop_until:
            return "hop"
        if self.mood == "notice":
            return "hop" if not self.reduce_motion else "sit"
        if self.mood == "worried":
            return "worried"
        if self.mood == "yawn":
            return "yawn"
        if self.mood == "focus":
            return "sit"
        if self.mood == "stretch":
            return "stretch" if (self.reduce_motion or self._stretch_on) else "sit"
        if self.mood == "bob":
            return "bob"
        if self.mood == "nap":
            return "nap"
        return POSES[self._index][0]

    def _advance(self):
        self._timer = 0
        if not self._animated():
            return GLib.SOURCE_REMOVE
        now = time.monotonic()
        if now < self._hop_until or self.mood == "notice":
            self._phase += 0.55
            self.queue_draw()
            self._schedule(110 if now < self._hop_until else 260)
            return GLib.SOURCE_REMOVE
        if self.mood == "bob":
            self._phase += 0.52
            self.queue_draw()
            self._schedule(120)
            return GLib.SOURCE_REMOVE
        if self.mood == "stretch":
            self._stretch_on = not self._stretch_on
            self.queue_draw()
            self._schedule(2200 if self._stretch_on else 1400)
            return GLib.SOURCE_REMOVE
        if self.mood in ("focus", "nap", "yawn", "worried"):
            self.queue_draw()
            return GLib.SOURCE_REMOVE

        # Default idle cycle
        pose, duration = POSES[self._index]
        if pose == "walk":
            fraction = min(1, (GLib.get_monotonic_time() - self._started) / (duration * 1000))
            self._location = self._walk_from + fraction * (self._target - self._walk_from)
            self._stride = -self._stride
            if fraction < 1:
                self.queue_draw()
                self._schedule(135)
                return GLib.SOURCE_REMOVE
            self._target = 1 - self._target
        self._index = (self._index + 1) % len(POSES)
        pose, duration = POSES[self._index]
        if pose == "walk":
            self._started = GLib.get_monotonic_time()
            self._walk_from = self._location
            self._facing = 1 if self._target > self._location else -1
            self._stride = 1.45
            duration = 135
        self.queue_draw()
        self._schedule(duration)
        return GLib.SOURCE_REMOVE

    def _draw(self, _widget, cr):
        paint_pet(cr, self.species, self.get_allocated_width(), self.get_allocated_height(),
                  pose=self._current_pose(), location=self._location,
                  facing=self._facing, stride=self._stride, vertical=self.vertical,
                  badge=self.badge, phase=self._phase)
        return True


class RoamingPet(Gtk.Window):
    """Transparent always-on-top DOCK window that lets the pet stroll along Plank when idle."""

    def __init__(self, species, *, reduce_motion=False, get_notch_anchor=None,
                 get_plank_bounds=None, get_toast_perch=None, on_click=None):
        super().__init__(title="OpenNotch Roaming Pet")
        self.species = species
        self.reduce_motion = bool(reduce_motion)
        self.get_notch_anchor = get_notch_anchor
        self.get_plank_bounds = get_plank_bounds
        self.get_toast_perch = get_toast_perch
        self.on_click = on_click

        self.set_name("opennotch-roaming-pet")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_type_hint(Gdk.WindowTypeHint.DOCK)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_above(True)
        self.set_accept_focus(False)
        self.set_focus_on_map(False)
        self.stick()

        visual = self.get_screen().get_rgba_visual()
        if visual is not None:
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.set_size_request(ROAM_SIZE, ROAM_SIZE)
        self.resize(ROAM_SIZE, ROAM_SIZE)

        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("draw", self._draw)
        self.connect("button-press-event", self._on_press)

        self.idle_clock = IdleClock()
        self.active = False
        self.stage = "home"  # home | hop_out | stroll | perch | hop_home
        self.stage_t0 = 0.0
        self.roam_t0 = 0.0
        self.last_roam_end = time.monotonic() - ROAM_COOLDOWN_S + 30.0
        self.x = 0.0
        self.y = 0.0
        self.start_xy = (0.0, 0.0)
        self.end_xy = (0.0, 0.0)
        self.stroll_bounds = (400.0, 1200.0, 960.0)  # (left, right, y)
        self.facing = 1
        self.stride = 1.4
        self.pose = "sit"
        self.badge = 0
        self.phase = 0.0
        self._step_acc = 0.0
        self._last_tick = 0.0
        self.tick_id = 0
        self.watch_id = 0
        self.closed = False

        if not self.reduce_motion:
            self.watch_id = GLib.timeout_add_seconds(5, self._watch)

    def _monitor(self):
        display = self.get_display()
        return display.get_primary_monitor() or display.get_monitor(0)

    def _active_window_covers(self, x, y):
        """Return True if the focused normal window covers the pet's rectangle (avoid typing overlap)."""
        try:
            gi.require_version("Wnck", "3.0")
            from gi.repository import Wnck

            screen = Wnck.Screen.get_default()
            active = screen.get_active_window() if screen else None
            if active is None or active.get_window_type() != Wnck.WindowType.NORMAL:
                return False
            wx, wy, ww, wh = active.get_geometry()
            return (x + ROAM_SIZE > wx and x < wx + ww and
                    y + ROAM_SIZE > wy and y < wy + wh)
        except (ImportError, ValueError):
            return False

    def _notch_home(self):
        if self.get_notch_anchor is not None:
            pos = self.get_notch_anchor()
            if pos is not None:
                return float(pos[0] - ROAM_SIZE / 2), float(pos[1])
        mon = self._monitor()
        if mon is not None:
            g = mon.get_geometry()
            return float(g.x + g.width / 2 - ROAM_SIZE / 2), float(g.y + 30)
        return 600.0, 30.0

    def _plank_track(self):
        if self.get_plank_bounds is not None:
            bounds = self.get_plank_bounds()
            if bounds is not None:
                left, right, top_y = bounds
                if right - left > ROAM_SIZE * 2:
                    return float(left + 16), float(right - ROAM_SIZE - 16), float(top_y - ROAM_SIZE + 5)
        mon = self._monitor()
        if mon is not None:
            g = mon.get_geometry()
            w = min(640, g.width - 120)
            left = g.x + (g.width - w) / 2
            return float(left), float(left + w - ROAM_SIZE), float(g.y + g.height - 63 - ROAM_SIZE + 5)
        return 400.0, 900.0, 620.0

    def _watch(self):
        if self.closed or self.reduce_motion:
            return False
        if self.active:
            return True
        mon = self._monitor()
        _, fullscreen = coverage(mon)
        idle_s = self.idle_clock.seconds()
        since_last = time.monotonic() - self.last_roam_end
        if can_roam(enabled=True, reduce_motion=self.reduce_motion, fullscreen=fullscreen,
                    idle_s=idle_s, since_last_s=since_last):
            self.start_roam()
        return True

    def start_roam(self, force=False):
        if self.closed or self.active or (self.reduce_motion and not force):
            return False
        mon = self._monitor()
        _, fullscreen = coverage(mon)
        if fullscreen and not force:
            return False
        self.stroll_bounds = self._plank_track()
        left, right, ty = self.stroll_bounds
        if not force and self.idle_clock.seconds() < 3.0 and self._active_window_covers((left + right) / 2, ty):
            return False
        self.active = True
        self.badge = 0
        self.roam_t0 = time.monotonic()
        self.stage = "hop_out"
        self.stage_t0 = self.roam_t0
        self.start_xy = self._notch_home()
        self.end_xy = ((left + right) / 2.0, ty)
        self.x, self.y = self.start_xy
        self.facing = 1
        self.pose = "hop"
        self._last_tick = self.roam_t0
        self.move(int(round(self.x)), int(round(self.y)))
        self.show_all()
        if not self.tick_id:
            self.tick_id = self.add_tick_callback(self._tick)
        return True

    def jump_to_notice(self, badge=1):
        """If currently roaming, jump onto an incoming notice toast."""
        if not self.active or self.stage in ("home", "hop_home"):
            return
        perch = self.get_toast_perch() if self.get_toast_perch is not None else None
        if perch is None:
            return
        self.badge = max(1, int(badge))
        self.stage = "perch"
        self.stage_t0 = time.monotonic()
        self.start_xy = (self.x, self.y)
        self.end_xy = (float(perch[0] - ROAM_SIZE / 2), float(perch[1] - ROAM_SIZE + 6))
        self.pose = "hop"

    def return_home(self):
        if not self.active or self.stage == "hop_home":
            return
        self.stage = "hop_home"
        self.stage_t0 = time.monotonic()
        self.start_xy = (self.x, self.y)
        self.end_xy = self._notch_home()
        self.pose = "hop"

    def _finish(self):
        self.active = False
        self.stage = "home"
        self.badge = 0
        self.last_roam_end = time.monotonic()
        if self.tick_id:
            self.remove_tick_callback(self.tick_id)
            self.tick_id = 0
        self.hide()

    def _on_press(self, _widget, event):
        if event.button == 1:
            if self.on_click is not None:
                self.on_click()
            self.return_home()
            return True
        return False

    def _tick(self, _widget, _clock):
        if self.closed or not self.active:
            self.tick_id = 0
            return False
        now = time.monotonic()
        dt = min(0.1, max(0.0, now - self._last_tick))
        self._last_tick = now

        # Abort immediately on fullscreen, or if user starts typing in a window under the pet
        _, fullscreen = coverage(self._monitor())
        if fullscreen:
            self._finish()
            return False
        if (self.stage in ("stroll", "perch") and
                self.idle_clock.seconds() < 1.5 and self._active_window_covers(self.x, self.y)):
            self.return_home()

        if self.stage == "hop_out":
            t = min(1.0, (now - self.stage_t0) / 0.85)
            p = design.ease_out_quint(t)
            sx, sy = self.start_xy
            ex, ey = self.end_xy
            arc = -42.0 * math.sin(math.pi * t)
            self.x = sx + (ex - sx) * p
            self.y = sy + (ey - sy) * p + arc
            self.pose = "hop"
            self.phase += dt * 7.0
            if t >= 1.0:
                self.stage = "stroll"
                self.stage_t0 = now
                self.pose = "walk"
        elif self.stage == "stroll":
            left, right, ty = self.stroll_bounds
            self.y = ty
            speed = 46.0  # calm stroll in px/s
            self.x += self.facing * speed * dt
            if self.x <= left:
                self.x = left
                self.facing = 1
            elif self.x >= right:
                self.x = right
                self.facing = -1
            self._step_acc += dt
            if self._step_acc >= 0.14:
                self._step_acc = 0.0
                self.stride = -self.stride
            self.pose = "walk"
            if now - self.roam_t0 >= ROAM_DURATION_S:
                self.return_home()
        elif self.stage == "perch":
            t = min(1.0, (now - self.stage_t0) / 0.55)
            p = design.spring(t)
            sx, sy = self.start_xy
            ex, ey = self.end_xy
            arc = -36.0 * math.sin(math.pi * t)
            self.x = sx + (ex - sx) * p
            self.y = sy + (ey - sy) * p + arc
            self.pose = "hop"
            self.phase += dt * 6.0
            if now - self.stage_t0 >= 3.2:
                self.return_home()
        elif self.stage == "hop_home":
            t = min(1.0, (now - self.stage_t0) / 0.75)
            p = design.ease_out_quint(t)
            sx, sy = self.start_xy
            ex, ey = self.end_xy
            arc = -34.0 * math.sin(math.pi * t)
            self.x = sx + (ex - sx) * p
            self.y = sy + (ey - sy) * p + arc
            self.pose = "hop"
            self.phase += dt * 7.0
            if t >= 1.0:
                self._finish()
                return False

        self.move(int(round(self.x)), int(round(self.y)))
        self.queue_draw()
        return True

    def _draw(self, _widget, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        paint_pet(cr, self.species, ROAM_SIZE, ROAM_SIZE,
                  pose=self.pose, location=0.5, facing=self.facing,
                  stride=self.stride, badge=self.badge, phase=self.phase)
        return False

    def close(self):
        self.closed = True
        if self.watch_id:
            GLib.source_remove(self.watch_id)
            self.watch_id = 0
        if self.tick_id:
            self.remove_tick_callback(self.tick_id)
            self.tick_id = 0
        self.idle_clock.close()
        self.destroy()
