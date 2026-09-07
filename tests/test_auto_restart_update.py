from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from process_restart import current_process_command


def main():
    command = current_process_command()
    assert command
    assert command[0] == sys.executable

    flet = (ROOT / "flet_app.py").read_text(encoding="utf-8")
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "schedule_restart(APP_DIR, delay=0.8)" in flet
    assert "Restarting automatically" in flet
    assert "schedule_restart(APP_DIR, delay=1.0)" in app
    assert "waitForAppRestart" in js
    assert 'version = "2.4.2"' in pyproject
    print("Auto-restart updater tests: PASS")


if __name__ == "__main__":
    main()
