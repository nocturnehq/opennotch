"""60 fps PySide6 (Qt6) Dynamic Island UI for OpenNotch on Windows."""
from __future__ import annotations

import math
import os
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSlider,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from . import config_win, system_win
from .media_smtc import SmtcController, TrackInfo
from .win32_glass import apply_island_win32


def fmt_time(seconds: float) -> str:
    s = max(0, int(seconds))
    if s >= 3600:
        return f"{s // 3600}:{(s // 60) % 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


def dominant_color(pm: QPixmap | None) -> QColor | None:
    if pm is None or pm.isNull():
        return None
    img = pm.toImage().scaled(6, 6)
    best, score = None, -1.0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            s = (c.saturationF() * 0.7 + c.valueF() * 0.3)
            if s > score:
                score, best = s, c
    return best


class ArtWidget(QWidget):
    """Rounded album artwork with optional dark-ringed corner play badge."""

    def __init__(self, size: int = 64, radius: int = 14, show_badge: bool = True, parent=None):
        super().__init__(parent)
        self._size = size
        self._radius = radius
        self.show_badge = show_badge
        self.active = False
        self._pixmap: QPixmap | None = None
        self.setFixedSize(size, size)

    def set_pixmap(self, pm: QPixmap | None):
        self._pixmap = pm
        self.update()

    def set_active(self, active: bool):
        if self.active != active:
            self.active = active
            self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s, r = float(self._size), float(self._radius)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, s - 1, s - 1), r, r)
        p.save()
        p.setClipPath(path)
        if self._pixmap and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                self._size, self._size,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            ox = (scaled.width() - self._size) // 2
            oy = (scaled.height() - self._size) // 2
            p.drawPixmap(0, 0, scaled, ox, oy, self._size, self._size)
        else:
            p.fillRect(self.rect(), QColor(38, 38, 41))
        p.restore()
        p.setPen(QPen(QColor(255, 255, 255, 22), 1.0))
        p.drawPath(path)

        if self.show_badge and self.active and self._size >= 48:
            bx, by, br = s - 10.0, s - 10.0, 9.0
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(15, 15, 18))
            p.drawEllipse(QPointF(bx, by), br + 1.5, br + 1.5)
            p.setBrush(QColor(34, 34, 38))
            p.drawEllipse(QPointF(bx, by), br, br)
            p.setPen(QPen(QColor(255, 255, 255, 72), 1.1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(bx, by), br - 1.5, br - 1.5)
            tri = QPainterPath()
            tri.moveTo(bx - 2.2, by - 3.2)
            tri.lineTo(bx + 3.4, by)
            tri.lineTo(bx - 2.2, by + 3.2)
            tri.closeSubpath()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 235))
            p.drawPath(tri)


