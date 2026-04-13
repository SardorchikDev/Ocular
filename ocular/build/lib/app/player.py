from __future__ import annotations

import logging
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import vlc
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QWidget

from app.theme import format_timestamp

LOGGER = logging.getLogger(__name__)

PLAYBACK_SPEEDS: tuple[float, ...] = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0)
MAX_USER_VOLUME = 100
MAX_OUTPUT_VOLUME = 150
VOLUME_BOOST_FACTOR = 1.5


def build_vlc_instance_options() -> list[str]:
    options = [
        "--quiet",
        "--no-video-title-show",
        "--drop-late-frames",
        "--skip-frames",
        "--file-caching=300",
        "--network-caching=300",
    ]
    if sys.platform.startswith("win"):
        options.append("--avcodec-hw=dxva2")
    elif sys.platform == "darwin":
        options.append("--avcodec-hw=videotoolbox")
    elif sys.platform.startswith("linux"):
        if Path("/dev/dri/renderD128").exists() or Path("/dev/dri").exists():
            options.append("--avcodec-hw=vaapi")
        else:
            options.append("--avcodec-hw=vdpau")
    else:
        options.append("--avcodec-hw=any")
    return options


@dataclass(slots=True)
class MediaEntry:
    identifier: str
    path: Path
    media: Any
    duration_ms: int
    width: int
    height: int
    fps: float = 0.0
    thumbnail_path: Path | None = None

    @property
    def title(self) -> str:
        return self.path.name

    @property
    def duration_text(self) -> str:
        return format_timestamp(self.duration_ms)

    @property
    def resolution_text(self) -> str:
        if self.width > 0 and self.height > 0:
            return f"{self.width}x{self.height}"
        return "Unknown"

    def release(self) -> None:
        if self.thumbnail_path is not None:
            try:
                self.thumbnail_path.unlink(missing_ok=True)
            except OSError as exc:
                LOGGER.debug("Failed to delete thumbnail %s: %s", self.thumbnail_path, exc)
            self.thumbnail_path = None
        release = getattr(self.media, "release", None)
        if callable(release):
            try:
                release()
            except vlc.VLCException as exc:
                LOGGER.debug("Failed to release media %s: %s", self.path, exc)


