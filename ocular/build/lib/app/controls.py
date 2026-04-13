from __future__ import annotations

from PyQt6.QtCore import QSignalBlocker, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QToolButton, QWidget

from app.player import PLAYBACK_SPEEDS
from app.seekbar import SeekBar, VolumeBar
from app.theme import ThemeManager, format_timestamp, render_svg_icon


class IconToolButton(QToolButton):
    def __init__(
        self,
        theme_manager: ThemeManager,
        icon_name: str,
        *,
        object_name: str = "",
        size: int = 18,
        button_size: int = 38,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme_manager = theme_manager
        self._icon_name = icon_name
        self._icon_size = size
        if object_name:
            self.setObjectName(object_name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAutoRaise(True)
        self.setFixedSize(button_size, button_size)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._theme_manager.theme_changed.connect(self.refresh_icon)
        self.refresh_icon()

    def set_icon_name(self, icon_name: str) -> None:
        self._icon_name = icon_name
        self.refresh_icon()

    def refresh_icon(self, _theme_name: str | None = None) -> None:
        del _theme_name
        icon_color = self.palette().color(QPalette.ColorRole.WindowText)
        self.setIcon(render_svg_icon(self._icon_name, icon_color, self._icon_size))
        self.setIconSize(self.icon().actualSize(self.size()))


class PlaybackControls(QWidget):
    toggle_playback_requested = pyqtSignal()
    previous_requested = pyqtSignal()
    next_requested = pyqtSignal()
    seek_relative_requested = pyqtSignal(int)
    scrub_requested = pyqtSignal(int)
    seek_requested = pyqtSignal(int)
    volume_requested = pyqtSignal(int)
    mute_requested = pyqtSignal()
    fullscreen_requested = pyqtSignal()
    speed_requested = pyqtSignal(float)

    def __init__(self, theme_manager: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme_manager = theme_manager
        self._duration_ms = 0
        self._position_ms = 0
        self._buffered_ms = 0
        self._is_playing = False
        self._is_muted = False
        self._is_fullscreen = False
        self._auto_hide_enabled = False

        self.setObjectName("ControlsBar")
        self.setMouseTracking(True)

        self.previous_button = IconToolButton(
            theme_manager,
            "previous",
            object_name="TransportButton",
            size=18,
            button_size=38,
            parent=self,
        )
        self.rewind_button = IconToolButton(
            theme_manager,
            "rewind",
            object_name="TransportButton",
            size=18,
            button_size=38,
            parent=self,
        )
        self.play_button = IconToolButton(
            theme_manager,
            "play",
            object_name="PrimaryTransportButton",
            size=20,
            button_size=44,
            parent=self,
        )
        self.forward_button = IconToolButton(
            theme_manager,
            "forward",
            object_name="TransportButton",
            size=18,
            button_size=38,
            parent=self,
        )
        self.next_button = IconToolButton(
            theme_manager,
            "next",
            object_name="TransportButton",
            size=18,
            button_size=38,
            parent=self,
        )
        self.mute_button = IconToolButton(
            theme_manager,
            "volume",
            object_name="TransportButton",
            size=18,
            button_size=38,
            parent=self,
        )
        self.fullscreen_button = IconToolButton(
            theme_manager,
            "fullscreen",
            object_name="TransportButton",
            size=18,
            button_size=38,
            parent=self,
        )

        self.seekbar = SeekBar(self)
        self.volume_bar = VolumeBar(self)

        self.time_label = QLabel("00:00:00 / 00:00:00", self)
        self.time_label.setObjectName("TimelineLabel")
        self.time_label.setMinimumWidth(184)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.speed_combo = QComboBox(self)
        self.speed_combo.setObjectName("SpeedChooser")
        for speed in PLAYBACK_SPEEDS:
            self.speed_combo.addItem(f"{speed:g}x", speed)
        self.speed_combo.setCurrentText("1x")
        self.speed_combo.setMinimumWidth(82)
        self.speed_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)
        layout.addWidget(self.previous_button)
        layout.addWidget(self.rewind_button)
        layout.addWidget(self.play_button)
        layout.addWidget(self.forward_button)
        layout.addWidget(self.next_button)
        layout.addWidget(self.seekbar, 1)
        layout.addWidget(self.time_label)
        layout.addWidget(self.mute_button)
        layout.addWidget(self.volume_bar)
        layout.addWidget(self.speed_combo)
        layout.addWidget(self.fullscreen_button)

        self._hide_timer = QTimer(self)
        self._hide_timer.setInterval(2500)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._apply_auto_hide)

        self.previous_button.clicked.connect(self.previous_requested.emit)
        self.rewind_button.clicked.connect(lambda: self.seek_relative_requested.emit(-5000))
        self.play_button.clicked.connect(self.toggle_playback_requested.emit)
        self.forward_button.clicked.connect(lambda: self.seek_relative_requested.emit(5000))
        self.next_button.clicked.connect(self.next_requested.emit)
        self.seekbar.scrubbed.connect(self._on_seekbar_scrubbed)
        self.seekbar.seek_requested.connect(self.seek_requested.emit)
        self.mute_button.clicked.connect(self.mute_requested.emit)
        self.volume_bar.volume_changed.connect(self.volume_requested.emit)
        self.fullscreen_button.clicked.connect(self.fullscreen_requested.emit)
        self.speed_combo.currentIndexChanged.connect(self._emit_speed_change)

    def set_playing(self, playing: bool) -> None:
        self._is_playing = playing
        self.play_button.set_icon_name("pause" if playing else "play")

    def set_volume(self, volume: int, muted: bool) -> None:
        self._is_muted = muted
        self.volume_bar.set_volume(volume)
        self.mute_button.set_icon_name("mute" if muted or volume == 0 else "volume")

    def set_speed(self, speed: float) -> None:
        with QSignalBlocker(self.speed_combo):
            for index in range(self.speed_combo.count()):
                combo_speed = float(self.speed_combo.itemData(index))
                if abs(combo_speed - speed) < 0.01:
                    self.speed_combo.setCurrentIndex(index)
                    break

    def set_fullscreen(self, fullscreen: bool) -> None:
        self._is_fullscreen = fullscreen
        icon_name = "fullscreen-exit" if fullscreen else "fullscreen"
        self.fullscreen_button.set_icon_name(icon_name)

    def set_timeline(self, position_ms: int, duration_ms: int, buffered_ms: int) -> None:
        self._position_ms = max(position_ms, 0)
        self._duration_ms = max(duration_ms, 0)
        self._buffered_ms = max(buffered_ms, 0)
        self.seekbar.set_duration(self._duration_ms)
        self.seekbar.set_buffered_position(self._buffered_ms)
        self.seekbar.set_position(self._position_ms)
        self._update_time_label(self._position_ms)

    def preview_position(self, position_ms: int) -> None:
        self.seekbar.preview_position(position_ms)
        self._update_time_label(position_ms)

    def set_auto_hide_enabled(self, enabled: bool) -> None:
        self._auto_hide_enabled = enabled
        if enabled:
            self.note_activity()
        else:
            self._hide_timer.stop()
            self.show()

    def note_activity(self) -> None:
        if not self._auto_hide_enabled:
            return
        self.show()
        self.raise_()
        self._hide_timer.start()

    def is_scrubbing(self) -> bool:
        return self.seekbar.is_dragging()

    def mouseMoveEvent(self, event: object) -> None:
        self.note_activity()
        super().mouseMoveEvent(event)

    def enterEvent(self, event: object) -> None:
        self.note_activity()
        super().enterEvent(event)

    def _emit_speed_change(self, index: int) -> None:
        speed = float(self.speed_combo.itemData(index))
        self.speed_requested.emit(speed)

    def _on_seekbar_scrubbed(self, position_ms: int) -> None:
        self.preview_position(position_ms)
        self.scrub_requested.emit(position_ms)

    def _update_time_label(self, position_ms: int) -> None:
        current = format_timestamp(position_ms)
        total = format_timestamp(self._duration_ms)
        self.time_label.setText(f"{current} / {total}")

    def _apply_auto_hide(self) -> None:
        if not self._auto_hide_enabled:
            return
        if self.underMouse() or self.seekbar.is_dragging() or self.volume_bar.is_dragging():
            self._hide_timer.start()
            return
        self.hide()
