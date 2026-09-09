from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from app_version import APP_VERSION


def main():
    assert APP_VERSION == "3.0.1"
    flet = (ROOT / "flet_app.py").read_text(encoding="utf-8")
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'version = "3.0.1"' in project
    assert "Pilih warna" in flet
    assert "Kode HEX" in flet
    assert "Pilihan warna" in flet
    assert "palette_colors" in flet
    assert "border_radius=22" in flet
    assert "_install_packaged_exe_on_desktop" in flet
    assert "SHGetFolderPathW" in flet
    assert 'desktop / "FactorioModManager.exe"' in flet
    assert "desktop-exe-version.txt" in flet
    assert "_version_tuple(APP_VERSION) > _version_tuple(installed_version)" in flet
    print("v3.0.1 color/desktop tests: PASS")


if __name__ == "__main__":
    main()