class VlcPlayer(QObject):
    position_changed = pyqtSignal(int, int, int)
    playback_state_changed = pyqtSignal(bool)
    state_changed = pyqtSignal(str)
    end_reached = pyqtSignal()
    error_occurred = pyqtSignal(str)
    volume_changed = pyqtSignal(int)
    muted_changed = pyqtSignal(bool)
    rate_changed = pyqtSignal(float)

    def __init__(self, volume: int = 80, rate: float = 1.0) -> None:
        super().__init__()
        self.instance_options = build_vlc_instance_options()
        try:
            self.instance = vlc.Instance(*self.instance_options)
        except (NameError, OSError, vlc.VLCException) as exc:
            raise RuntimeError(
                "libVLC is not available. Install VLC on the system so python-vlc can "
                "load libvlc."
            ) from exc
        self.media_player = self.instance.media_player_new()
        self.current_entry: MediaEntry | None = None
        self._video_widget: QWidget | None = None
        self._last_duration = 0
        self._last_position = 0
        self._last_buffered = 0
        self._last_playing = False
        self._last_state = "stopped"
        self._pending_end = False
        self._pending_error: str | None = None
        self._volume = max(min(volume, MAX_USER_VOLUME), 0)
        self._rate = self._closest_speed(rate)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(200)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start()

        self._event_manager = self.media_player.event_manager()
        self._attach_events()

    def prepare_media(self, path: Path) -> MediaEntry:
        media = self.instance.media_new(str(path))
        media.add_option(":input-fast-seek")
        media.add_option(":no-video-title-show")
        return MediaEntry(
            identifier=uuid.uuid4().hex,
            path=path,
            media=media,
            duration_ms=0,
            width=0,
            height=0,
            fps=0.0,
        )

    def set_video_widget(self, widget: QWidget) -> None:
        self._video_widget = widget
        window_id = int(widget.winId())
        if sys.platform.startswith("linux"):
            self.media_player.set_xwindow(window_id)
        elif sys.platform == "darwin":
            self.media_player.set_nsobject(window_id)
        else:
            self.media_player.set_hwnd(window_id)
        try:
            self.media_player.video_set_mouse_input(False)
            self.media_player.video_set_key_input(False)
        except vlc.VLCException:
            LOGGER.debug("VLC did not accept embedded input disabling.")

    def play_entry(self, entry: MediaEntry) -> None:
        self.current_entry = entry
        self._pending_end = False
        self.media_player.set_media(entry.media)
        if self._video_widget is not None:
            self.set_video_widget(self._video_widget)
        LOGGER.info("Requesting VLC playback for %s", entry.path)
        play_result = self.media_player.play()
        if play_result == -1:
            self.error_occurred.emit(f"Failed to play {entry.path}")
            return
        self.set_volume(self._volume)
        QTimer.singleShot(120, lambda: self.set_rate(self._rate))

    def play(self) -> None:
        if self.current_entry is not None and self._state_name() == "ended":
            self.play_entry(self.current_entry)
            return
        self.media_player.play()

    def pause(self) -> None:
        self.media_player.pause()

    def toggle_playback(self) -> None:
        if self.is_playing():
            self.pause()
        else:
            self.play()

    def stop(self) -> None:
        self.media_player.stop()
        self._last_position = 0
        self._last_buffered = 0

    def seek_relative(self, milliseconds: int) -> None:
        duration_ms = self.duration_ms()
        if duration_ms <= 0:
            return
        self.set_time(self.time_ms() + milliseconds)

    def set_time(self, milliseconds: int) -> None:
        duration_ms = self.duration_ms()
        if duration_ms <= 0:
            return
        clamped = max(0, min(milliseconds, duration_ms))
        self.media_player.set_time(clamped)

    def time_ms(self) -> int:
        return max(int(self.media_player.get_time()), 0)

    def duration_ms(self) -> int:
        live_duration = max(int(self.media_player.get_length()), 0)
        if live_duration > 0:
            return live_duration
        if self.current_entry is not None:
            return self.current_entry.duration_ms
        return 0

    def buffered_ms(self) -> int:
        duration_ms = self.duration_ms()
        if duration_ms <= 0 or self.current_entry is None:
            return 0
        media = self.media_player.get_media()
        if media is None:
            return 0
        stats = vlc.MediaStats()
        if not media.get_stats(stats):
            return 0
        try:
            file_size = self.current_entry.path.stat().st_size
        except OSError:
            return 0
        read_bytes = max(
            self._stat_value(stats, "demux_read_bytes", "i_demux_read_bytes"),
            self._stat_value(stats, "read_bytes", "i_read_bytes"),
        )
        if file_size <= 0 or read_bytes <= 0:
            return 0
        return int(duration_ms * min(read_bytes / file_size, 1.0))

    def set_volume(self, volume: int) -> None:
        self._volume = max(0, min(volume, MAX_USER_VOLUME))
        if self._volume > 0:
            self._set_muted(False)

        base_volume = self._volume
        self._set_output_volume(base_volume)

        boosted_volume = min(
            int(round(self._volume * VOLUME_BOOST_FACTOR)),
            MAX_OUTPUT_VOLUME,
        )
        if boosted_volume > base_volume:
            boost_result = self._set_output_volume(boosted_volume)
            if boost_result == -1:
                self._set_output_volume(base_volume)
        self.volume_changed.emit(self._volume)
        self.muted_changed.emit(self.is_muted())

    def change_volume(self, delta: int) -> None:
        self.set_volume(self._volume + delta)

    def volume(self) -> int:
        return self._volume

    def toggle_mute(self) -> None:
        self.media_player.audio_toggle_mute()
        self.muted_changed.emit(self.is_muted())

    def is_muted(self) -> bool:
        return bool(self.media_player.audio_get_mute())

    def _set_output_volume(self, volume: int) -> int:
        try:
            return int(self.media_player.audio_set_volume(volume))
        except vlc.VLCException as exc:
            LOGGER.warning("VLC rejected output volume %s: %s", volume, exc)
            return -1

    def _set_muted(self, muted: bool) -> None:
        setter = getattr(self.media_player, "audio_set_mute", None)
        if callable(setter):
            try:
                setter(muted)
            except vlc.VLCException as exc:
                LOGGER.debug("Failed to set mute=%s: %s", muted, exc)

    def set_rate(self, rate: float) -> None:
        self._rate = self._closest_speed(rate)
        result = self.media_player.set_rate(self._rate)
        if result == -1:
            LOGGER.debug("VLC rejected playback rate %s", self._rate)
        self.rate_changed.emit(self._rate)

    def rate(self) -> float:
        live_rate = float(self.media_player.get_rate() or 0.0)
        return live_rate if live_rate > 0 else self._rate

    def step_rate(self, direction: int) -> float:
        current_rate = self._closest_speed(self.rate())
        current_index = PLAYBACK_SPEEDS.index(current_rate)
        next_index = max(0, min(current_index + direction, len(PLAYBACK_SPEEDS) - 1))
        self.set_rate(PLAYBACK_SPEEDS[next_index])
        return PLAYBACK_SPEEDS[next_index]

    def frame_step_forward(self) -> None:
        self.media_player.set_pause(True)
        if hasattr(self.media_player, "next_frame"):
            self.media_player.next_frame()
            return
        self.set_time(self.time_ms() + self._frame_interval_ms())

    def frame_step_backward(self) -> None:
        self.media_player.set_pause(True)
        self.set_time(self.time_ms() - self._frame_interval_ms())

    def is_playing(self) -> bool:
        return bool(self.media_player.is_playing())

    def release(self) -> None:
        self._poll_timer.stop()
        try:
            self.media_player.stop()
        except vlc.VLCException as exc:
            LOGGER.debug("Failed to stop VLC player: %s", exc)
        for target in (self.media_player, self.instance):
            release = getattr(target, "release", None)
            if callable(release):
                try:
                    release()
                except vlc.VLCException as exc:
                    LOGGER.debug("Failed to release VLC object: %s", exc)

    def _attach_events(self) -> None:
        self._event_manager.event_attach(
            vlc.EventType.MediaPlayerEndReached,
            self._mark_end_reached,
        )
        self._event_manager.event_attach(
            vlc.EventType.MediaPlayerEncounteredError,
            self._mark_error,
        )

    def _mark_end_reached(self, event: Any) -> None:
        del event
        self._pending_end = True

    def _mark_error(self, event: Any) -> None:
        del event
        self._pending_error = "VLC reported a playback failure."

    def _poll(self) -> None:
        position_ms = self.time_ms()
        duration_ms = self.duration_ms()
        buffered_ms = max(self.buffered_ms(), position_ms)
        playing = self.is_playing()
        state_name = self._state_name()

        if (
            position_ms != self._last_position
            or duration_ms != self._last_duration
            or buffered_ms != self._last_buffered
        ):
            self._last_position = position_ms
            self._last_duration = duration_ms
            self._last_buffered = buffered_ms
            self.position_changed.emit(position_ms, duration_ms, buffered_ms)

        if playing != self._last_playing:
            self._last_playing = playing
            self.playback_state_changed.emit(playing)

        if state_name != self._last_state:
            self._last_state = state_name
            self.state_changed.emit(state_name)

        if self._pending_end:
            self._pending_end = False
            self.end_reached.emit()

        if self._pending_error is not None:
            error_message = self._pending_error
            self._pending_error = None
            self.error_occurred.emit(error_message)

    def _frame_interval_ms(self) -> int:
        if self.current_entry is not None and self.current_entry.fps > 0:
            return max(int(1000 / self.current_entry.fps), 1)
        live_fps = float(self.media_player.get_fps() or 0.0)
        if live_fps > 0:
            return max(int(1000 / live_fps), 1)
        return 40

    def _state_name(self) -> str:
        state = self.media_player.get_state()
        state_name = getattr(state, "name", None)
        if isinstance(state_name, str):
            return state_name.lower()
        return str(state).split(".")[-1].lower()

    @staticmethod
    def _closest_speed(rate: float) -> float:
        return min(PLAYBACK_SPEEDS, key=lambda value: abs(value - rate))

    @staticmethod
    def _stat_value(stats: Any, *names: str) -> float:
        for name in names:
            value = getattr(stats, name, None)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return 0.0
        return 0.0
