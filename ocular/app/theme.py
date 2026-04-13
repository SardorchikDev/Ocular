from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Mapping

from PyQt6.QtCore import QByteArray, QObject, QSize, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication

LOGGER = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".config" / "ocular"
CONFIG_PATH = CONFIG_DIR / "config.json"


@dataclass(slots=True)
class WindowConfig:
    x: int = 100
    y: int = 100
    w: int = 1280
    h: int = 720


@dataclass(slots=True)
class AppConfig:
    theme: str = "dark"
    volume: int = 80
    window: WindowConfig = field(default_factory=WindowConfig)
    last_dir: str = str(Path.home() / "Videos")
    speed: float = 1.0

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["last_dir"] = str(Path(self.last_dir))
        return payload


@dataclass(frozen=True, slots=True)
class ThemeTokens:
    bg: str
    surface: str
    border: str
    text: str
    subtext: str
    accent: str
    accent_dim: str
    thumb: str


THEMES: dict[str, ThemeTokens] = {
    "dark": ThemeTokens(
        bg="#090b0e",
        surface="#11151a",
        border="#252c34",
        text="#f3f5f7",
        subtext="#7f8893",
        accent="#78beff",
        accent_dim="#16212c",
        thumb="#ffffff",
    ),
    "light": ThemeTokens(
        bg="#eceff3",
        surface="#ffffff",
        border="#c4ccd4",
        text="#101418",
        subtext="#5f6873",
        accent="#0b74d8",
        accent_dim="#dde9f4",
        thumb="#101418",
    ),
}


