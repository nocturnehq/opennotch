"""Entry point for OpenNotch on Windows (`python -m opennotch_win`)."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .island import OpenNotchIsland


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    win = OpenNotchIsland()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
