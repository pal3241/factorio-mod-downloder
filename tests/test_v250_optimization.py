from pathlib import Path
import sys
import tempfile
import zipfile
import json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from manager import FactorioModManager


def make_mod(path: Path):
    info = {
        "name": "cache-test",
        "title": "Cache Test",
        "version": "1.0.0",
        "factorio_version": "2.0",
        "dependencies": ["base >= 2.0"],
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("cache-test_1.0.0/info.json", json.dumps(info))
        archive.writestr("cache-test_1.0.0/settings.lua", "data:extend({})")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        mods = base / "mods"
        mods.mkdir()
        make_mod(mods / "cache-test_1.0.0.zip")
        cfg = base / "config.json"
        cfg.write_text(json.dumps({"mods_dir": str(mods), "factorio_version": "2.0"}), encoding="utf-8")
        manager = FactorioModManager(cfg, project_root=ROOT)

        first = manager.list_installed()
        second = manager.list_installed()
        assert first == second
        assert first[0]["has_settings"] is True
        assert manager._installed_cache_signature is not None

        state = manager.dashboard_state()
        assert state["mods"][0]["name"] == "cache-test"
        assert not state["issues"]["missing"]
        assert not state["duplicates"]

    flet = (ROOT / "flet_app.py").read_text(encoding="utf-8")
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "#070B14" in flet
    assert "#09111E" in flet
    assert "#4EA1FF" in flet
    assert "--sidebar: #08111F" in css
    assert "#4ea1ff" in css.lower()
    assert 'version = "3.0.1"' in project
    print("v2.5.0 optimization/theme tests: PASS")


if __name__ == "__main__":
    main()