_ICON_TEMPLATES: dict[str, str] = {
    "play": """
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <polygon fill="{color}" points="8,5 19,12 8,19" />
        </svg>
    """,
    "pause": """
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <rect fill="{color}" x="7" y="5" width="4" height="14" rx="1" />
          <rect fill="{color}" x="13" y="5" width="4" height="14" rx="1" />
        </svg>
    """,
    "previous": """
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <rect fill="{color}" x="6" y="5" width="2" height="14" rx="1" />
          <polygon fill="{color}" points="18,5 9,12 18,19" />
        </svg>
    """,
    "next": """
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <rect fill="{color}" x="16" y="5" width="2" height="14" rx="1" />
          <polygon fill="{color}" points="6,5 15,12 6,19" />
        </svg>
    """,
    "rewind": """
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <polygon fill="{color}" points="12,6 6,12 12,18" />
          <polygon fill="{color}" points="19,6 13,12 19,18" />
        </svg>
    """,
    "forward": """
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <polygon fill="{color}" points="5,6 11,12 5,18" />
          <polygon fill="{color}" points="12,6 18,12 12,18" />
        </svg>
    """,
    "volume": """
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <polygon fill="{color}" points="5,10 9,10 14,6 14,18 9,14 5,14" />
          <path d="M16 9 C17.8 10.6 17.8 13.4 16 15" fill="none"
                stroke="{color}" stroke-width="2" stroke-linecap="round" />
          <path d="M18 6.5 C21 9 21 15 18 17.5" fill="none"
                stroke="{color}" stroke-width="2" stroke-linecap="round" />
        </svg>
    """,
    "mute": """
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <polygon fill="{color}" points="5,10 9,10 14,6 14,18 9,14 5,14" />
          <path d="M17 8 L21 16" stroke="{color}" stroke-width="2"
                stroke-linecap="round" />
          <path d="M21 8 L17 16" stroke="{color}" stroke-width="2"
                stroke-linecap="round" />
        </svg>
    """,
    "fullscreen": """
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <path d="M8 4 H4 V8" fill="none" stroke="{color}" stroke-width="2"
                stroke-linecap="round" stroke-linejoin="round" />
          <path d="M16 4 H20 V8" fill="none" stroke="{color}" stroke-width="2"
                stroke-linecap="round" stroke-linejoin="round" />
          <path d="M8 20 H4 V16" fill="none" stroke="{color}" stroke-width="2"
                stroke-linecap="round" stroke-linejoin="round" />
          <path d="M16 20 H20 V16" fill="none" stroke="{color}" stroke-width="2"
                stroke-linecap="round" stroke-linejoin="round" />
        </svg>
    """,
    "fullscreen-exit": """
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <path d="M8 9 H4 V4" fill="none" stroke="{color}" stroke-width="2"
                stroke-linecap="round" stroke-linejoin="round" />
          <path d="M16 9 H20 V4" fill="none" stroke="{color}" stroke-width="2"
                stroke-linecap="round" stroke-linejoin="round" />
          <path d="M8 15 H4 V20" fill="none" stroke="{color}" stroke-width="2"
                stroke-linecap="round" stroke-linejoin="round" />
          <path d="M16 15 H20 V20" fill="none" stroke="{color}" stroke-width="2"
                stroke-linecap="round" stroke-linejoin="round" />
        </svg>
    """,
    "minimize": """
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <rect fill="{color}" x="6" y="15" width="12" height="2" rx="1" />
        </svg>
    """,
    "maximize": """
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <rect x="6" y="6" width="12" height="12" fill="none"
                stroke="{color}" stroke-width="2" rx="1" />
        </svg>
    """,
    "restore": """
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <rect x="8" y="5" width="10" height="10" fill="none"
                stroke="{color}" stroke-width="2" rx="1" />
          <path d="M6 9 V18 H15" fill="none" stroke="{color}" stroke-width="2"
                stroke-linecap="round" stroke-linejoin="round" />
        </svg>
    """,
    "close": """
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <path d="M7 7 L17 17" stroke="{color}" stroke-width="2"
                stroke-linecap="round" />
          <path d="M17 7 L7 17" stroke="{color}" stroke-width="2"
                stroke-linecap="round" />
        </svg>
    """,
    "playlist": """
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <rect fill="{color}" x="4" y="6" width="10" height="2" rx="1" />
          <rect fill="{color}" x="4" y="11" width="10" height="2" rx="1" />
          <rect fill="{color}" x="4" y="16" width="10" height="2" rx="1" />
          <polygon fill="{color}" points="17,10 21,12 17,14" />
        </svg>
    """,
    "folder": """
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <path d="M4 7 H9 L11 9 H20 V18 H4 Z" fill="none" stroke="{color}"
                stroke-width="2" stroke-linejoin="round" />
          <path d="M4 10 H20" fill="none" stroke="{color}" stroke-width="2"
                stroke-linecap="round" />
        </svg>
    """,
    "sun": """
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <circle cx="12" cy="12" r="4" fill="none" stroke="{color}" stroke-width="2" />
          <path d="M12 2 V5" fill="none" stroke="{color}" stroke-width="2"
                stroke-linecap="round" />
          <path d="M12 19 V22" fill="none" stroke="{color}" stroke-width="2"
                stroke-linecap="round" />
          <path d="M2 12 H5" fill="none" stroke="{color}" stroke-width="2"
                stroke-linecap="round" />
          <path d="M19 12 H22" fill="none" stroke="{color}" stroke-width="2"
                stroke-linecap="round" />
          <path d="M5.2 5.2 L7.3 7.3" fill="none" stroke="{color}" stroke-width="2"
                stroke-linecap="round" />
          <path d="M16.7 16.7 L18.8 18.8" fill="none" stroke="{color}" stroke-width="2"
                stroke-linecap="round" />
          <path d="M5.2 18.8 L7.3 16.7" fill="none" stroke="{color}" stroke-width="2"
                stroke-linecap="round" />
          <path d="M16.7 7.3 L18.8 5.2" fill="none" stroke="{color}" stroke-width="2"
                stroke-linecap="round" />
        </svg>
    """,
    "moon": """
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <path d="M16.5 3.8 C13 4.3 10.2 7.4 10.2 11.1 C10.2 15.2 13.5 18.5 17.6 18.5
                   C18.6 18.5 19.5 18.3 20.4 17.9 C19.1 20.2 16.6 21.8 13.8 21.8
                   C9.5 21.8 6 18.3 6 14 C6 9.9 9.1 6.5 13.1 6.1 C14.3 5.9 15.5 5.9 16.5 3.8 Z"
                fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round" />
        </svg>
    """,
}


def format_timestamp(milliseconds: int) -> str:
    total_seconds = max(milliseconds, 0) // 1000
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def blend_color(color: QColor, alpha: int) -> QColor:
    blended = QColor(color)
    blended.setAlpha(alpha)
    return blended


def render_svg_icon(name: str, color: QColor | str, size: int = 18) -> QIcon:
    if name not in _ICON_TEMPLATES:
        raise KeyError(f"Unknown icon template: {name}")
    color_name = color.name() if isinstance(color, QColor) else color
    svg = _ICON_TEMPLATES[name].format(color=color_name).encode("utf-8")
    renderer = QSvgRenderer(QByteArray(svg))
    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


