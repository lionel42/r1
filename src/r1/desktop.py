"""Linux desktop launcher of the viewer (``r1 gui --install-desktop``).

pip cannot install files outside the Python environment, so the launcher
is written by a command: a ``.desktop`` file in
``~/.local/share/applications`` and the logo in the user's icon theme.
"""

import logging
import os
import shutil
import subprocess
import sys
from importlib.resources import files
from pathlib import Path

logger = logging.getLogger(__name__)

APP_ID = "r1"
APP_NAME = "R1"
OLD_APP_IDS = ["r1-viewer"]  # earlier names, removed on (un)install
LOGO = files("r1") / "resources" / "logo.svg"


def data_home() -> Path:
    """``$XDG_DATA_HOME``, by default ``~/.local/share``."""
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def desktop_file(app_id: str = APP_ID) -> Path:
    return data_home() / "applications" / f"{app_id}.desktop"


def icon_file(app_id: str = APP_ID) -> Path:
    return data_home() / "icons" / "hicolor" / "scalable" / "apps" / f"{app_id}.svg"


def _remove(app_ids: list[str]) -> list[Path]:
    """Remove the desktop and icon files of ``app_ids``; return those removed."""
    paths = [f(app_id) for app_id in app_ids for f in (desktop_file, icon_file)]
    removed = [path for path in paths if path.exists()]
    for path in removed:
        path.unlink()
    return removed


def desktop_entry(python: str | None = None) -> str:
    """The content of the ``.desktop`` file, starting the viewer with
    ``python`` (default: the running interpreter, so it works from a venv)."""
    python = python or sys.executable
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        "Comment=Plots and calibration chains of the GCwerks R1 propagation\n"
        f'Exec="{python}" -m r1 gui\n'
        f"Icon={APP_ID}\n"
        "Terminal=false\n"
        "Categories=Science;DataVisualization;\n"
    )


def _refresh_caches() -> None:
    """Tell the desktop about the new files, where the tools exist."""
    commands = [
        ["update-desktop-database", str(desktop_file().parent)],
        ["gtk-update-icon-cache", "-q", "-t", str(data_home() / "icons" / "hicolor")],
    ]
    for command in commands:
        if shutil.which(command[0]):
            subprocess.run(command, check=False, capture_output=True)


def install_desktop_entry() -> list[Path]:
    """Write the ``.desktop`` file and the icon, removing those of earlier
    names; return the paths written."""
    for old in _remove(OLD_APP_IDS):
        logger.info(f"removed {old}")
    for path in (desktop_file(), icon_file()):
        path.parent.mkdir(parents=True, exist_ok=True)
    desktop_file().write_text(desktop_entry())
    icon_file().write_bytes(LOGO.read_bytes())
    _refresh_caches()
    return [desktop_file(), icon_file()]


def uninstall_desktop_entry() -> list[Path]:
    """Remove the ``.desktop`` file and the icon; return the removed paths."""
    removed = _remove([APP_ID, *OLD_APP_IDS])
    _refresh_caches()
    return removed
