from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: Path, old: str, new: str):
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected text not found in {path}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


process_restart_source = r"""from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path


def current_process_command() -> list[str]:
    # Return a command that starts the current application again.
    if getattr(sys, "frozen", False):
        return [sys.executable, *sys.argv[1:]]

    argv0 = Path(sys.argv[0])
    if not argv0.is_absolute():
        argv0 = (Path.cwd() / argv0).resolve()
    return [sys.executable, str(argv0), *sys.argv[1:]]


def schedule_restart(project_root: Path | str | None = None, delay: float = 0.8) -> dict:
    # Schedule a clean restart without blocking the current UI response.
    cwd = str(Path(project_root or Path.cwd()).resolve())
    command = current_process_command()

    def restart_worker():
        env = os.environ.copy()
        env["FMM_RESTART_COMMAND"] = json.dumps(command)
        env["FMM_RESTART_CWD"] = cwd

        code = r'''
import json
import os
import subprocess
import time

time.sleep(0.9)
cmd = json.loads(os.environ.pop("FMM_RESTART_COMMAND"))
cwd = os.environ.pop("FMM_RESTART_CWD")
kwargs = {
    "cwd": cwd,
    "env": os.environ.copy(),
    "close_fds": True,
}
if os.name == "nt":
    kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
else:
    kwargs["start_new_session"] = True
subprocess.Popen(cmd, **kwargs)
'''

        kwargs = {
            "cwd": cwd,
            "env": env,
            "close_fds": True,
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True

        subprocess.Popen([sys.executable, "-c", code], **kwargs)
        os._exit(0)

    timer = threading.Timer(max(0.1, float(delay)), restart_worker)
    timer.daemon = True
    timer.start()
    return {"scheduled": True, "delay": float(delay), "command": command, "cwd": cwd}
"""
(ROOT / "process_restart.py").write_text(process_restart_source, encoding="utf-8")

# Flet app: restart automatically after a successful pull.
flet_path = ROOT / "flet_app.py"
replace_once(
    flet_path,
    'from storage import app_data_dir\n',
    'from storage import app_data_dir\nfrom process_restart import schedule_restart\n',
)
replace_once(
    flet_path,
    '''                if result.get("changed"):\n                    after = result.get("after") or {}\n                    app_update_text.value = f'Updated to {after.get("local_short", "new commit")}. Restart Factorio Mod Manager to load the new code.'\n                    app_update_text.color = "#8fbf75"\n                    self.notify("Update pulled successfully. Restart the app to apply it.")\n                else:\n                    app_update_text.value = "Already up to date."\n                    app_update_text.color = "#8fbf75"\n''',
    '''                if result.get("changed"):\n                    after = result.get("after") or {}\n                    app_update_text.value = f'Updated to {after.get("local_short", "new commit")}. Restarting automatically...'\n                    app_update_text.color = "#8fbf75"\n                    self.notify("Update pulled successfully. Restarting Factorio Mod Manager...")\n                    self.page.update()\n                    schedule_restart(APP_DIR, delay=0.8)\n                    return\n                else:\n                    app_update_text.value = "Already up to date."\n                    app_update_text.color = "#8fbf75"\n''',
)

# Flask web: schedule the backend restart only after pull succeeds.
app_path = ROOT / "app.py"
replace_once(
    app_path,
    'from storage import app_data_dir\n',
    'from storage import app_data_dir\nfrom process_restart import schedule_restart\n',
)
replace_once(
    app_path,
    '''@app.post("/api/app-update/pull")\ndef app_update_pull():\n    try:\n        return ok(result=manager.pull_app_update())\n    except ManagerError as exc:\n        return fail(exc)\n''',
    '''@app.post("/api/app-update/pull")\ndef app_update_pull():\n    try:\n        result = manager.pull_app_update()\n        restarting = bool(result.get("changed"))\n        if restarting:\n            schedule_restart(APP_DIR, delay=1.0)\n        return ok(result=result, restarting=restarting)\n    except ManagerError as exc:\n        return fail(exc)\n''',
)

# Web UI: communicate automatic restart and reload when the server comes back.
js_path = ROOT / "static" / "app.js"
replace_once(
    js_path,
    '''async function pullAppUpdate() {\n    const button = $("pullAppUpdateBtn");\n    const statusEl = $("appUpdateStatus");\n    busy(button, true, "Pulling...");\n    try {\n        const data = await api("/api/app-update/pull", {method:"POST", body:"{}"});\n        if (data.result.changed) {\n            const after = data.result.after || {};\n            statusEl.textContent = `Updated to ${after.local_short || "new commit"}. Restart Factorio Mod Manager to load the new code.`;\n            toast("Update pulled. Restart the app to apply it.");\n        } else {\n            statusEl.textContent = "Already up to date.";\n            toast("Already up to date.");\n        }\n    } catch(err) {\n        statusEl.textContent = err.message;\n        toast(err.message, "error");\n    } finally { button.disabled = true; }\n}\n''',
    '''async function waitForAppRestart(attempt = 0) {\n    if (attempt > 30) {\n        const statusEl = $("appUpdateStatus");\n        statusEl.textContent = "Update installed, but the restarted server did not respond yet. Refresh this page manually.";\n        return;\n    }\n    try {\n        const response = await fetch(`/api/config?restart_check=${Date.now()}`, {cache: "no-store"});\n        if (response.ok) {\n            window.location.reload();\n            return;\n        }\n    } catch (_) {}\n    setTimeout(() => waitForAppRestart(attempt + 1), 700);\n}\n\nasync function pullAppUpdate() {\n    const button = $("pullAppUpdateBtn");\n    const statusEl = $("appUpdateStatus");\n    busy(button, true, "Pulling...");\n    try {\n        const data = await api("/api/app-update/pull", {method:"POST", body:"{}"});\n        if (data.result.changed) {\n            const after = data.result.after || {};\n            statusEl.textContent = `Updated to ${after.local_short || "new commit"}. Restarting automatically...`;\n            toast("Update pulled. Restarting Factorio Mod Manager...");\n            setTimeout(() => waitForAppRestart(), 1500);\n        } else {\n            statusEl.textContent = "Already up to date.";\n            toast("Already up to date.");\n        }\n    } catch(err) {\n        statusEl.textContent = err.message;\n        toast(err.message, "error");\n    } finally { button.disabled = true; }\n}\n''',
)

replace_once(ROOT / "pyproject.toml", 'version = "2.4.1"', 'version = "2.4.2"')

(ROOT / "tests" / "test_auto_restart_update.py").write_text(r'''from pathlib import Path
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
''', encoding="utf-8")

print("Applied v2.4.2 automatic restart updater patch")
