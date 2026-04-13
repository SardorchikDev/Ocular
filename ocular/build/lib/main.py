from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from app.theme import ConfigManager, ThemeManager
from app.window import MainWindow


def _initialize_x11_threads() -> None:
    if not sys.platform.startswith("linux") or not os.environ.get("DISPLAY"):
        return
    library_name = ctypes.util.find_library("X11")
    if not library_name:
        return
    try:
        x11 = ctypes.CDLL(library_name)
        x11.XInitThreads()
    except OSError as exc:
        logging.getLogger(__name__).debug("XInitThreads unavailable: %s", exc)


def parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ocular",
        description="Minimal desktop video viewer powered by VLC.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        metavar="file",
        help="optional video file paths to open on launch",
    )
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_arguments(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    _initialize_x11_threads()

    app = QApplication(sys.argv)
    app.setApplicationName("Ocular")
    app.setOrganizationName("Ocular")

    config = ConfigManager()
    theme_manager = ThemeManager(config)
    theme_manager.apply(app)

    try:
        window = MainWindow(
            config,
            theme_manager,
            startup_paths=[Path(value).expanduser() for value in args.paths],
        )
    except RuntimeError as exc:
        logging.getLogger(__name__).error("%s", exc)
        return 1
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