class EqualiserWidget(QWidget):
    """60 fps fluid Dynamic Island visualizer (bars | pixels | dots)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = "bars"
        self.color = QColor(255, 255, 255)
        self._phase = 0.0
        self._amps = [0.22] * 5
        self._running = False
        self._last = time.monotonic()
        self.setFixedSize(26, 16)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._step)

    def set_running(self, on: bool):
        self._running = on
        if on and not self._timer.isActive():
            self._last = time.monotonic()
            self._timer.start()
        elif not on and self._timer.isActive():
            self._timer.stop()
        self.update()

    def _step(self):
        now = time.monotonic()
        dt = min(0.05, max(0.0, now - self._last))
        self._last = now
        self._phase += dt * 5.0
        freqs = (0.95, 1.32, 1.08, 1.44, 0.88)
        offsets = (0.0, 1.3, 2.5, 3.8, 5.1)
        weights = (0.72, 0.94, 1.0, 0.92, 0.70)
        for i in range(5):
            w1 = math.sin(self._phase * freqs[i] + offsets[i])
            w2 = math.sin(self._phase * (freqs[i] * 1.85 + 0.25) + offsets[i] * 1.6)
            target = (0.18 + 0.82 * (0.5 + 0.32 * w1 + 0.18 * w2)) * weights[i]
            self._amps[i] += (target - self._amps[i]) * min(1.0, dt * 14.0)
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        cy = 8.0
        if self.mode == "pixels":
            bar_w, gap = 2.6, 2.0
            x0 = (self.width() - (5 * bar_w + 4 * gap)) / 2.0
            for i in range(5):
                amp = self._amps[i] if self._running else 0.22
                rows = max(1, round(4.4 * amp))
                x = x0 + i * (bar_w + gap)
                for j in range(rows):
                    c = QColor(self.color)
                    c.setAlphaF(0.52 + 0.48 * (j / max(1, rows - 1)) if rows > 1 else 0.78)
                    p.setBrush(c)
                    p.drawRoundedRect(QRectF(x, 14.6 - (j + 1) * 3.1, bar_w, 2.3), 0.8, 0.8)
        elif self.mode == "dots":
            gap = 5.4
            x0 = (self.width() - 3 * gap) / 2.0
            for i in range(4):
                wave = math.sin(self._phase * 1.15 - i * 0.95) if self._running else 0.0
                c = QColor(self.color)
                c.setAlphaF(0.68 + 0.32 * (0.5 + 0.5 * wave))
                p.setBrush(c)
                p.drawEllipse(QPointF(x0 + i * gap, cy + wave * 3.6), 1.85 + 0.35 * (0.5 + 0.5 * wave), 1.85 + 0.35 * (0.5 + 0.5 * wave))
        else:
            bar_w, gap = 2.4, 2.2
            x0 = (self.width() - (5 * bar_w + 4 * gap)) / 2.0
            for i in range(5):
                amp = self._amps[i] if self._running else 0.22
                bh = max(3.0, 14.4 * amp)
                x = x0 + i * (bar_w + gap)
                c = QColor(self.color)
                c.setAlphaF(0.78 + 0.22 * amp)
                p.setBrush(c)
                p.drawRoundedRect(QRectF(x, cy - bh / 2.0, bar_w, bh), bar_w / 2.0, bar_w / 2.0)


class TransportIcon(QWidget):
    """Crisp SF-Symbols-style vector Play / Pause / Prev / Next button."""

    clicked = Signal()

    def __init__(self, kind: str, size: int = 34, parent=None):
        super().__init__(parent)
        self.kind = kind
        self._hover = False
        self._pressed = False
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_kind(self, kind: str):
        if self.kind != kind:
            self.kind = kind
            self.update()

    def enterEvent(self, _ev):
        self._hover = True
        self.update()

    def leaveEvent(self, _ev):
        self._hover = False
        self._pressed = False
        self.update()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton and self._pressed:
            self._pressed = False
            self.update()
            if self.rect().contains(ev.position().toPoint()):
                self.clicked.emit()

    @staticmethod
    def _rounded_tri(pts: list[tuple[float, float]], r: float) -> QPainterPath:
        path = QPainterPath()
        for i in range(3):
            p_prev, p_cur, p_next = pts[(i - 1) % 3], pts[i], pts[(i + 1) % 3]
            v1x, v1y = p_prev[0] - p_cur[0], p_prev[1] - p_cur[1]
            v2x, v2y = p_next[0] - p_cur[0], p_next[1] - p_cur[1]
            l1, l2 = math.hypot(v1x, v1y) or 1.0, math.hypot(v2x, v2y) or 1.0
            d = min(r, l1 * 0.35, l2 * 0.35)
            ax, ay = p_cur[0] + v1x / l1 * d, p_cur[1] + v1y / l1 * d
            bx, by = p_cur[0] + v2x / l2 * d, p_cur[1] + v2y / l2 * d
            if i == 0:
                path.moveTo(ax, ay)
            else:
                path.lineTo(ax, ay)
            path.quadTo(p_cur[0], p_cur[1], bx, by)
        path.closeSubpath()
        return path

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() / 2.0, self.height() / 2.0
        p.setPen(Qt.PenStyle.NoPen)
        if self._hover:
            p.setBrush(QColor(255, 255, 255, 24))
            p.drawEllipse(QPointF(cx, cy), min(cx, cy) * 0.94, min(cx, cy) * 0.94)
        p.translate(cx, cy)
        scale = 0.90 if self._pressed else (1.04 if self._hover else 1.0)
        p.scale(scale, scale)
        if self.kind in ("play", "pause"):
            p.setBrush(QColor(255, 255, 255, 255 if self._hover else 242))
            if self.kind == "play":
                p.drawPath(self._rounded_tri([(-7.0, -9.8), (10.5, 0.0), (-7.0, 9.8)], 2.8))
            else:
                p.drawRoundedRect(QRectF(-7.8, -9.5, 5.4, 19.0), 2.5, 2.5)
                p.drawRoundedRect(QRectF(2.4, -9.5, 5.4, 19.0), 2.5, 2.5)
        else:
            p.setBrush(QColor(255, 255, 255, 248 if self._hover else 130))
            sgn = -1.0 if self.kind == "prev" else 1.0
            for ox in (-4.8 * sgn, 4.2 * sgn):
                pts = [(ox - 5.2 * sgn, -6.2), (ox + 5.6 * sgn, 0.0), (ox - 5.2 * sgn, 6.2)]
                p.drawPath(self._rounded_tri(pts, 1.9))


class ScrubBarWidget(QWidget):
    """60 fps Glass / Comet / Wave progress bar with hover expand and floating scrub tooltip."""

    seeked = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.style_mode = "comet"  # pill | comet | wave
        self.accent = QColor(255, 255, 255)
        self.duration = 0.0
        self.position = 0.0
        self._playing = False
        self._hover = False
        self._drag = False
        self._hover_x = 0.0
        self._ht = 0.0
        self._phase = 0.0
        self._last = time.monotonic()
        self.setFixedHeight(22)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._step)

    def set_playing(self, on: bool):
        self._playing = on
        self._sync_timer()

    def set_track_pos(self, pos: float, dur: float):
        if not self._drag:
            self.position = max(0.0, pos)
            self.duration = max(0.0, dur)
            self._last = time.monotonic()
            self.update()

    def _sync_timer(self):
        need = self._playing or self._hover or self._drag or (self._ht > 0.01)
        if need and not self._timer.isActive():
            self._last = time.monotonic()
            self._timer.start()
        elif not need and self._timer.isActive():
            self._timer.stop()

    def _step(self):
        now = time.monotonic()
        dt = min(0.05, max(0.0, now - self._last))
        self._last = now
        if self._playing and not self._drag and self.duration > 0:
            self.position = min(self.duration, self.position + dt)
            self._phase += dt * 5.0
        target = 1.0 if (self._hover or self._drag) else 0.0
        self._ht += (target - self._ht) * min(1.0, dt * 14.0)
        if abs(target - self._ht) < 0.01:
            self._ht = target
        self.update()
        self._sync_timer()

    def enterEvent(self, ev):
        self._hover = True
        self._hover_x = ev.position().x()
        self._sync_timer()

    def leaveEvent(self, _ev):
        self._hover = False
        self._sync_timer()

    def _emit_at(self, x: float):
        if self.duration <= 0:
            return
        pad = 4.0
        frac = max(0.0, min(1.0, (x - pad) / max(1.0, self.width() - 2 * pad)))
        self.position = frac * self.duration
        self.seeked.emit(self.position)
        self.update()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton and self.duration > 0:
            self._drag = True
            self._hover_x = ev.position().x()
            self._emit_at(self._hover_x)
            self._sync_timer()

    def mouseMoveEvent(self, ev):
        self._hover_x = ev.position().x()
        if self._drag:
            self._emit_at(self._hover_x)
        else:
            self.update()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag = False
            self._sync_timer()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        pad = 4.0 if self.style_mode in ("comet", "wave") else 2.0
        span = max(1.0, w - 2 * pad)
        ht = self._ht if self.duration > 0 else 0.0
        frac = max(0.0, min(1.0, self.position / self.duration)) if self.duration > 0 else 0.0
        fill_w = span * frac
        x_now = pad + fill_w
        ar, ag, ab = self.accent.red(), self.accent.green(), self.accent.blue()

        if self.style_mode == "comet":
            bar_h = 3.0 + 2.4 * ht
            cy = h - 6.0
            by = cy - bar_h / 2.0
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, int(36 + 20 * ht)))
            p.drawRoundedRect(QRectF(pad, by, span, bar_h), bar_h / 2.0, bar_h / 2.0)
            if fill_w > 0.5:
                tail = QLinearGradient(pad, 0, max(pad + 1.0, x_now), 0)
                tail.setColorAt(0.0, QColor(ar, ag, ab, 26))
                tail.setColorAt(0.65, QColor(ar, ag, ab, 135))
                tail.setColorAt(1.0, QColor(ar, ag, ab, 255))
                p.setPen(QPen(QBrush(tail), bar_h, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(pad, cy), QPointF(x_now, cy))
                glow_r = 7.5 + 2.5 * ht
                glow = QRadialGradient(QPointF(x_now, cy), glow_r)
                glow.setColorAt(0.0, QColor(ar, ag, ab, 110))
                glow.setColorAt(0.55, QColor(ar, ag, ab, 36))
                glow.setColorAt(1.0, QColor(ar, ag, ab, 0))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(glow)
                p.drawEllipse(QPointF(x_now, cy), glow_r, glow_r)
                p.setBrush(QColor(255, 255, 255))
                p.drawEllipse(QPointF(x_now, cy), 3.0 + 1.1 * ht, 3.0 + 1.1 * ht)
        elif self.style_mode == "wave":
            bar_h = 2.6 + 1.2 * ht
            cy = h - 7.0
            by = cy - bar_h / 2.0
            p.setPen(QPen(QColor(255, 255, 255, int(38 + 20 * ht)), bar_h, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(min(w - pad, x_now + 5.0), cy), QPointF(w - pad, cy))
            if fill_w > 2.0:
                amp_max = 2.6 + 0.6 * ht
                path = QPainterPath(QPointF(pad, cy))
                x = pad + 1.5
                while x <= x_now:
                    u = (x - pad) / max(1.0, fill_w)
                    env = min(1.0, u * 8.0) * min(1.0, (1.0 - u) * 10.0)
                    y = cy + amp_max * env * math.sin((x - pad) / 5.4 - self._phase)
                    path.lineTo(x, y)
                    x += 1.5
                path.lineTo(x_now, cy)
                grad = QLinearGradient(pad, 0, x_now, 0)
                grad.setColorAt(0.0, QColor(ar, ag, ab, 140))
                grad.setColorAt(1.0, QColor(ar, ag, ab, 255))
                p.setPen(QPen(QBrush(grad), bar_h, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(path)
                tw, th = 3.4 + 0.8 * ht, 10.5 + 2.5 * ht
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255))
                p.drawRoundedRect(QRectF(x_now - tw / 2.0, cy - th / 2.0, tw, th), tw / 2.0, tw / 2.0)
        else:
            bar_h = 4.5 + 3.5 * ht
            cy = h - 6.0
            by = cy - bar_h / 2.0
            track = QPainterPath()
            track.addRoundedRect(QRectF(pad, by, span, bar_h), bar_h / 2.0, bar_h / 2.0)
            p.fillPath(track, QColor(255, 255, 255, int(33 + 20 * ht)))
            p.setPen(QPen(QColor(255, 255, 255, int(18 + 16 * ht)), 0.75))
            p.drawPath(track)
            if fill_w > 0.5:
                p.save()
                p.setClipPath(track)
                fg = QLinearGradient(0, by, 0, by + bar_h)
                fg.setColorAt(0.0, QColor(ar, ag, ab, 250))
                fg.setColorAt(0.55, QColor(ar, ag, ab, int(220 + 25 * ht)))
                fg.setColorAt(1.0, QColor(ar, ag, ab, int(185 + 40 * ht)))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(fg)
                p.drawRoundedRect(QRectF(pad, by, max(bar_h, fill_w), bar_h), bar_h / 2.0, bar_h / 2.0)
                p.restore()

        if ht > 0.05 and self.duration > 0:
            hx = max(pad, min(pad + span, self._hover_x))
            txt = fmt_time(((hx - pad) / span) * self.duration)
            f = QFont("Segoe UI", 8)
            f.setBold(True)
            p.setFont(f)
            fm = QFontMetrics(f)
            pw, ph = fm.horizontalAdvance(txt) + 12.0, 15.0
            px = max(pad, min(w - pad - pw, hx - pw / 2.0))
            py = max(0.0, by - ph - 3.0)
            p.setPen(QPen(QColor(255, 255, 255, int(52 * ht)), 0.8))
            p.setBrush(QColor(24, 24, 28, int(235 * ht)))
            p.drawRoundedRect(QRectF(px, py, pw, ph), 7.0, 7.0)
            p.setPen(QColor(255, 255, 255, int(245 * ht)))
            p.drawText(QRectF(px, py, pw, ph), Qt.AlignmentFlag.AlignCenter, txt)


class SettingsDialog(QDialog):
    def __init__(self, cfg: dict, on_change, parent=None):
        super().__init__(parent)
        self.cfg = dict(cfg)
        self._on_change = on_change
        self.setWindowTitle("OpenNotch Settings")
        self.setFixedWidth(360)
        self.setStyleSheet(
            "QDialog { background: #141416; color: #f5f5f7; font-family: 'Segoe UI'; }"
            "QLabel { color: #d8d8dc; }"
            "QComboBox { background: #232327; color: #ffffff; border: 1px solid #35353a; border-radius: 6px; padding: 5px 8px; }"
            "QCheckBox { color: #e8e8ec; spacing: 8px; }"
        )
        form = QFormLayout(self)
        form.setSpacing(12)

        def combo(key, items):
            cb = QComboBox()
            for val, label in items:
                cb.addItem(label, val)
            idx = cb.findData(self.cfg[key])
            if idx >= 0:
                cb.setCurrentIndex(idx)
            cb.currentIndexChanged.connect(lambda *_: self._set(key, cb.currentData()))
            return cb

        def check(key, text):
            c = QCheckBox(text)
            c.setChecked(bool(self.cfg[key]))
            c.toggled.connect(lambda v: self._set(key, bool(v)))
            return c

        form.addRow("Shape", combo("shape", [("island", "Island (floating)"), ("notch", "Notch (attached)")]))
        form.addRow("Progress bar", combo("progress", [("pill", "Glass"), ("comet", "Comet"), ("wave", "Wave")]))
        form.addRow("Visualizer", combo("visualizer", [("bars", "Bars"), ("pixels", "Pixels"), ("dots", "Dots")]))
        form.addRow("Music background", combo("music_background", [("album", "Album colours"), ("black", "Black")]))
        form.addRow("", check("music_volume", "Music bar volume slider"))
        form.addRow("", check("music_art_badge", "Artwork corner badge"))
        form.addRow("", check("autostart", "Run at Windows startup"))

    def _set(self, key: str, value):
        self.cfg[key] = value
        if key == "autostart":
            config_win.set_windows_autostart(bool(value))
        saved = config_win.save(self.cfg)
        self._on_change(saved)


class OpenNotchIsland(QWidget):
    """Main frameless Dynamic Island window for Windows 10/11."""

    track_signal = Signal(object)

    PILL_SIZE = (164, 34)
    TAB_SIZES = {
        "music": (440, 152),
        "overview": (480, 210),
        "controls": (440, 185),
        "clipboard": (440, 200),
        "shelf": (440, 180),
    }

    def __init__(self):
        super().__init__()
        self.cfg = config_win.load()
        self.state = "pill"  # pill | card
        self.current_tab = "music"
        self.track: TrackInfo | None = None
        self.art_color: QColor | None = None
        self.sys_stats = system_win.SysStats()
        self.clip_items: list[str] = []
        self.shelf_files: list[str] = []
        self._pomo_left = self.cfg["focus_minutes"] * 60
        self._pomo_running = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAcceptDrops(True)

        self._cur_w, self._cur_h = float(self.PILL_SIZE[0]), float(self.PILL_SIZE[1])
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(240)
        self._anim.setEasingCurve(QEasingCurve.Type.OutBack)
        self._anim.valueChanged.connect(self._on_anim_val)

        self._build_ui()
        self._apply_cfg(self.cfg)
        self._reposition()

        # Connect SMTC
        self.track_signal.connect(self._on_track)
        self.smtc = SmtcController(lambda info: self.track_signal.emit(info))
        self.smtc.start()

        # Clipboard watcher
        cb = QApplication.clipboard()
        cb.dataChanged.connect(self._on_clipboard)

        # Hover poll (works even when unfocused) & 1s stats/pomo tick
        self._hover_timer = QTimer(self)
        self._hover_timer.setInterval(120)
        self._hover_timer.timeout.connect(self._poll_hover)
        self._hover_timer.start()

        self._tick_1s = QTimer(self)
        self._tick_1s.setInterval(1000)
        self._tick_1s.timeout.connect(self._on_1s_tick)
        self._tick_1s.start()

        self._setup_tray()

    def showEvent(self, ev):
        super().showEvent(ev)
        apply_island_win32(int(self.winId()))

    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        pm = QPixmap(32, 32)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(18, 18, 20))
        p.setPen(QPen(QColor(255, 255, 255, 210), 2.0))
        p.drawRoundedRect(3, 9, 26, 14, 7, 7)
        p.end()
        self.tray = QSystemTrayIcon(pm, self)
        self.tray.setToolTip("OpenNotch")
        menu = QMenu()
        menu.addAction("Open Settings", self._open_settings)
        menu.addAction("Quit OpenNotch", QApplication.quit)
        self.tray.setContextMenu(menu)
        self.tray.show()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 6, 14, 10)
        root.setSpacing(6)

        self.root_stack = QStackedWidget()
        root.addWidget(self.root_stack)

        # --- Page 0: Idle Pill
        pill_w = QWidget()
        pl = QHBoxLayout(pill_w)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(8)
        self.pill_art = ArtWidget(22, 6, show_badge=False)
        self.pill_art.hide()
        self.pill_clock = QLabel(datetime.now().strftime("%H:%M"))
        self.pill_clock.setStyleSheet("color: rgba(255,255,255,0.78); font: 600 11px 'Segoe UI';")
        self.pill_eq = EqualiserWidget()
        self.pill_eq.hide()
        pl.addWidget(self.pill_art)
        pl.addStretch(1)
        pl.addWidget(self.pill_clock)
        pl.addStretch(1)
        pl.addWidget(self.pill_eq)
        self.root_stack.addWidget(pill_w)

        # --- Page 1: Expanded Card
        card_w = QWidget()
        cl = QVBoxLayout(card_w)
        cl.setContentsMargins(0, 2, 0, 2)
        cl.setSpacing(8)

        # Top tab bar
        tabs_row = QHBoxLayout()
        tabs_row.setSpacing(6)
        tabs_row.addStretch(1)
        self._tab_btns: dict[str, QPushButton] = {}
        for key, label in (("music", "♫"), ("overview", "⊞"), ("controls", "☰"), ("clipboard", "📋"), ("shelf", "📁")):
            b = QPushButton(label)
            b.setFixedSize(30, 24)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self._select_tab(k))
            self._tab_btns[key] = b
            tabs_row.addWidget(b)
        gear = QPushButton("⚙")
        gear.setFixedSize(28, 24)
        gear.setCursor(Qt.CursorShape.PointingHandCursor)
        gear.setStyleSheet("QPushButton { background: transparent; color: rgba(255,255,255,0.55); border: none; font-size: 13px; }"
                           "QPushButton:hover { color: #ffffff; }")
        gear.clicked.connect(self._open_settings)
        tabs_row.addWidget(gear)
        tabs_row.addStretch(1)
        cl.addLayout(tabs_row)

        self.pages = QStackedWidget()
        cl.addWidget(self.pages)

        # Tab: Music (1-to-1 with OpenNotch Linux / NotchPixel)
        music_w = QWidget()
        ml = QVBoxLayout(music_w)
        ml.setContentsMargins(2, 0, 2, 0)
        ml.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(14)
        self.art = ArtWidget(64, 14, show_badge=True)
        top.addWidget(self.art)
        meta = QVBoxLayout()
        meta.setSpacing(2)
        meta.addStretch(1)
        self.m_title = QLabel("Nothing playing")
        self.m_title.setStyleSheet("color: #ffffff; font: 700 15px 'Segoe UI';")
        self.m_artist = QLabel("Start a player to see it here")
        self.m_artist.setStyleSheet("color: rgba(255,255,255,0.52); font: 500 12px 'Segoe UI';")
        meta.addWidget(self.m_title)
        meta.addWidget(self.m_artist)
        meta.addStretch(1)
        top.addLayout(meta, 1)

        trans = QHBoxLayout()
        trans.setSpacing(6)
        self.b_prev = TransportIcon("prev", 32)
        self.b_play = TransportIcon("play", 38)
        self.b_next = TransportIcon("next", 32)
        self.b_prev.clicked.connect(lambda: self.smtc.prev_track())
        self.b_play.clicked.connect(lambda: self.smtc.play_pause())
        self.b_next.clicked.connect(lambda: self.smtc.next_track())
        for b in (self.b_prev, self.b_play, self.b_next):
            trans.addWidget(b)
        top.addLayout(trans)
        ml.addLayout(top)

        self.seek = ScrubBarWidget()
        self.seek.seeked.connect(lambda s: self.smtc.seek(s))
        ml.addWidget(self.seek)

        foot = QHBoxLayout()
        self.m_pos = QLabel("0:00")
        self.m_len = QLabel("-0:00")
        ts_css = "color: rgba(255,255,255,0.60); font: 600 11px 'Segoe UI';"
        self.m_pos.setStyleSheet(ts_css)
        self.m_len.setStyleSheet(ts_css)
        self.m_vol = QSlider(Qt.Orientation.Horizontal)
        self.m_vol.setRange(0, 100)
        self.m_vol.setFixedWidth(110)
        self.m_vol.valueChanged.connect(lambda v: system_win.set_volume(v))
        foot.addWidget(self.m_pos)
        foot.addStretch(1)
        foot.addWidget(self.m_vol)
        foot.addStretch(1)
        foot.addWidget(self.m_len)
        ml.addLayout(foot)
        self.pages.addWidget(music_w)

        # Tab: Overview
        ov_w = QWidget()
        ovl = QVBoxLayout(ov_w)
        ovl.setSpacing(8)
        self.ov_date = QLabel(datetime.now().strftime("%A, %B %d"))
        self.ov_date.setStyleSheet("color: #ffffff; font: 700 15px 'Segoe UI';")
        self.ov_stats = QLabel("CPU 0%   RAM 0%   ↓ 0 B/s")
        self.ov_stats.setStyleSheet("color: rgba(255,255,255,0.68); font: 600 12px 'Segoe UI';")
        pomo_row = QHBoxLayout()
        self.ov_pomo = QLabel(f"Focus  {fmt_time(self._pomo_left)}")
        self.ov_pomo.setStyleSheet("color: #ffffff; font: 600 13px 'Segoe UI';")
        pomo_btn = QPushButton("Start / Pause")
        pomo_btn.setStyleSheet("QPushButton { background: #ffffff; color: #0b0b0c; border-radius: 9px; padding: 4px 12px; font-weight: 600; }")
        pomo_btn.clicked.connect(self._toggle_pomo)
        pomo_row.addWidget(self.ov_pomo)
        pomo_row.addStretch(1)
        pomo_row.addWidget(pomo_btn)
        ovl.addWidget(self.ov_date)
        ovl.addWidget(self.ov_stats)
        ovl.addLayout(pomo_row)
        ovl.addStretch(1)
        self.pages.addWidget(ov_w)

        # Tab: Controls
        ctl_w = QWidget()
        ctll = QVBoxLayout(ctl_w)
        ctll.setSpacing(10)
        self.c_vol = QSlider(Qt.Orientation.Horizontal)
        self.c_vol.setRange(0, 100)
        self.c_vol.valueChanged.connect(lambda v: system_win.set_volume(v))
        self.c_bri = QSlider(Qt.Orientation.Horizontal)
        self.c_bri.setRange(5, 100)
        self.c_bri.valueChanged.connect(lambda v: system_win.set_brightness(v))
        for title, sl in (("Volume", self.c_vol), ("Brightness", self.c_bri)):
            lb = QLabel(title)
            lb.setStyleSheet("color: rgba(255,255,255,0.65); font: 600 11px 'Segoe UI';")
            ctll.addWidget(lb)
            ctll.addWidget(sl)
        ctll.addStretch(1)
        self.pages.addWidget(ctl_w)

        # Tab: Clipboard
        clip_w = QWidget()
        clipl = QVBoxLayout(clip_w)
        self.clip_list = QListWidget()
        self.clip_list.setStyleSheet("QListWidget { background: transparent; border: none; color: #f5f5f7; }"
                                     "QListWidget::item { padding: 5px; border-radius: 8px; }"
                                     "QListWidget::item:hover { background: rgba(255,255,255,0.09); }")
        self.clip_list.itemClicked.connect(lambda it: QApplication.clipboard().setText(it.text()))
        clipl.addWidget(self.clip_list)
        self.pages.addWidget(clip_w)

        # Tab: Shelf
        shelf_w = QWidget()
        shelfl = QVBoxLayout(shelf_w)
        self.shelf_list = QListWidget()
        self.shelf_list.setStyleSheet(self.clip_list.styleSheet())
        self.shelf_list.addItem("Drop files onto the island to pin them here")
        self.shelf_list.itemClicked.connect(self._open_shelf_item)
        shelfl.addWidget(self.shelf_list)
        self.pages.addWidget(shelf_w)

        self.root_stack.addWidget(card_w)
        self._select_tab("music", animate=False)

    def _apply_cfg(self, cfg: dict):
        self.cfg = cfg
        self.seek.style_mode = cfg["progress"]
        self.seek.accent = QColor(cfg["accent"])
        self.pill_eq.mode = cfg["visualizer"]
        self.art.show_badge = cfg["music_art_badge"]
        self.m_vol.setVisible(cfg["music_volume"])
        self.art.update()
        self.seek.update()
        self.pill_eq.update()
        self._reposition()
        self.update()

    def _select_tab(self, name: str, animate: bool = True):
        self.current_tab = name
        idx = list(self.TAB_SIZES.keys()).index(name)
        self.pages.setCurrentIndex(idx)
        for k, b in self._tab_btns.items():
            if k == name:
                b.setStyleSheet("QPushButton { background: #ffffff; color: #0b0b0c; border-radius: 11px; border: none; font-weight: 700; }")
            else:
                b.setStyleSheet("QPushButton { background: transparent; color: rgba(255,255,255,0.55); border-radius: 11px; border: none; }"
                                "QPushButton:hover { color: #ffffff; background: rgba(255,255,255,0.10); }")
        if name == "controls":
            v, _ = system_win.get_volume()
            self.c_vol.blockSignals(True)
            self.c_vol.setValue(v)
            self.c_vol.blockSignals(False)
            bri = system_win.get_brightness()
            if bri is not None:
                self.c_bri.blockSignals(True)
                self.c_bri.setValue(bri)
                self.c_bri.blockSignals(False)
        if self.state == "card" and animate:
            w, h = self.TAB_SIZES[name]
            self._morph_to(w, h)

    def _morph_to(self, tw: int, th: int):
        self._start_sz = (self._cur_w, self._cur_h)
        self._end_sz = (float(tw), float(th))
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def _on_anim_val(self, t: float):
        sw, sh = self._start_sz
        ew, eh = self._end_sz
        self._cur_w = sw + (ew - sw) * t
        self._cur_h = sh + (eh - sh) * t
        self._reposition()
        self.update()

    def _reposition(self):
        screen = QGuiApplication.primaryScreen()
        geo = screen.geometry() if screen else QRectF(0, 0, 1920, 1080).toRect()
        w, h = max(120, int(round(self._cur_w))), max(30, int(round(self._cur_h)))
        y = geo.y() + (self.cfg["top_gap"] if self.cfg["shape"] == "island" else 0)
        x = geo.x() + (geo.width() - w) // 2
        self.setGeometry(x, y, w, h)

    def _set_state(self, state: str):
        if self.state == state:
            return
        self.state = state
        if state == "card":
            self.root_stack.setCurrentIndex(1)
            w, h = self.TAB_SIZES[self.current_tab]
            self._morph_to(w, h)
        else:
            self.root_stack.setCurrentIndex(0)
            self._morph_to(*self.PILL_SIZE)
        playing = bool(self.track and self.track.status == "Playing")
        self.pill_eq.set_running(playing and state == "pill")
        self.seek.set_playing(playing and state == "card" and self.current_tab == "music")

    def _poll_hover(self):
        pos = QCursor.pos()
        rect = self.geometry().adjusted(-8, -8, 8, 8)
        inside = rect.contains(pos)
        if inside and self.state == "pill":
            self._set_state("card")
        elif not inside and self.state == "card" and not self.seek._drag:
            self._set_state("pill")

    def _on_track(self, info: TrackInfo | None):
        self.track = info
        playing = bool(info and info.status == "Playing")
        if info:
            self.m_title.setText(info.title)
            self.m_artist.setText(info.artist)
            self.m_artist.setVisible(bool(info.artist))
            self.art.set_active(True)
            self.seek.set_track_pos(info.position_s, info.duration_s)
            self.m_pos.setText(fmt_time(info.position_s))
            rem = max(0.0, info.duration_s - info.position_s)
            self.m_len.setText("-" + fmt_time(rem) if info.duration_s > 0 else "LIVE")
            pm = QPixmap()
            if info.art_bytes and pm.loadFromData(info.art_bytes):
                self.art.set_pixmap(pm)
                self.pill_art.set_pixmap(pm)
                self.art_color = dominant_color(pm)
                if self.art_color:
                    c = self.art_color
                    self.pill_eq.color = QColor(
                        int(90 + 0.65 * c.red()),
                        int(90 + 0.65 * c.green()),
                        int(90 + 0.65 * c.blue()),
                    )
            else:
                self.art.set_pixmap(None)
                self.pill_art.set_pixmap(None)
                self.art_color = None
                self.pill_eq.color = QColor(self.cfg["accent"])
        else:
            self.m_title.setText("Nothing playing")
            self.m_artist.setText("Start a player to see it here")
            self.m_artist.setVisible(True)
            self.art.set_active(False)
            self.art.set_pixmap(None)
            self.pill_art.set_pixmap(None)
            self.art_color = None
            self.seek.set_track_pos(0, 0)
            self.m_pos.setText("0:00")
            self.m_len.setText("-0:00")

        self.b_play.set_kind("pause" if playing else "play")
        self.pill_art.setVisible(playing)
        self.pill_eq.setVisible(playing)
        self.pill_clock.setVisible(not playing)
        self.pill_eq.set_running(playing and self.state == "pill")
        self.seek.set_playing(playing and self.state == "card" and self.current_tab == "music")
        self.update()

    def _on_1s_tick(self):
        self.pill_clock.setText(datetime.now().strftime("%H:%M"))
        if self._pomo_running and self._pomo_left > 0:
            self._pomo_left -= 1
            self.ov_pomo.setText(f"Focus  {fmt_time(self._pomo_left)}")
        if self.state == "card" and self.current_tab == "overview":
            st = self.sys_stats.sample()
            batt = f"   BAT {st['battery']}%" if st["battery"] is not None else ""
            self.ov_stats.setText(f"CPU {st['cpu']:.0f}%   RAM {st['ram']:.0f}%{batt}   ↓ {system_win.fmt_bps(st['down_bps'])}")
        if self.track and self.track.status == "Playing" and self.track.duration_s > 0:
            self.m_pos.setText(fmt_time(self.seek.position))
            self.m_len.setText("-" + fmt_time(max(0.0, self.track.duration_s - self.seek.position)))

    def _toggle_pomo(self):
        self._pomo_running = not self._pomo_running

    def _on_clipboard(self):
        txt = (QApplication.clipboard().text() or "").strip()
        if txt and (not self.clip_items or self.clip_items[0] != txt):
            self.clip_items.insert(0, txt)
            self.clip_items = self.clip_items[:20]
            self.clip_list.clear()
            for item in self.clip_items:
                self.clip_list.addItem(QListWidgetItem(item[:120]))

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()
            self._select_tab("shelf")
            self._set_state("card")

    def dropEvent(self, ev):
        for url in ev.mimeData().urls():
            path = url.toLocalFile()
            if path and path not in self.shelf_files:
                self.shelf_files.insert(0, path)
        self.shelf_list.clear()
        for f in self.shelf_files:
            it = QListWidgetItem(Path(f).name)
            it.setData(Qt.ItemDataRole.UserRole, f)
            self.shelf_list.addItem(it)

    def _open_shelf_item(self, item: QListWidgetItem):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and os.path.exists(path):
            try:
                os.startfile(path)  # type: ignore[attr-defined]
            except Exception:
                pass

    def _open_settings(self):
        dlg = SettingsDialog(self.cfg, self._apply_cfg, self)
        dlg.exec()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = float(min(self.height() / 2.0, 22.0 if self.state == "card" else self.height() / 2.0))
        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        path = QPainterPath()
        if self.cfg["shape"] == "notch":
            path.moveTo(0.5, 0.5)
            path.lineTo(self.width() - 0.5, 0.5)
            path.lineTo(self.width() - 0.5, self.height() - r)
            path.quadTo(self.width() - 0.5, self.height() - 0.5, self.width() - r, self.height() - 0.5)
            path.lineTo(r, self.height() - 0.5)
            path.quadTo(0.5, self.height() - 0.5, 0.5, self.height() - r)
            path.closeSubpath()
        else:
            path.addRoundedRect(rect, r, r)

        p.save()
        p.setClipPath(path)
        p.fillRect(self.rect(), QColor(12, 12, 14, 238))
        # Subtle ambient album-art glow on Music card
        if self.state == "card" and self.current_tab == "music" and self.cfg["music_background"] == "album" and self.art_color:
            glow = QRadialGradient(QPointF(60, 75), 240)
            c = QColor(self.art_color)
            c.setAlpha(68)
            glow.setColorAt(0.0, c)
            glow.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.fillRect(self.rect(), glow)
        p.restore()
        p.setPen(QPen(QColor(255, 255, 255, 28), 1.0))
        p.drawPath(path)
