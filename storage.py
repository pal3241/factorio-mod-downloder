from __future__ import annotations

import os
import platform
from pathlib import Path

APP_NAME = "FactorioModManagerPro"


def app_data_dir() -> Path:
    # Flet 0.86+ packaged applications expose a writable app-private data dir.
    flet_data = os.getenv("FLET_APP_STORAGE_DATA")
    if flet_data:
        path = Path(flet_data)
    else:
        system = platform.system().lower()
        if system == "windows":
            base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
            path = Path(base) / APP_NAME if base else Path.home() / f".{APP_NAME}"
        elif system == "darwin":
            path = Path.home() / "Library" / "Application Support" / APP_NAME
        else:
            xdg = os.getenv("XDG_DATA_HOME")
            path = Path(xdg) / APP_NAME if xdg else Path.home() / ".local" / "share" / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path
