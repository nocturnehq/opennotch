"""GTK controls for a time-limited local file share."""
from io import BytesIO
import time

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

from .share import ShareSession, local_interface


class ShareDialog(Gtk.Dialog):
    def __init__(self, path):
        super().__init__(title="Send to phone")
        self.set_resizable(False)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.add_button("Stop sharing", Gtk.ResponseType.CLOSE)
        self.add_button("Copy link", Gtk.ResponseType.APPLY)
        self.set_default_response(Gtk.ResponseType.APPLY)

        try:
            import qrcode
        except ImportError as error:
            raise ValueError("The Python qrcode package is required to show a QR code.") from error
        self.share = ShareSession(path, local_interface())
        try:
            data = BytesIO()
            qrcode.make(self.share.url, box_size=5, border=4).save(data, format="PNG")
            loader = GdkPixbuf.PixbufLoader.new_with_type("png")
            loader.write(data.getvalue())
            loader.close()
        except (GLib.Error, OSError, ValueError):
            self.share.close()
            raise

        content = self.get_content_area()
        content.set_spacing(10)
        content.set_border_width(18)
        content.pack_start(Gtk.Image.new_from_pixbuf(loader.get_pixbuf()), False, False, 0)
        content.pack_start(Gtk.Label(label="Scan this code on your phone while it’s on the same network."),
                           False, False, 0)
        self.time_label = Gtk.Label()
        content.pack_start(self.time_label, False, False, 0)
        self.connect("response", self._response)
        self.connect("destroy", self._stop)
        self.timer = 0
        self._tick()
        self.timer = GLib.timeout_add_seconds(1, self._tick)

    def _response(self, _dialog, action):
        if action == Gtk.ResponseType.APPLY:
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            clipboard.set_text(self.share.url, -1)
            clipboard.store()
        else:
            self.destroy()

    def _tick(self):
        left = max(0, int(self.share.deadline - time.monotonic()))
        if not self.share.active:
            self.timer = 0
            self.destroy()
            return GLib.SOURCE_REMOVE
        self.time_label.set_text(f"Link expires in {left // 60}:{left % 60:02d}")
        return GLib.SOURCE_CONTINUE

    def _stop(self, _dialog):
        if self.timer:
            GLib.source_remove(self.timer)
        self.share.close()
