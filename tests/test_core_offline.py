from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from manager import FactorioModManager


def make_mod(path: Path, name: str, version: str, deps=None):
    info = {
        "name": name,
        "version": version,
        "title": name.title(),
        "author": "test",
        "factorio_version": "2.0",
        "dependencies": deps or ["base >= 2.0"],
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{name}_{version}/info.json", json.dumps(info))


def main():
    with TemporaryDirectory() as td:
        td = Path(td)
        mods = td / "mods"
        mods.mkdir()
        manager = FactorioModManager(td / "manager-config.json")
        manager.save_config({"mods_dir": str(mods), "factorio_version": "2.0"})

        make_mod(mods / "alpha_1.0.0.zip", "alpha", "1.0.0", ["base >= 2.0", "beta >= 1.0.0"])
        make_mod(mods / "alpha_0.9.0.zip", "alpha", "0.9.0")
        make_mod(mods / "beta_1.1.0.zip", "beta", "1.1.0")
        (mods / "broken.zip").write_bytes(b"not-a-zip")

        manager.set_enabled("alpha", True)
        manager.set_enabled("beta", True)

        assert len(manager.list_installed()) == 3
        assert len(manager.duplicate_mods()) == 1
        assert len(manager.invalid_mod_files()) == 1
        assert sum(len(v) for v in manager.dependency_issues().values()) == 0

        profile = manager.save_profile("Test Profile")
        assert profile["mod_count"] == 3
        assert len(manager.list_profiles()) == 1

        backup = manager.backup_state("test")
        assert Path(backup["manifest"]).exists()

        cleaned = manager.clean_duplicates()
        assert cleaned["removed"] == ["alpha_0.9.0.zip"]
        assert len(manager.list_installed()) == 2

    print("Core offline tests: PASS")


if __name__ == "__main__":
    main()
