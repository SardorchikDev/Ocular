from __future__ import annotations

import argparse
import ctypes.util
import os
import shlex
import shutil
import subprocess
import sys
import textwrap
import venv
from dataclasses import dataclass
from pathlib import Path

MARKER_BEGIN = "# >>> ocular installer >>>"
MARKER_END = "# <<< ocular installer <<<"


@dataclass(slots=True)
class InstallerPaths:
    repo_root: Path
    source_dir: Path
    install_root: Path
    venv_dir: Path
    bin_dir: Path
    launcher_path: Path
    rc_path: Path
    shell_name: str

    @property
    def venv_python(self) -> Path:
        return self.venv_dir / "bin" / "python"

    @property
    def installed_command(self) -> Path:
        return self.venv_dir / "bin" / "ocular"


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Terminal installer for Ocular.")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="skip the TUI prompt and install immediately",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would happen without creating files",
    )
    return parser.parse_args(argv)


def detect_shell_name() -> str:
    shell_path = os.environ.get("SHELL", "")
    shell_name = Path(shell_path).name.lower()
    return shell_name or "sh"


def detect_rc_path(home: Path, shell_name: str) -> Path:
    if shell_name == "zsh":
        return home / ".zshrc"
    if shell_name == "bash":
        return home / ".bashrc"
    return home / ".profile"


def build_paths() -> InstallerPaths:
    repo_root = Path(__file__).resolve().parent
    source_dir = repo_root / "ocular"
    home = Path.home()
    shell_name = detect_shell_name()
    bin_dir = home / ".local" / "bin"
    return InstallerPaths(
        repo_root=repo_root,
        source_dir=source_dir,
        install_root=home / ".local" / "share" / "ocular",
        venv_dir=home / ".local" / "share" / "ocular" / "venv",
        bin_dir=bin_dir,
        launcher_path=bin_dir / "ocular",
        rc_path=detect_rc_path(home, shell_name),
        shell_name=shell_name,
    )


def detect_vlc_runtime() -> bool:
    return bool(
        shutil.which("vlc")
        or ctypes.util.find_library("vlc")
        or ctypes.util.find_library("libvlc")
    )


def ensure_supported_platform() -> None:
    if os.name != "posix":
        raise RuntimeError("This installer currently supports Linux and macOS style shells.")
    if sys.version_info < (3, 11):
        raise RuntimeError("Python 3.11 or newer is required.")


def ensure_source_tree(paths: InstallerPaths) -> None:
    pyproject_path = paths.source_dir / "pyproject.toml"
    if not pyproject_path.exists():
        raise RuntimeError(f"Could not find {pyproject_path}. Run the installer from the repo root.")


