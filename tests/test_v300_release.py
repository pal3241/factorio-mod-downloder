from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]

from manager import FactorioModManager, ManagerError
from app_version import APP_VERSION


def main():
    assert APP_VERSION == "3.0.0"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        mgr = FactorioModManager(root / "config.json", project_root=ROOT)
        cfg = mgr.save_config({
            "mods_dir": str(root / "mods"),
            "ui_menu_color": "#123456",
            "ui_background_color": "#050A10",
            "ui_accent_color": "#55AAFF",
        })
        assert cfg["ui_menu_color"] == "#123456"
        try:
            mgr.save_config({"ui_menu_color": "blue"})
        except ManagerError:
            pass
        else:
            raise AssertionError("invalid color accepted")

    flet = (ROOT / "flet_app.py").read_text(encoding="utf-8")
    manager = (ROOT / "manager.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "windows-exe-release.yml").read_text(encoding="utf-8")
    assert "Menu / sidebar color" in flet
    assert "Information\", \"Downloads\", \"Dependencies\", \"Changelog\", \"Metrics" in flet
    assert "schedule_executable_replace_and_restart" in flet
    assert "_release_update_status" in manager
    assert "flet pack flet_app.py" in workflow
    assert not (ROOT / "run_app.bat").exists()
    print("v3.0.0 release tests: PASS")


if __name__ == "__main__":
    main()
