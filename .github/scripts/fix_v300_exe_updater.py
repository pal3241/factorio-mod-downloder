from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
path = ROOT / "flet_app.py"
text = path.read_text(encoding="utf-8")
old = '''                if not result.get("git_repo"):\n                    app_update_text.value = result.get("message", "Not a Git clone.")\n                    app_update_text.color = "#e4b65f"\n                    pull_update_btn.disabled = True\n                elif result.get("update_available"):\n                    app_update_text.value = f'Update available: {result["local_short"]} → {result["remote_short"]} · {result["behind"]} commit(s) · {result.get("latest_subject") or ""}'\n                    app_update_text.color = "#e4b65f"\n                    pull_update_btn.disabled = bool(result.get("dirty") or result.get("ahead"))\n                    if result.get("dirty"):\n                        app_update_text.value += " · local changes detected; commit/stash first"\n                else:\n                    app_update_text.value = f'Up to date · {result.get("local_short", "?")}'\n                    app_update_text.color = "#8fbf75"\n                    pull_update_btn.disabled = True\n'''
new = '''                mode = result.get("mode")\n                if mode == "release":\n                    if result.get("update_available"):\n                        size_mb = int(result.get("asset_size") or 0) / (1024 * 1024)\n                        app_update_text.value = f'EXE update available: v{result.get("current_version", "?")} → v{result.get("latest_version", "?")} · {size_mb:.1f} MB · {result.get("latest_subject") or ""}'\n                        app_update_text.color = "#e4b65f"\n                        pull_update_btn.text = "Download & Install"\n                        pull_update_btn.disabled = not bool(result.get("download_url"))\n                    else:\n                        app_update_text.value = f'Up to date · v{result.get("current_version", "?")}'\n                        app_update_text.color = "#8fbf75"\n                        pull_update_btn.text = "Download & Install"\n                        pull_update_btn.disabled = True\n                elif not result.get("git_repo"):\n                    app_update_text.value = result.get("message", "Not a Git clone.")\n                    app_update_text.color = "#e4b65f"\n                    pull_update_btn.disabled = True\n                elif result.get("update_available"):\n                    app_update_text.value = f'Update available: {result["local_short"]} → {result["remote_short"]} · {result["behind"]} commit(s) · {result.get("latest_subject") or ""}'\n                    app_update_text.color = "#e4b65f"\n                    pull_update_btn.text = "Pull Update"\n                    pull_update_btn.disabled = bool(result.get("dirty") or result.get("ahead"))\n                    if result.get("dirty"):\n                        app_update_text.value += " · local changes detected; commit/stash first"\n                else:\n                    app_update_text.value = f'Up to date · {result.get("local_short", "?")}'\n                    app_update_text.color = "#8fbf75"\n                    pull_update_btn.text = "Pull Update"\n                    pull_update_btn.disabled = True\n'''
if old not in text:
    raise SystemExit("Updater block not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")

# Make packaged-download status wording accurate.
text = path.read_text(encoding="utf-8")
text = text.replace('app_update_text.value = "Pulling update..."', 'app_update_text.value = "Downloading / applying update..."', 1)
path.write_text(text, encoding="utf-8")

# Add regression test.
test = ROOT / "tests" / "test_v300_exe_updater.py"
test.write_text(r'''from pathlib import Path

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
''', encoding="utf-8")

print("Applied v3.0.0 packaged updater fix")
