from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "flet_app.py").read_text(encoding="utf-8")
manager = (ROOT / "manager.py").read_text(encoding="utf-8")

assert 'if mode == "release":' in source
assert 'pull_update_btn.text = "Download & Install"' in source
assert 'result.get("download_url")' in source
assert 'schedule_executable_replace_and_restart' in source
assert '"mode": "release"' in manager
assert 'replacement_path' in manager
print("v3 EXE updater regression: PASS")
