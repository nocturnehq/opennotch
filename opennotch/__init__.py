"""OpenNotch: a Dynamic-Island-style notch for Linux (GTK 3, X11)."""
import os

__version__ = "1.0.0"

CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "opennotch")
DATA_DIR = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "opennotch")


def socket_path():
    return os.path.join(os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/opennotch-{os.getuid()}", "opennotch.sock")