def quote_command(parts: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def run_command(parts: list[str], dry_run: bool) -> None:
    print(f"$ {quote_command(parts)}")
    if dry_run:
        return
    subprocess.run(parts, check=True)


def create_virtualenv(paths: InstallerPaths, dry_run: bool) -> None:
    if paths.venv_python.exists():
        print(f"Reusing virtualenv: {paths.venv_dir}")
        return
    print(f"Creating virtualenv: {paths.venv_dir}")
    if dry_run:
        return
    paths.install_root.mkdir(parents=True, exist_ok=True)
    builder = venv.EnvBuilder(with_pip=True, clear=False, upgrade=False)
    builder.create(str(paths.venv_dir))


def install_package(paths: InstallerPaths, dry_run: bool) -> None:
    run_command(
        [
            str(paths.venv_python),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "pip",
            "setuptools",
            "wheel",
        ],
        dry_run,
    )
    run_command(
        [
            str(paths.venv_python),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--no-build-isolation",
            str(paths.source_dir),
        ],
        dry_run,
    )


def write_launcher(paths: InstallerPaths, dry_run: bool) -> None:
    launcher_text = textwrap.dedent(
        f"""\
        #!/usr/bin/env sh
        exec "{paths.installed_command}" "$@"
        """
    )
    print(f"Writing launcher: {paths.launcher_path}")
    if dry_run:
        return
    paths.bin_dir.mkdir(parents=True, exist_ok=True)
    paths.launcher_path.write_text(launcher_text, encoding="utf-8")
    paths.launcher_path.chmod(0o755)


def path_contains(bin_dir: Path) -> bool:
    path_entries = [entry for entry in os.environ.get("PATH", "").split(os.pathsep) if entry]
    normalized_entries = {str(Path(entry).expanduser()) for entry in path_entries}
    return str(bin_dir) in normalized_entries


def ensure_path_export(paths: InstallerPaths, dry_run: bool) -> bool:
    if path_contains(paths.bin_dir):
        print(f"PATH already contains {paths.bin_dir}")
        return False

    if paths.rc_path.exists():
        contents = paths.rc_path.read_text(encoding="utf-8")
    else:
        contents = ""

    if MARKER_BEGIN in contents or str(paths.bin_dir) in contents:
        print(f"PATH export already present in {paths.rc_path}")
        return False

    snippet = textwrap.dedent(
        f"""
        {MARKER_BEGIN}
        export PATH="$HOME/.local/bin:$PATH"
        {MARKER_END}
        """
    ).lstrip()
    print(f"Updating shell config: {paths.rc_path}")
    if dry_run:
        return True

    paths.rc_path.parent.mkdir(parents=True, exist_ok=True)
    with paths.rc_path.open("a", encoding="utf-8") as handle:
        if contents and not contents.endswith("\n"):
            handle.write("\n")
        handle.write(snippet)
    return True


def draw_fallback_prompt(paths: InstallerPaths, vlc_ready: bool) -> str:
    print("OCULAR INSTALLER")
    print(f"Source:   {paths.source_dir}")
    print(f"Install:  {paths.venv_dir}")
    print(f"Launcher: {paths.launcher_path}")
    print(f"Shell rc: {paths.rc_path}")
    print(f"libVLC:   {'detected' if vlc_ready else 'not detected'}")
    print("Choose: [I]nstall  [D]ry run  [Q]uit")

    while True:
        choice = input("> ").strip().lower()
        if choice in {"", "i", "install"}:
            return "install"
        if choice in {"d", "dry", "dry-run"}:
            return "dry-run"
        if choice in {"q", "quit"}:
            return "quit"


def draw_tui(paths: InstallerPaths, vlc_ready: bool) -> str:
    try:
        import curses
    except ImportError:
        return draw_fallback_prompt(paths, vlc_ready)

    def _screen(stdscr: object) -> str:
        window = stdscr
        curses.curs_set(0)
        window.keypad(True)

        while True:
            window.erase()
            height, width = window.getmaxyx()
            lines = [
                "OCULAR INSTALLER",
                "",
                f"Source   : {paths.source_dir}",
                f"Install  : {paths.venv_dir}",
                f"Launcher : {paths.launcher_path}",
                f"Shell rc : {paths.rc_path}",
                f"libVLC   : {'detected' if vlc_ready else 'not detected'}",
                "",
                "This creates an isolated venv and a global `ocular` launcher.",
                "",
                "Enter / I  install",
                "D          dry run",
                "Q / Esc    quit",
            ]

            top = max((height - len(lines)) // 2, 1)
            for index, line in enumerate(lines):
                window.addnstr(top + index, 3, line, max(width - 6, 1))
            window.refresh()

            key = window.getch()
            if key in {10, 13, ord("i"), ord("I")}:
                return "install"
            if key in {ord("d"), ord("D")}:
                return "dry-run"
            if key in {27, ord("q"), ord("Q")}:
                return "quit"

    try:
        return curses.wrapper(_screen)
    except curses.error:
        return draw_fallback_prompt(paths, vlc_ready)


def choose_action(paths: InstallerPaths, vlc_ready: bool, auto_yes: bool) -> str:
    if auto_yes:
        return "install"
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return "install"
    return draw_tui(paths, vlc_ready)


def print_summary(paths: InstallerPaths, path_updated: bool) -> None:
    print()
    print("Install complete.")
    print(f"Launcher: {paths.launcher_path}")
    print('Use it anywhere like: ocular "movie.mkv"')
    if path_updated:
        print(f"Reload your shell to pick up PATH changes: source {paths.rc_path}")
    elif not path_contains(paths.bin_dir):
        print(f"Run it directly once with: {paths.launcher_path} \"movie.mkv\"")


def perform_install(paths: InstallerPaths, dry_run: bool) -> int:
    ensure_supported_platform()
    ensure_source_tree(paths)
    create_virtualenv(paths, dry_run)
    install_package(paths, dry_run)
    write_launcher(paths, dry_run)
    path_updated = ensure_path_export(paths, dry_run)

    if dry_run:
        print()
        print("Dry run complete.")
        return 0

    print_summary(paths, path_updated)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_arguments(sys.argv[1:] if argv is None else argv)
    paths = build_paths()
    vlc_ready = detect_vlc_runtime()
    action = "dry-run" if args.dry_run else choose_action(paths, vlc_ready, args.yes)

    if action == "quit":
        print("Installer cancelled.")
        return 0

    if not vlc_ready:
        print("Warning: VLC/libVLC was not detected. Install VLC if playback fails.")
        print()

    try:
        return perform_install(paths, dry_run=action == "dry-run")
    except subprocess.CalledProcessError as exc:
        print(f"Installer failed while running: {quote_command(exc.cmd)}", file=sys.stderr)
        return exc.returncode or 1
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
