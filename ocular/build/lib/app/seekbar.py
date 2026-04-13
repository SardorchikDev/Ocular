from __future__ import annotations

from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent, QPaintEvent, QPainter, QPalette
from PyQt6.QtWidgets import QSizePolicy, QToolTip, QWidget

from app.theme import blend_color, format_timestamp


class PillSlider(QWidget):
    value_changed = pyqtSignal(float)
    value_committed = pyqtSignal(float)
    slider_pressed = pyqtSignal()
    slider_released = pyqtSignal()

    def __init__(self, minimum: float, maximum: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._minimum = minimum
        self._maximum = maximum
        self._value = minimum
        self._buffer_value = minimum
        self._dragging = False
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        return QSize(240, 30)

    def set_range(self, minimum: float, maximum: float) -> None:
        self._minimum = minimum
        self._maximum = max(maximum, minimum)
        self._value = min(max(self._value, self._minimum), self._maximum)
        self._buffer_value = min(max(self._buffer_value, self._minimum), self._maximum)
        self.update()

    def set_value(self, value: float) -> None:
        self._value = min(max(value, self._minimum), self._maximum)
        self.update()

    def set_buffer_value(self, value: float) -> None:
        self._buffer_value = min(max(value, self._minimum), self._maximum)
        self.update()

    def value(self) -> float:
        return self._value

    def is_dragging(self) -> bool:
        return self._dragging

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        track_rect = self._track_rect()
        painter = QPainter(self)

        border_color = blend_color(self.palette().color(QPalette.ColorRole.Mid), 180)
        buffer_color = blend_color(self.palette().color(QPalette.ColorRole.Midlight), 190)
        fill_color = self.palette().color(QPalette.ColorRole.Highlight)
        thumb_color = self.palette().color(QPalette.ColorRole.BrightText)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(border_color)
        painter.drawRect(track_rect)

        if self._buffer_fraction() > 0:
            buffered_rect = QRectF(track_rect)
            buffered_rect.setWidth(track_rect.width() * self._buffer_fraction())
            painter.setBrush(buffer_color)
            painter.drawRect(buffered_rect)

        if self._value_fraction() > 0:
            fill_rect = QRectF(track_rect)
            fill_rect.setWidth(track_rect.width() * self._value_fraction())
            painter.setBrush(fill_color)
            painter.drawRect(fill_rect)

        thumb_width = 8.0 if self._dragging else 6.0
        thumb_height = 18.0 if self._dragging else 14.0
        thumb_rect = QRectF(
            track_rect.left() + track_rect.width() * self._value_fraction() - thumb_width / 2.0,
            track_rect.center().y() - thumb_height / 2.0,
            thumb_width,
            thumb_height,
        )
        painter.setBrush(thumb_color)
        painter.drawRect(thumb_rect)
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self.slider_pressed.emit()
            self._set_from_position(event.position().x(), emit_changed=True)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging:
            self._set_from_position(event.position().x(), emit_changed=True)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self._set_from_position(event.position().x(), emit_changed=False)
            self.value_committed.emit(self._value)
            self.slider_released.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _set_from_position(self, x_pos: float, emit_changed: bool) -> None:
        self._value = self._value_from_x(x_pos)
        self.update()
        if emit_changed:
            self.value_changed.emit(self._value)

    def _track_rect(self) -> QRectF:
        return QRectF(8.0, (self.height() - 8.0) / 2.0, max(self.width() - 16.0, 0.0), 8.0)

    def _value_fraction(self) -> float:
        span = self._maximum - self._minimum
        if span <= 0:
            return 0.0
        return (self._value - self._minimum) / span

    def _buffer_fraction(self) -> float:
        span = self._maximum - self._minimum
        if span <= 0:
            return 0.0
        return (self._buffer_value - self._minimum) / span

    def _value_from_x(self, x_pos: float) -> float:
        track_rect = self._track_rect()
        span = self._maximum - self._minimum
        if track_rect.width() <= 0 or span <= 0:
            return self._minimum
        fraction = (x_pos - track_rect.left()) / track_rect.width()
        fraction = min(max(fraction, 0.0), 1.0)
        return self._minimum + span * fraction


class SeekBar(PillSlider):
    scrubbed = pyqtSignal(int)
    seek_requested = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0.0, 1.0, parent)
        self._duration_ms = 0
        self.value_changed.connect(self._emit_scrubbed)
        self.value_committed.connect(self._emit_committed)

    def set_duration(self, duration_ms: int) -> None:
        self._duration_ms = max(duration_ms, 0)
        super().set_range(0.0, float(max(self._duration_ms, 1)))

    def set_position(self, position_ms: int) -> None:
        if not self.is_dragging():
            super().set_value(float(max(position_ms, 0)))

    def preview_position(self, position_ms: int) -> None:
        super().set_value(float(max(position_ms, 0)))

    def set_buffered_position(self, buffered_ms: int) -> None:
        super().set_buffer_value(float(max(buffered_ms, 0)))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        super().mouseMoveEvent(event)
        if self._duration_ms > 0:
            hover_ms = int(self._value_from_x(event.position().x()))
            QToolTip.showText(
                event.globalPosition().toPoint(),
                format_timestamp(hover_ms),
                self,
            )

    def leaveEvent(self, event: object) -> None:
        QToolTip.hideText()
        super().leaveEvent(event)

    def _emit_scrubbed(self, value: float) -> None:
        if self._duration_ms > 0:
            self.scrubbed.emit(int(value))

    def _emit_committed(self, value: float) -> None:
        if self._duration_ms > 0:
            self.seek_requested.emit(int(value))


class VolumeBar(PillSlider):
    volume_changed = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0.0, 100.0, parent)
        self.setFixedWidth(116)
        self.value_changed.connect(self._emit_volume)
        self.value_committed.connect(self._emit_volume)

    def set_volume(self, volume: int) -> None:
        if not self.is_dragging():
            super().set_value(float(max(min(volume, 100), 0)))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        super().mouseMoveEvent(event)
        hover_value = int(round(self._value_from_x(event.position().x())))
        QToolTip.showText(
            event.globalPosition().toPoint(),
            f"{hover_value}%",
            self,
        )

    def leaveEvent(self, event: object) -> None:
        QToolTip.hideText()
        super().leaveEvent(event)

    def _emit_volume(self, value: float) -> None:
        self.volume_changed.emit(int(round(value)))
