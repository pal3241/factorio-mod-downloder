from __future__ import annotations

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
