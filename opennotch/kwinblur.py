"""Constrain KWin's X11 backdrop blur to the current frame of the notch."""
import math

ATOM = "_KDE_NET_WM_BLUR_BEHIND_REGION"


class KWinBlur:
    def __init__(self, display_name, xid):
        from Xlib import Xatom, display

        self.connection = display.Display(display_name)
        self.atom = self.connection.intern_atom(ATOM, only_if_exists=True)
        self.cardinal = Xatom.CARDINAL
        self.root = self.connection.screen().root
        self.window = self.connection.create_resource_object("window", xid)
        self.last = None

    @property
    def available(self):
        return bool(self.atom and self.root.get_full_property(self.atom, self.atom))

    def set_region(self, cr, scale):
        if cr is None:
            if self.last is not None:
                self.window.delete_property(self.atom)
                self.connection.flush()
                self.last = None
            return
        region = []
        x0, y0, x1, y1 = cr.fill_extents()
        center = (x0 + x1) / 2
        for y in range(math.ceil(y0 * scale), math.floor(y1 * scale)):
            top, bottom = y / scale, (y + 1) / scale
            left, right = math.ceil(x0 * scale), math.floor(x1 * scale)
            center_px = round(center * scale)
            while left < center_px and not all(cr.in_fill(left / scale, py) for py in (top, bottom)):
                left += 1
            while right > center_px and not all(cr.in_fill(right / scale, py) for py in (top, bottom)):
                right -= 1
            if right <= left:
                continue
            if region and region[-4] == left and region[-2] == right - left and region[-3] + region[-1] == y:
                region[-1] += 1
            else:
                region.extend((left, y, right - left, 1))
        if not region:
            self.set_region(None, scale)
        elif region != self.last:
            self.window.change_property(self.atom, self.cardinal, 32, region)
            self.connection.flush()
            self.last = region

    def set_rects(self, rects):
        """Set the blur region from a flat list of (x, y, w, h) integers, or clear when empty/None."""
        if not rects:
            if self.last is not None:
                self.window.delete_property(self.atom)
                self.connection.flush()
                self.last = None
            return
        if rects != self.last:
            self.window.change_property(self.atom, self.cardinal, 32, rects)
            self.connection.flush()
            self.last = list(rects)
