from __future__ import annotations

import importlib.util
import platform
import sys
from pathlib import Path


def has(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def main():
    root = Path(__file__).resolve().parent
    print("Factorio Mod Manager Pro - Doctor")
    print("Python:", sys.version.split()[0])
    print("OS:", platform.platform())
    print("Project:", root)

    required = {
        "requests": "requests",
        "packaging": "packaging",
        "Flask": "flask",
        "Flet": "flet",
    }
    missing = []
    for label, module in required.items():
        ok = has(module)
        print(f"{label}: {'OK' if ok else 'MISSING'}")
        if not ok:
            missing.append(label)

    if missing:
        print("\nInstall dependencies with: pip install -r requirements.txt")
        return 1

    from storage import app_data_dir
    from manager import FactorioModManager

    manager = FactorioModManager(app_data_dir() / "manager-config.json")
    diag = manager.diagnostics()
    print("\nManager data:", app_data_dir())
    print("Factorio mods dir:", diag["mods_dir"])
    print("Installed mods:", diag["installed_count"])
    print("Dependency issues:", diag["dependency_issue_count"])
    print("Duplicate groups:", len(diag["duplicates"]))
    print("Invalid files:", len(diag["invalid_files"]))
    print("\nDoctor: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
