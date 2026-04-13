from __future__ import annotations

import logging
from collections.abc import Sequence
from enum import IntFlag
from pathlib import Path

from PyQt6.QtCore import QPoint, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QDragEnterEvent,
    QDropEvent,
    QKeySequence,
    QMouseEvent,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.controls import IconToolButton, PlaybackControls
from app.player import VlcPlayer
from app.playlist import PlaylistSidebar
from app.theme import ConfigManager, ThemeManager

LOGGER = logging.getLogger(__name__)


class ResizeEdges(IntFlag):
    NONE = 0
    LEFT = 1
    TOP = 2
    RIGHT = 4
    BOTTOM = 8


class VideoSurface(QWidget):
    activity = pyqtSignal()
    double_clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("VideoPane")
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAcceptDrops(False)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self.activity.emit()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.activity.emit()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class TitleBar(QWidget):
    open_requested = pyqtSignal()
    playlist_requested = pyqtSignal()
    theme_requested = pyqtSignal()
    close_requested = pyqtSignal()

    def __init__(self, theme_manager: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dragging = False
        self._drag_offset = QPoint()
        self._theme_manager = theme_manager

        self.setObjectName("TitleBar")
        self.setMouseTracking(True)
        self.setFixedHeight(50)

        self._placeholder_title = "Drop a video or press Ctrl+O"
        self.title_label = QLabel(self._placeholder_title, self)
        self.title_label.setObjectName("WindowTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setMinimumWidth(280)

        self.open_button = IconToolButton(
            theme_manager,
            "folder",
            object_name="ToolbarButton",
            size=18,
            button_size=38,
            parent=self,
        )
        self.playlist_button = IconToolButton(
            theme_manager,
            "playlist",
            object_name="ToolbarButton",
            size=18,
            button_size=38,
            parent=self,
        )
        self.theme_button = IconToolButton(
            theme_manager,
            "sun",
            object_name="ToolbarButton",
            size=18,
            button_size=38,
            parent=self,
        )
        self.close_button = IconToolButton(
            theme_manager,
            "close",
            object_name="CloseButton",
            size=18,
            button_size=38,
            parent=self,
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)
        layout.addWidget(self.open_button)
        layout.addWidget(self.playlist_button)
        layout.addWidget(self.theme_button)
        layout.addWidget(self.title_label, 1)
        layout.addWidget(self.close_button)

        self.open_button.clicked.connect(self.open_requested.emit)
        self.playlist_button.clicked.connect(self.playlist_requested.emit)
        self.theme_button.clicked.connect(self.theme_requested.emit)
        self.close_button.clicked.connect(self.close_requested.emit)
        self._theme_manager.theme_changed.connect(self._sync_theme_icon)
        self._sync_theme_icon()

    def set_title(self, title: str) -> None:
        self.title_label.setText(title or self._placeholder_title)

    def set_maximized(self, maximized: bool) -> None:
        del maximized

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        target = self.childAt(event.position().toPoint())
        if isinstance(target, IconToolButton):
            super().mousePressEvent(event)
            return
        if self.window().isMaximized() or self.window().isFullScreen():
            super().mousePressEvent(event)
            return
        self._dragging = True
        self._drag_offset = (
            event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
        )
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging and not self.window().isMaximized() and not self.window().isFullScreen():
            self.window().move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._dragging = False
        super().mouseReleaseEvent(event)

    def _sync_theme_icon(self, _theme_name: str | None = None) -> None:
        del _theme_name
        icon_name = "sun" if self._theme_manager.theme_name == "dark" else "moon"
        self.theme_button.set_icon_name(icon_name)


class MainWindow(QWidget):
    RESIZE_MARGIN = 8

    def __init__(
        self,
        config: ConfigManager,
        theme_manager: ThemeManager,
        startup_paths: Sequence[Path] | None = None,
    ) -> None:
        super().__init__()
        self._config = config
        self._theme_manager = theme_manager
        self._playlist_visible_before_fullscreen = True
        self._was_maximized_before_fullscreen = False
        self._resize_edges = ResizeEdges.NONE
        self._resize_origin = QPoint()
        self._resize_geometry = QRect()
        self._output_bound = False
        self._startup_paths = [Path(path).expanduser() for path in startup_paths or []]
        self._startup_paths_loaded = False

        self.player = VlcPlayer(config.data.volume, config.data.speed)

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setMinimumSize(640, 400)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        geometry = config.data.window
        self.setGeometry(geometry.x, geometry.y, geometry.w, geometry.h)

        self._geometry_save_timer = QTimer(self)
        self._geometry_save_timer.setInterval(250)
        self._geometry_save_timer.setSingleShot(True)
        self._geometry_save_timer.timeout.connect(self._persist_window_geometry)

        self._build_ui()
        self._build_shortcuts()
        self._connect_signals()

        self.controls.set_speed(self._config.data.speed)
        self.controls.set_volume(self._config.data.volume, False)

    def showEvent(self, event: object) -> None:
        if not self._output_bound:
            self.player.set_video_widget(self.video_surface)
            self._output_bound = True
        if self._startup_paths and not self._startup_paths_loaded:
            self._startup_paths_loaded = True
            QTimer.singleShot(0, self._open_startup_paths)
        super().showEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        if not paths:
            super().dropEvent(event)
            return
        LOGGER.info("Dropped %d file(s) into the window.", len(paths))
        self.open_paths(paths, play_first=True)
        event.acceptProposedAction()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self._window_locked():
            edges = self._hit_test(event.position().toPoint())
            if edges != ResizeEdges.NONE:
                self._resize_edges = edges
                self._resize_origin = event.globalPosition().toPoint()
                self._resize_geometry = self.geometry()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._resize_edges != ResizeEdges.NONE:
            self._perform_resize(event.globalPosition().toPoint())
            event.accept()
            return
        if not self._window_locked():
            self._update_cursor(self._hit_test(event.position().toPoint()))
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._resize_edges = ResizeEdges.NONE
        self.unsetCursor()
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event: object) -> None:
        if self._resize_edges == ResizeEdges.NONE:
            self.unsetCursor()
        super().leaveEvent(event)

    def resizeEvent(self, event: object) -> None:
        self._schedule_geometry_save()
        super().resizeEvent(event)

    def moveEvent(self, event: object) -> None:
        self._schedule_geometry_save()
        super().moveEvent(event)

    def changeEvent(self, event: object) -> None:
        if hasattr(self, "title_bar"):
            self.title_bar.set_maximized(self.isMaximized())
        super().changeEvent(event)

    def closeEvent(self, event: object) -> None:
        self._persist_window_geometry()
        for entry_id in self.playlist.entry_ids():
            entry = self.playlist.entry(entry_id)
            if entry is not None:
                entry.release()
        self.player.release()
        super().closeEvent(event)

    def open_files(self) -> None:
        last_dir = Path(self._config.data.last_dir).expanduser()
        selected_files, _ = QFileDialog.getOpenFileNames(
            self,
            "Open Video",
            str(last_dir),
            (
                "Videos (*.mp4 *.mkv *.avi *.mov *.webm *.flv *.ts *.m2ts);;"
                "All Files (*)"
            ),
        )
        if not selected_files:
            LOGGER.info("Open dialog closed without selecting a file.")
            return
        paths = [Path(value) for value in selected_files]
        LOGGER.info("Selected %d file(s) from the open dialog.", len(paths))
        self.open_paths(paths, play_first=True)

    def open_paths(self, paths: Sequence[Path], play_first: bool = True) -> None:
        normalized_paths = [Path(path).expanduser() for path in paths]
        existing_paths = [path for path in normalized_paths if path.is_file()]
        for missing_path in normalized_paths:
            if missing_path not in existing_paths:
                LOGGER.warning("Skipped missing file: %s", missing_path)
        if not existing_paths:
            return
        self._config.update_last_dir(existing_paths[0].parent)
        self._enqueue_and_optionally_play(existing_paths, play_first=play_first)

    def toggle_theme(self) -> None:
        app = QApplication.instance()
        if app is not None:
            self._theme_manager.toggle_theme(app)

    def toggle_playlist(self) -> None:
        if self.isFullScreen():
            return
        self.playlist.setVisible(not self.playlist.isVisible())

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self._leave_fullscreen()
            return
        self._enter_fullscreen()

    def exit_fullscreen(self) -> None:
        if self.isFullScreen():
            self._leave_fullscreen()

    def play_next(self) -> None:
        entry_id = self.playlist.next_entry_id()
        if entry_id is not None:
            self.play_entry_id(entry_id)

    def play_previous(self) -> None:
        entry_id = self.playlist.previous_entry_id()
        if entry_id is not None:
            self.play_entry_id(entry_id)

    def play_entry_id(self, entry_id: str) -> None:
        entry = self.playlist.entry(entry_id)
        if entry is None:
            LOGGER.warning("Requested playback for unknown entry id %s.", entry_id)
            return
        LOGGER.info("Starting playback for %s", entry.path)
        self.playlist.set_current_entry(entry_id)
        self.player.play_entry(entry)
        self.player.set_volume(self._config.data.volume)
        self.player.set_rate(self._config.data.speed)
        self.controls.set_timeline(0, entry.duration_ms, 0)
        self.controls.set_playing(True)
        self.controls.set_volume(self._config.data.volume, self.player.is_muted())
        self.controls.set_speed(self._config.data.speed)
        self.title_bar.set_title(entry.title)
        self._note_activity()

    def set_volume(self, volume: int) -> None:
        if self.player.is_muted() and volume > 0:
            self.player.toggle_mute()
        self.player.set_volume(volume)
        self.controls.set_volume(self.player.volume(), self.player.is_muted())
        self._config.update_volume(self.player.volume())

    def adjust_speed(self, direction: int) -> None:
        speed = self.player.step_rate(direction)
        self.controls.set_speed(speed)
        self._config.update_speed(speed)

    def _build_ui(self) -> None:
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(
            self.RESIZE_MARGIN,
            self.RESIZE_MARGIN,
            self.RESIZE_MARGIN,
            self.RESIZE_MARGIN,
        )
        outer_layout.setSpacing(0)

        self.frame = QWidget(self)
        self.frame.setObjectName("frame")
        outer_layout.addWidget(self.frame)

        frame_layout = QVBoxLayout(self.frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)

        self.title_bar = TitleBar(self._theme_manager, self.frame)
        frame_layout.addWidget(self.title_bar)

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self.frame)
        self.splitter.setChildrenCollapsible(False)
        frame_layout.addWidget(self.splitter, 1)

        self.video_column = QWidget(self.splitter)
        self.video_column.setObjectName("VideoPane")
        video_layout = QVBoxLayout(self.video_column)
        video_layout.setContentsMargins(0, 0, 0, 0)
        video_layout.setSpacing(0)

        self.video_surface = VideoSurface(self.video_column)
        self.controls = PlaybackControls(self._theme_manager, self.video_column)
        video_layout.addWidget(self.video_surface, 1)
        video_layout.addWidget(self.controls)

        self.playlist = PlaylistSidebar(self.player, self._theme_manager, self.splitter)

        self.splitter.addWidget(self.video_column)
        self.splitter.addWidget(self.playlist)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([1080, 340])

    def _build_shortcuts(self) -> None:
        bindings = [
            ("Ctrl+O", self.open_files),
            ("Ctrl+Q", self.close),
            ("Space", self.player.toggle_playback),
            ("Right", lambda: self.player.seek_relative(5000)),
            ("Shift+Right", lambda: self.player.seek_relative(30000)),
            ("Left", lambda: self.player.seek_relative(-5000)),
            ("Shift+Left", lambda: self.player.seek_relative(-30000)),
            ("Up", lambda: self.set_volume(self.player.volume() + 5)),
            ("Down", lambda: self.set_volume(self.player.volume() - 5)),
            ("M", self.player.toggle_mute),
            ("F11", self.toggle_fullscreen),
            ("Esc", self.exit_fullscreen),
            ("N", self.play_next),
            ("P", self.play_previous),
            (".", self.player.frame_step_forward),
            (",", self.player.frame_step_backward),
            ("[", lambda: self.adjust_speed(-1)),
            ("]", lambda: self.adjust_speed(1)),
            ("L", self.toggle_playlist),
            ("T", self.toggle_theme),
        ]
        self._shortcuts: list[QShortcut] = []
        for sequence, callback in bindings:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)

    def _connect_signals(self) -> None:
        self.title_bar.open_requested.connect(self.open_files)
        self.title_bar.playlist_requested.connect(self.toggle_playlist)
        self.title_bar.theme_requested.connect(self.toggle_theme)
        self.title_bar.close_requested.connect(self.close)

        self.video_surface.activity.connect(self._note_activity)
        self.video_surface.double_clicked.connect(self.toggle_fullscreen)

        self.controls.toggle_playback_requested.connect(self.player.toggle_playback)
        self.controls.previous_requested.connect(self.play_previous)
        self.controls.next_requested.connect(self.play_next)
        self.controls.seek_relative_requested.connect(self.player.seek_relative)
        self.controls.scrub_requested.connect(self.player.set_time)
        self.controls.seek_requested.connect(self.player.set_time)
        self.controls.volume_requested.connect(self.set_volume)
        self.controls.mute_requested.connect(self.player.toggle_mute)
        self.controls.fullscreen_requested.connect(self.toggle_fullscreen)
        self.controls.speed_requested.connect(self._set_speed)

        self.playlist.play_requested.connect(self.play_entry_id)
        self.playlist.entry_removed.connect(self._handle_entry_removed)

        self.player.position_changed.connect(self._sync_timeline)
        self.player.playback_state_changed.connect(self.controls.set_playing)
        self.player.volume_changed.connect(self._handle_volume_changed)
        self.player.muted_changed.connect(self._handle_muted_changed)
        self.player.rate_changed.connect(self._handle_rate_changed)
        self.player.state_changed.connect(self._handle_state_changed)
        self.player.end_reached.connect(self.play_next)
        self.player.error_occurred.connect(self._handle_player_error)

    def _enqueue_and_optionally_play(self, paths: Sequence[Path], play_first: bool) -> None:
        added_ids = self.playlist.enqueue_paths(paths)
        LOGGER.info("Enqueued %d of %d requested file(s).", len(added_ids), len(paths))
        if added_ids and play_first:
            self.play_entry_id(added_ids[0])

    def _set_speed(self, speed: float) -> None:
        self.player.set_rate(speed)
        self._config.update_speed(speed)

    def _sync_timeline(self, position_ms: int, duration_ms: int, buffered_ms: int) -> None:
        if self.controls.is_scrubbing():
            return
        self.controls.set_timeline(position_ms, duration_ms, buffered_ms)

    def _handle_volume_changed(self, volume: int) -> None:
        self.controls.set_volume(volume, self.player.is_muted())

    def _handle_muted_changed(self, muted: bool) -> None:
        self.controls.set_volume(self.player.volume(), muted)

    def _handle_rate_changed(self, speed: float) -> None:
        self.controls.set_speed(speed)

    def _handle_state_changed(self, state_name: str) -> None:
        if state_name == "playing":
            self.controls.set_playing(True)
            return
        if state_name in {"stopped", "paused"}:
            self.controls.set_playing(False)

    def _handle_player_error(self, message: str) -> None:
        LOGGER.error(message)

    def _handle_entry_removed(self, entry_id: str, removed_current: bool) -> None:
        del entry_id
        if removed_current:
            self.player.stop()
            replacement = self.playlist.current_entry_id()
            if replacement is not None:
                self.play_entry_id(replacement)
            else:
                self.controls.set_timeline(0, 0, 0)
                self.controls.set_playing(False)
                self.title_bar.set_title("")

    def _enter_fullscreen(self) -> None:
        self._playlist_visible_before_fullscreen = self.playlist.isVisible()
        self._was_maximized_before_fullscreen = self.isMaximized()
        self.showFullScreen()
        self.title_bar.hide()
        self.playlist.hide()
        self.controls.set_fullscreen(True)
        self.controls.set_auto_hide_enabled(True)
        self.controls.note_activity()

    def _leave_fullscreen(self) -> None:
        self.showNormal()
        if self._was_maximized_before_fullscreen:
            self.showMaximized()
        self.title_bar.show()
        if self._playlist_visible_before_fullscreen:
            self.playlist.show()
        self.controls.set_auto_hide_enabled(False)
        self.controls.set_fullscreen(False)
        self.controls.show()

    def _note_activity(self) -> None:
        if self.isFullScreen():
            self.controls.note_activity()

    def _open_startup_paths(self) -> None:
        self.open_paths(self._startup_paths, play_first=True)
        self._startup_paths = []

    def _window_locked(self) -> bool:
        return self.isMaximized() or self.isFullScreen()

    def _schedule_geometry_save(self) -> None:
        if self._window_locked():
            return
        self._geometry_save_timer.start()

    def _persist_window_geometry(self) -> None:
        if self.isFullScreen():
            return
        geometry = self.normalGeometry() if self.isMaximized() else self.geometry()
        self._config.update_window(
            geometry.x(),
            geometry.y(),
            geometry.width(),
            geometry.height(),
        )

    def _hit_test(self, position: QPoint) -> ResizeEdges:
        edges = ResizeEdges.NONE
        if position.x() <= self.RESIZE_MARGIN:
            edges |= ResizeEdges.LEFT
        if position.x() >= self.width() - self.RESIZE_MARGIN:
            edges |= ResizeEdges.RIGHT
        if position.y() <= self.RESIZE_MARGIN:
            edges |= ResizeEdges.TOP
        if position.y() >= self.height() - self.RESIZE_MARGIN:
            edges |= ResizeEdges.BOTTOM
        return edges

    def _update_cursor(self, edges: ResizeEdges) -> None:
        if edges in (ResizeEdges.TOP | ResizeEdges.LEFT, ResizeEdges.BOTTOM | ResizeEdges.RIGHT):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edges in (ResizeEdges.TOP | ResizeEdges.RIGHT, ResizeEdges.BOTTOM | ResizeEdges.LEFT):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif edges in (ResizeEdges.LEFT, ResizeEdges.RIGHT):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edges in (ResizeEdges.TOP, ResizeEdges.BOTTOM):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.unsetCursor()

    def _perform_resize(self, global_position: QPoint) -> None:
        delta = global_position - self._resize_origin
        geometry = QRect(self._resize_geometry)

        if self._resize_edges & ResizeEdges.LEFT:
            new_left = min(
                geometry.right() - self.minimumWidth(),
                self._resize_geometry.left() + delta.x(),
            )
            geometry.setLeft(new_left)
        if self._resize_edges & ResizeEdges.RIGHT:
            geometry.setRight(
                max(
                    geometry.left() + self.minimumWidth(),
                    self._resize_geometry.right() + delta.x(),
                )
            )
        if self._resize_edges & ResizeEdges.TOP:
            new_top = min(
                geometry.bottom() - self.minimumHeight(),
                self._resize_geometry.top() + delta.y(),
            )
            geometry.setTop(new_top)
        if self._resize_edges & ResizeEdges.BOTTOM:
            geometry.setBottom(
                max(
                    geometry.top() + self.minimumHeight(),
                    self._resize_geometry.bottom() + delta.y(),
                )
            )

        self.setGeometry(geometry)