class ConfigManager:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or CONFIG_PATH
        self.data = self.load()

    def load(self) -> AppConfig:
        defaults = AppConfig()
        default_window = defaults.window
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write(defaults)
            return defaults
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            LOGGER.error("Failed to read config %s: %s", self.path, exc)
            self._write(defaults)
            return defaults
        if not isinstance(payload, Mapping):
            payload = {}

        window_payload = payload.get("window", {})
        if not isinstance(window_payload, Mapping):
            window_payload = {}

        theme_name = str(payload.get("theme", defaults.theme))
        if theme_name not in THEMES:
            theme_name = defaults.theme

        last_dir = Path(str(payload.get("last_dir", defaults.last_dir))).expanduser()
        if not last_dir.exists():
            last_dir = Path(defaults.last_dir)

        config = AppConfig(
            theme=theme_name,
            volume=self._clamp_int(payload.get("volume", defaults.volume), 0, 100),
            window=WindowConfig(
                x=self._safe_int(window_payload.get("x", default_window.x)),
                y=self._safe_int(window_payload.get("y", default_window.y)),
                w=max(self._safe_int(window_payload.get("w", default_window.w)), 640),
                h=max(self._safe_int(window_payload.get("h", default_window.h)), 400),
            ),
            last_dir=str(last_dir),
            speed=self._clamp_float(payload.get("speed", defaults.speed), 0.25, 2.0),
        )
        return config

    def save(self) -> None:
        self._write(self.data)

    def update_theme(self, theme_name: str) -> None:
        if theme_name in THEMES:
            self.data.theme = theme_name
            self.save()

    def update_volume(self, volume: int) -> None:
        self.data.volume = self._clamp_int(volume, 0, 100)
        self.save()

    def update_speed(self, speed: float) -> None:
        self.data.speed = self._clamp_float(speed, 0.25, 2.0)
        self.save()

    def update_last_dir(self, directory: Path) -> None:
        self.data.last_dir = str(directory.expanduser())
        self.save()

    def update_window(self, x: int, y: int, w: int, h: int) -> None:
        self.data.window = WindowConfig(x=x, y=y, w=max(w, 640), h=max(h, 400))
        self.save()

    def _write(self, config: AppConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.write_text(
                json.dumps(config.to_dict(), indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            LOGGER.error("Failed to write config %s: %s", self.path, exc)

    @staticmethod
    def _safe_int(value: object) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _clamp_int(cls, value: object, minimum: int, maximum: int) -> int:
        return max(min(cls._safe_int(value), maximum), minimum)

    @staticmethod
    def _clamp_float(value: object, minimum: float, maximum: float) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = minimum
        return max(min(numeric, maximum), minimum)


class ThemeManager(QObject):
    theme_changed = pyqtSignal(str)

    def __init__(self, config: ConfigManager) -> None:
        super().__init__()
        self._config = config
        self._theme_name = config.data.theme if config.data.theme in THEMES else "dark"

    @property
    def theme_name(self) -> str:
        return self._theme_name

    def tokens(self, theme_name: str | None = None) -> ThemeTokens:
        return THEMES[theme_name or self._theme_name]

    def color(self, token_name: str) -> QColor:
        value = getattr(self.tokens(), token_name)
        return QColor(value)

    def set_theme(self, theme_name: str, app: QApplication | None = None) -> None:
        if theme_name not in THEMES or theme_name == self._theme_name:
            return
        self._theme_name = theme_name
        self._config.update_theme(theme_name)
        if app is not None:
            self.apply(app)
        self.theme_changed.emit(theme_name)

    def toggle_theme(self, app: QApplication | None = None) -> None:
        next_theme = "light" if self._theme_name == "dark" else "dark"
        self.set_theme(next_theme, app)

    def apply(self, app: QApplication) -> None:
        app.setStyle("Fusion")
        app.setPalette(self.build_palette())
        app.setStyleSheet(self.build_stylesheet())

    def build_palette(self) -> QPalette:
        theme = self.tokens()
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(theme.bg))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(theme.text))
        palette.setColor(QPalette.ColorRole.Base, QColor(theme.surface))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(theme.bg))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(theme.surface))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor(theme.text))
        palette.setColor(QPalette.ColorRole.Text, QColor(theme.text))
        palette.setColor(QPalette.ColorRole.Button, QColor(theme.surface))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(theme.text))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(theme.accent))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(theme.thumb))
        palette.setColor(QPalette.ColorRole.BrightText, QColor(theme.thumb))
        palette.setColor(QPalette.ColorRole.Link, QColor(theme.accent))
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(theme.subtext))
        palette.setColor(QPalette.ColorRole.Mid, QColor(theme.border))
        palette.setColor(QPalette.ColorRole.Midlight, QColor(theme.accent_dim))
        return palette

    def build_stylesheet(self) -> str:
        theme = self.tokens()
        return f"""
        QWidget {{
            background: {theme.bg};
            color: {theme.text};
            font-family: "SF Pro Display", "SF Pro Text", "Symbols Nerd Font Mono",
                         "Iosevka Nerd Font Propo", "JetBrainsMono Nerd Font",
                         "Inter", "Noto Sans", "DejaVu Sans";
            font-size: 12px;
        }}
        QWidget#frame {{
            background: {theme.bg};
            border: 1px solid {theme.border};
            border-radius: 0px;
        }}
        QWidget#TitleBar,
        QWidget#ControlsBar,
        QWidget#PlaylistSidebar,
        QWidget#VideoPane {{
            background: {theme.surface};
        }}
        QWidget#TitleBar {{
            border-bottom: 2px solid {theme.border};
            padding-left: 4px;
            padding-right: 4px;
        }}
        QWidget#ControlsBar {{
            border-top: 2px solid {theme.border};
        }}
        QWidget#PlaylistSidebar {{
            border-left: 2px solid {theme.border};
        }}
        QWidget#VideoPane {{
            background: {theme.bg};
        }}
        QLabel#Subtle {{
            color: {theme.subtext};
            font-size: 11px;
            font-weight: 600;
        }}
        QLabel#WindowTitle {{
            color: {theme.text};
            background: transparent;
            font-size: 13px;
            font-weight: 700;
            padding-left: 10px;
            padding-right: 10px;
        }}
        QLabel#TimelineLabel {{
            color: {theme.subtext};
            font-size: 11px;
            font-weight: 600;
        }}
        QMenu {{
            background: {theme.surface};
            border: 1px solid {theme.border};
            border-radius: 0px;
            padding: 8px 0;
        }}
        QMenu::item {{
            border-radius: 0px;
            padding: 10px 18px;
        }}
        QMenu::item:selected {{
            background: {theme.accent_dim};
            color: {theme.text};
        }}
        QToolTip {{
            background: {theme.surface};
            color: {theme.text};
            border: 1px solid {theme.border};
            padding: 6px 8px;
        }}
        QToolButton,
        QPushButton,
        QComboBox {{
            background: transparent;
            border: 1px solid transparent;
            border-radius: 0px;
            color: {theme.text};
            padding: 4px 10px;
        }}
        QToolButton:hover,
        QPushButton:hover,
        QComboBox:hover {{
            background: {theme.accent_dim};
            border-color: {theme.border};
        }}
        QToolButton:pressed,
        QPushButton:pressed,
        QComboBox:on {{
            background: {theme.accent_dim};
        }}
        QToolButton#ToolbarButton {{
            background: transparent;
            border: 1px solid {theme.border};
        }}
        QToolButton#ToolbarButton:hover {{
            background: {theme.accent_dim};
            border-color: {theme.accent};
        }}
        QToolButton#TransportButton {{
            background: {theme.surface};
            border: 1px solid {theme.border};
        }}
        QToolButton#TransportButton:hover {{
            background: {theme.accent_dim};
            border-color: {theme.accent};
        }}
        QToolButton#PrimaryTransportButton {{
            background: {theme.accent_dim};
            border: 1px solid {theme.accent};
        }}
        QToolButton#PrimaryTransportButton:hover {{
            background: {theme.accent_dim};
            border-color: {theme.accent};
        }}
        QToolButton#CloseButton {{
            background: transparent;
            border: 1px solid {theme.border};
            border-radius: 0px;
            padding: 0px;
        }}
        QToolButton#CloseButton:hover {{
            background: {theme.accent_dim};
            border-color: {theme.accent};
        }}
        QTreeWidget {{
            background: {theme.surface};
            border: none;
            outline: none;
            padding: 4px;
        }}
        QTreeWidget::item {{
            border-top: 1px solid {theme.border};
            border-bottom: 1px solid transparent;
            border-left: 3px solid transparent;
            border-right: none;
            border-radius: 0px;
            padding: 10px 8px;
            height: 76px;
        }}
        QTreeWidget::item:selected {{
            background: {theme.accent_dim};
            border-left: 3px solid {theme.accent};
            border-top: 1px solid {theme.border};
            color: {theme.text};
        }}
        QHeaderView::section {{
            background: {theme.surface};
            color: {theme.subtext};
            border: none;
            border-bottom: 2px solid {theme.border};
            padding: 8px 6px;
            font-size: 11px;
            font-weight: 700;
        }}
        QScrollBar:vertical {{
            background: transparent;
            width: 10px;
            margin: 4px;
        }}
        QScrollBar::handle:vertical {{
            background: {theme.border};
            border-radius: 0px;
            min-height: 30px;
        }}
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical,
        QScrollBar::add-page:vertical,
        QScrollBar::sub-page:vertical {{
            background: transparent;
            border: none;
        }}
        QSplitter::handle {{
            background: {theme.border};
            width: 2px;
        }}
        QComboBox#SpeedChooser {{
            min-height: 36px;
            background: {theme.surface};
            border: 1px solid {theme.border};
            padding-left: 10px;
            padding-right: 16px;
        }}
        QComboBox#SpeedChooser::drop-down {{
            border: none;
            width: 14px;
        }}
        QComboBox#SpeedChooser::down-arrow {{
            image: none;
            width: 0px;
            height: 0px;
        }}
        """
