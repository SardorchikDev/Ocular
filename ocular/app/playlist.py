from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Sequence

import vlc
from PyQt6.QtCore import QPoint, QSize, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QDesktopServices,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QIcon,
    QKeyEvent,
    QPainter,
    QPalette,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QMenu,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.player import MediaEntry, VlcPlayer
from app.theme import CONFIG_DIR, ThemeManager, blend_color

LOGGER = logging.getLogger(__name__)


class PlaylistTreeWidget(QTreeWidget):
    files_dropped = pyqtSignal(list)
    delete_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Delete:
            self.delete_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class PlaylistSidebar(QWidget):
    play_requested = pyqtSignal(str)
    entry_removed = pyqtSignal(str, bool)
    thumbnail_ready = pyqtSignal(str, str)
    metadata_ready = pyqtSignal(str, int, int, int)

    def __init__(
        self,
        player: VlcPlayer,
        theme_manager: ThemeManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._player = player
        self._theme_manager = theme_manager
        self._ordered_ids: list[str] = []
        self._entries_by_id: dict[str, MediaEntry] = {}
        self._items_by_id: dict[str, QTreeWidgetItem] = {}
        self._current_id: str | None = None
        self._thumb_dir = CONFIG_DIR / "thumbs"
        self._thumb_dir.mkdir(parents=True, exist_ok=True)

        self.setObjectName("PlaylistSidebar")

        self.header_label = QLabel("Playlist", self)
        self.header_label.setObjectName("Subtle")

        self.tree = PlaylistTreeWidget(self)
        self.tree.setColumnCount(1)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree.setUniformRowHeights(False)
        self.tree.setAlternatingRowColors(False)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.setWordWrap(True)
        self.tree.setIndentation(0)
        self.tree.setIconSize(QSize(112, 63))
        self.tree.setMinimumWidth(330)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        layout.addWidget(self.header_label)
        layout.addWidget(self.tree, 1)

        self.tree.itemDoubleClicked.connect(self._handle_item_activated)
        self.tree.customContextMenuRequested.connect(self._open_context_menu)
        self.tree.files_dropped.connect(self.enqueue_paths)
        self.tree.delete_requested.connect(self.remove_selected)
        self.thumbnail_ready.connect(self._apply_thumbnail)
        self.metadata_ready.connect(self._apply_metadata)
        self._theme_manager.theme_changed.connect(self.refresh_theme)

    def enqueue_paths(self, paths: Sequence[Path]) -> list[str]:
        added_ids: list[str] = []
        for path in paths:
            source = path.expanduser()
            if not source.is_file():
                LOGGER.warning("Skipped non-file playlist input: %s", source)
                continue
            try:
                entry = self._player.prepare_media(source)
            except (OSError, TypeError, ValueError, vlc.VLCException) as exc:
                LOGGER.error("Failed to add %s to playlist: %s", source, exc)
                continue
            LOGGER.info("Added %s to playlist.", source)
            item = self._create_item(entry)
            self.tree.addTopLevelItem(item)
            self._entries_by_id[entry.identifier] = entry
            self._items_by_id[entry.identifier] = item
            self._ordered_ids.append(entry.identifier)
            self._start_thumbnail_worker(entry)
            added_ids.append(entry.identifier)

        if added_ids and self._current_id is None:
            self.set_current_entry(added_ids[0])
        self._update_header()
        return added_ids

    def entry(self, entry_id: str) -> MediaEntry | None:
        return self._entries_by_id.get(entry_id)

    def current_entry_id(self) -> str | None:
        return self._current_id

    def entry_ids(self) -> list[str]:
        return list(self._ordered_ids)

    def next_entry_id(self) -> str | None:
        if not self._ordered_ids:
            return None
        if self._current_id not in self._ordered_ids:
            return self._ordered_ids[0]
        current_index = self._ordered_ids.index(self._current_id)
        next_index = current_index + 1
        if next_index >= len(self._ordered_ids):
            return None
        return self._ordered_ids[next_index]

    def previous_entry_id(self) -> str | None:
        if not self._ordered_ids:
            return None
        if self._current_id not in self._ordered_ids:
            return self._ordered_ids[0]
        current_index = self._ordered_ids.index(self._current_id)
        previous_index = current_index - 1
        if previous_index < 0:
            return None
        return self._ordered_ids[previous_index]

    def set_current_entry(self, entry_id: str | None) -> None:
        self._current_id = entry_id
        if entry_id is None:
            self.tree.clearSelection()
            return
        item = self._items_by_id.get(entry_id)
        if item is None:
            return
        self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item)

    def remove_selected(self) -> None:
        item = self.tree.currentItem()
        if item is None:
            return
        entry_id = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(entry_id, str):
            self.remove_entry(entry_id)

    def remove_entry(self, entry_id: str) -> None:
        if entry_id not in self._entries_by_id:
            return
        removed_current = entry_id == self._current_id
        removal_index = self._ordered_ids.index(entry_id)
        item = self._items_by_id.pop(entry_id)
        tree_index = self.tree.indexOfTopLevelItem(item)
        self.tree.takeTopLevelItem(tree_index)

        entry = self._entries_by_id.pop(entry_id)
        self._ordered_ids.remove(entry_id)
        entry.release()

        if removed_current:
            if self._ordered_ids:
                replacement_index = min(removal_index, len(self._ordered_ids) - 1)
                self.set_current_entry(self._ordered_ids[replacement_index])
            else:
                self.set_current_entry(None)

        self._update_header()
        self.entry_removed.emit(entry_id, removed_current)

    def open_in_file_manager(self, entry_id: str) -> None:
        entry = self.entry(entry_id)
        if entry is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(entry.path.parent)))

    def refresh_theme(self, _theme_name: str | None = None) -> None:
        del _theme_name
        for entry_id, item in self._items_by_id.items():
            entry = self._entries_by_id[entry_id]
            if entry.thumbnail_path is None or not entry.thumbnail_path.exists():
                item.setIcon(0, QIcon(self._placeholder_icon(entry.title)))

    def _update_header(self) -> None:
        count = len(self._ordered_ids)
        self.header_label.setText(f"Playlist ({count})")

    def _create_item(self, entry: MediaEntry) -> QTreeWidgetItem:
        item = QTreeWidgetItem([self._display_text(entry)])
        item.setData(0, Qt.ItemDataRole.UserRole, entry.identifier)
        item.setSizeHint(0, QSize(0, 82))
        item.setToolTip(0, self._tooltip_text(entry))
        item.setIcon(0, QIcon(self._placeholder_icon(entry.title)))
        return item

    def _handle_item_activated(self, item: QTreeWidgetItem, column: int) -> None:
        del column
        entry_id = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(entry_id, str):
            self.set_current_entry(entry_id)
            self.play_requested.emit(entry_id)

    def _open_context_menu(self, position: QPoint) -> None:
        item = self.tree.itemAt(position)
        if item is None:
            return
        entry_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(entry_id, str):
            return

        menu = QMenu(self)
        play_action = QAction("Play", self)
        remove_action = QAction("Remove", self)
        open_action = QAction("Open in File Manager", self)
        play_action.triggered.connect(lambda: self.play_requested.emit(entry_id))
        remove_action.triggered.connect(lambda: self.remove_entry(entry_id))
        open_action.triggered.connect(lambda: self.open_in_file_manager(entry_id))
        menu.addAction(play_action)
        menu.addAction(remove_action)
        menu.addAction(open_action)
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def _start_thumbnail_worker(self, entry: MediaEntry) -> None:
        worker = threading.Thread(
            target=self._generate_thumbnail,
            args=(entry.identifier, entry.path, entry.duration_ms),
            daemon=True,
        )
        worker.start()

    def _generate_thumbnail(self, entry_id: str, path: Path, duration_ms: int) -> None:
        output_path = self._thumb_dir / f"{entry_id}.png"
        if output_path.exists():
            self.thumbnail_ready.emit(entry_id, str(output_path))

        instance = None
        media_player = None
        media = None
        try:
            options = [*self._player.instance_options, "--intf=dummy", "--no-audio"]
            instance = vlc.Instance(*options)
            media_player = instance.media_player_new()
            media = instance.media_new(str(path))
            media_player.set_media(media)
            media_player.audio_set_mute(True)
            media_player.play()

            deadline = time.monotonic() + 8.0
            while time.monotonic() < deadline:
                if media_player.get_length() > 0:
                    break
                time.sleep(0.1)

            actual_duration = int(max(duration_ms, media_player.get_length(), 0))
            width, height = self._video_size(media_player)
            self.metadata_ready.emit(entry_id, actual_duration, width, height)

            target_ms = int(actual_duration * 0.1)
            if target_ms > 0:
                media_player.set_time(target_ms)
                time.sleep(0.4)

            for _ in range(12):
                width, height = self._video_size(media_player)
                if width > 0 or height > 0 or actual_duration > 0:
                    self.metadata_ready.emit(entry_id, actual_duration, width, height)
                media_player.video_take_snapshot(0, str(output_path), 320, 180)
                if output_path.exists() and output_path.stat().st_size > 0:
                    self.thumbnail_ready.emit(entry_id, str(output_path))
                    return
                time.sleep(0.2)
        except (OSError, TypeError, ValueError, vlc.VLCException) as exc:
            LOGGER.debug("Thumbnail generation failed for %s: %s", path, exc)
        finally:
            if media_player is not None:
                try:
                    media_player.stop()
                except vlc.VLCException:
                    LOGGER.debug("Failed to stop thumbnail player for %s", path)
                release_player = getattr(media_player, "release", None)
                if callable(release_player):
                    try:
                        release_player()
                    except vlc.VLCException:
                        LOGGER.debug("Failed to release thumbnail player for %s", path)
            if media is not None:
                release_media = getattr(media, "release", None)
                if callable(release_media):
                    try:
                        release_media()
                    except vlc.VLCException:
                        LOGGER.debug("Failed to release thumbnail media for %s", path)
            if instance is not None:
                release_instance = getattr(instance, "release", None)
                if callable(release_instance):
                    try:
                        release_instance()
                    except vlc.VLCException:
                        LOGGER.debug("Failed to release thumbnail VLC instance for %s", path)

    def _apply_thumbnail(self, entry_id: str, thumbnail_path: str) -> None:
        entry = self._entries_by_id.get(entry_id)
        item = self._items_by_id.get(entry_id)
        if entry is None or item is None:
            return
        pixmap = QPixmap(thumbnail_path)
        if pixmap.isNull():
            return
        entry.thumbnail_path = Path(thumbnail_path)
        item.setIcon(0, QIcon(pixmap.scaled(
            self.tree.iconSize(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )))

    def _apply_metadata(
        self,
        entry_id: str,
        duration_ms: int,
        width: int,
        height: int,
    ) -> None:
        entry = self._entries_by_id.get(entry_id)
        item = self._items_by_id.get(entry_id)
        if entry is None or item is None:
            return
        if duration_ms > 0:
            entry.duration_ms = duration_ms
        if width > 0 and height > 0:
            entry.width = width
            entry.height = height
        item.setText(0, self._display_text(entry))
        item.setToolTip(0, self._tooltip_text(entry))

    def _placeholder_icon(self, title: str) -> QPixmap:
        pixmap = QPixmap(self.tree.iconSize())
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = pixmap.rect().adjusted(2, 2, -2, -2)
        background = blend_color(self.palette().color(QPalette.ColorRole.Midlight), 120)
        text_color = self.palette().color(QPalette.ColorRole.WindowText)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(background)
        painter.drawRect(rect)
        painter.setPen(text_color)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, title[:1].upper())
        painter.end()
        return pixmap

    @staticmethod
    def _display_text(entry: MediaEntry) -> str:
        return f"{entry.title}\n{entry.duration_text}  {entry.resolution_text}"

    @staticmethod
    def _tooltip_text(entry: MediaEntry) -> str:
        return (
            f"{entry.path}\n"
            f"{entry.duration_text}  {entry.resolution_text}"
        )

    @staticmethod
    def _video_size(media_player: vlc.MediaPlayer) -> tuple[int, int]:
        try:
            size = media_player.video_get_size(0)
        except (AttributeError, TypeError, ValueError, vlc.VLCException):
            return 0, 0
        if not isinstance(size, tuple) or len(size) != 2:
            return 0, 0
        width, height = size
        try:
            return int(width), int(height)
        except (TypeError, ValueError):
            return 0, 0
