from pathlib import Path
from tempfile import TemporaryDirectory
import json
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from manager import FactorioModManager, ManagerError


def git(cwd: Path, *args: str):
    return subprocess.run(["git", *args], cwd=cwd, check=True, text=True, capture_output=True)


def main():
    with TemporaryDirectory() as td_raw:
        td = Path(td_raw)
        remote = td / "remote.git"
        seed = td / "seed"
        clone = td / "clone"
        git(td, "init", "--bare", str(remote))
        seed.mkdir()
        git(seed, "init")
        git(seed, "config", "user.name", "test")
        git(seed, "config", "user.email", "test@example.com")
        (seed / "version.txt").write_text("1", encoding="utf-8")
        git(seed, "add", ".")
        git(seed, "commit", "-m", "v1")
        git(seed, "branch", "-M", "main")
        git(seed, "remote", "add", "origin", str(remote))
        git(seed, "push", "-u", "origin", "main")
        git(td, "clone", "--branch", "main", str(remote), str(clone))

        mods = td / "mods"
        mods.mkdir()
        cfg = td / "cfg.json"
        cfg.write_text(json.dumps({"mods_dir": str(mods), "factorio_version": "2.0"}), encoding="utf-8")
        manager = FactorioModManager(cfg, project_root=clone)

        current = manager.app_update_status(fetch=True)
        assert current["git_repo"] is True
        assert current["update_available"] is False

        (seed / "version.txt").write_text("2", encoding="utf-8")
        git(seed, "add", ".")
        git(seed, "commit", "-m", "v2")
        git(seed, "push")

        pending = manager.app_update_status(fetch=True)
        assert pending["update_available"] is True
        assert pending["behind"] == 1

        pulled = manager.pull_app_update()
        assert pulled["changed"] is True
        assert (clone / "version.txt").read_text(encoding="utf-8") == "2"

        # Per-mod settings.lua detection.
        mod_zip = mods / "demo_1.0.0.zip"
        info = {"name": "demo", "title": "Demo", "version": "1.0.0", "factorio_version": "2.0", "dependencies": ["base >= 2.0"]}
        with zipfile.ZipFile(mod_zip, "w") as archive:
            archive.writestr("demo_1.0.0/info.json", json.dumps(info))
            archive.writestr("demo_1.0.0/settings.lua", "-- settings")
        installed = manager.list_installed()
        demo = next(item for item in installed if item["name"] == "demo")
        assert demo["has_settings"] is True

        # Dirty working tree blocks a pull when another update exists.
        (seed / "version.txt").write_text("3", encoding="utf-8")
        git(seed, "add", ".")
        git(seed, "commit", "-m", "v3")
        git(seed, "push")
        (clone / "local.txt").write_text("dirty", encoding="utf-8")
        try:
            manager.pull_app_update()
        except ManagerError as exc:
            assert "belum di-commit" in str(exc)
        else:
            raise AssertionError("dirty working tree should block pull")

    print("App updater + per-mod settings offline tests: PASS")


if __name__ == "__main__":
    main()
