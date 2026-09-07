from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"patch target not found: {label}")
    return text.replace(old, new, 1)


# ---------------- manager.py ----------------
path = ROOT / "manager.py"
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "import uuid\n\nimport requests\n",
    "import uuid\nimport webbrowser\n\nimport requests\n",
    "manager webbrowser import",
)
text = replace_once(
    text,
    '''class FactorioModManager:\n    def __init__(self, config_path: Path):\n        self.config_path = config_path\n''',
    '''class FactorioModManager:\n    def __init__(self, config_path: Path, project_root: Path | None = None):\n        self.config_path = config_path\n        self.project_root = Path(project_root).resolve() if project_root else Path(__file__).resolve().parent\n''',
    "manager project_root",
)

old = '''    def _read_info_from_dir(self, path: Path) -> dict[str, Any] | None:\n        info_path = path / "info.json"\n        if not info_path.exists():\n            return None\n        try:\n            info = json.loads(info_path.read_text(encoding="utf-8-sig"))\n            return info if isinstance(info, dict) else None\n        except (OSError, json.JSONDecodeError, UnicodeDecodeError):\n            return None\n\n    def list_installed(self) -> list[dict[str, Any]]:\n'''
new = '''    def _read_info_from_dir(self, path: Path) -> dict[str, Any] | None:\n        info_path = path / "info.json"\n        if not info_path.exists():\n            return None\n        try:\n            info = json.loads(info_path.read_text(encoding="utf-8-sig"))\n            return info if isinstance(info, dict) else None\n        except (OSError, json.JSONDecodeError, UnicodeDecodeError):\n            return None\n\n    def _mod_has_settings(self, path: Path, kind: str) -> bool:\n        if kind == "folder":\n            return (path / "settings.lua").is_file()\n        if kind == "zip":\n            try:\n                with zipfile.ZipFile(path, "r") as archive:\n                    return any(name == "settings.lua" or name.endswith("/settings.lua") for name in archive.namelist())\n            except (OSError, zipfile.BadZipFile):\n                return False\n        return False\n\n    def list_installed(self) -> list[dict[str, Any]]:\n'''
text = replace_once(text, old, new, "manager mod settings detector")
text = replace_once(
    text,
    '''                "kind": kind,\n                "dependencies": dependencies,\n''',
    '''                "kind": kind,\n                "has_settings": self._mod_has_settings(path, kind),\n                "dependencies": dependencies,\n''',
    "manager installed has_settings",
)

marker = '''    def launch_factorio(self) -> dict[str, Any]:\n'''
methods = r'''    def get_installed_mod(self, name: str) -> dict[str, Any]:
        name = parse_mod_name(name)
        mod = self.installed_index().get(name)
        if not mod:
            raise ManagerError(f"{name} belum terpasang.")
        return mod

    def open_mod_location(self, name: str) -> dict[str, str]:
        mod = self.get_installed_mod(name)
        target = Path(mod["path"]).resolve()
        system = platform.system().lower()
        try:
            if system == "windows":
                if target.is_file():
                    subprocess.Popen(["explorer", "/select,", str(target)])
                else:
                    os.startfile(str(target))
            elif system == "darwin":
                if target.is_file():
                    subprocess.Popen(["open", "-R", str(target)])
                else:
                    subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target if target.is_dir() else target.parent)])
        except (OSError, subprocess.SubprocessError) as exc:
            raise ManagerError(f"Gagal membuka lokasi mod: {exc}") from exc
        return {"name": name, "path": str(target)}

    def open_mod_portal(self, name: str) -> dict[str, str]:
        name = parse_mod_name(name)
        url = f"{MOD_PORTAL}/mod/{name}"
        try:
            opened = webbrowser.open(url, new=2)
        except Exception as exc:
            raise ManagerError(f"Gagal membuka browser: {exc}") from exc
        return {"name": name, "url": url, "opened": bool(opened)}

    def _run_git(self, *args: str, check: bool = True, timeout: int = 90) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=str(self.project_root),
                text=True,
                capture_output=True,
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            raise ManagerError("Git tidak ditemukan. Install Git dan pastikan tersedia di PATH.") from exc
        except subprocess.TimeoutExpired as exc:
            raise ManagerError("Perintah Git timeout.") from exc

        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout or "Git command failed").strip()
            raise ManagerError(detail)
        return result

    def app_update_status(self, fetch: bool = True) -> dict[str, Any]:
        git_dir = self.project_root / ".git"
        if not git_dir.exists():
            return {
                "git_repo": False,
                "update_available": False,
                "dirty": False,
                "message": "Folder aplikasi bukan Git clone. Check/Pull Update hanya tersedia jika project di-clone dengan Git.",
                "project_root": str(self.project_root),
            }

        branch = self._run_git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        remote_url_result = self._run_git("remote", "get-url", "origin", check=False)
        remote_url = remote_url_result.stdout.strip() if remote_url_result.returncode == 0 else ""
        if not remote_url:
            raise ManagerError("Git remote 'origin' tidak ditemukan.")

        if fetch:
            self._run_git("fetch", "--quiet", "origin", timeout=120)

        local_sha = self._run_git("rev-parse", "HEAD").stdout.strip()
        remote_ref = "origin/main"
        remote_sha_result = self._run_git("rev-parse", remote_ref, check=False)
        if remote_sha_result.returncode != 0:
            remote_ref = f"origin/{branch}"
            remote_sha_result = self._run_git("rev-parse", remote_ref, check=False)
        if remote_sha_result.returncode != 0:
            raise ManagerError("Branch remote untuk updater tidak ditemukan.")
        remote_sha = remote_sha_result.stdout.strip()

        behind = int(self._run_git("rev-list", "--count", f"HEAD..{remote_ref}").stdout.strip() or "0")
        ahead = int(self._run_git("rev-list", "--count", f"{remote_ref}..HEAD").stdout.strip() or "0")
        dirty = bool(self._run_git("status", "--porcelain").stdout.strip())
        subject = self._run_git("log", "-1", "--pretty=%s", remote_ref).stdout.strip()

        return {
            "git_repo": True,
            "project_root": str(self.project_root),
            "branch": branch,
            "remote": remote_url,
            "remote_ref": remote_ref,
            "local_sha": local_sha,
            "remote_sha": remote_sha,
            "local_short": local_sha[:7],
            "remote_short": remote_sha[:7],
            "behind": behind,
            "ahead": ahead,
            "dirty": dirty,
            "update_available": behind > 0,
            "latest_subject": subject,
            "message": f"{behind} commit(s) behind, {ahead} ahead" if (behind or ahead) else "Up to date",
        }

    def pull_app_update(self) -> dict[str, Any]:
        status = self.app_update_status(fetch=True)
        if not status.get("git_repo"):
            raise ManagerError(status.get("message") or "Aplikasi bukan Git clone.")
        if status.get("dirty"):
            raise ManagerError("Ada perubahan lokal yang belum di-commit. Commit/stash dulu sebelum Pull Update agar file tidak tertimpa.")
        if status.get("ahead") and status.get("behind"):
            raise ManagerError("Branch lokal dan origin berbeda arah (diverged). Pull otomatis dibatalkan agar aman.")
        if not status.get("update_available"):
            return {"changed": False, "before": status, "after": status, "restart_required": False, "output": "Already up to date."}

        before_sha = status["local_sha"]
        result = self._run_git("pull", "--ff-only", "origin", "main", timeout=180)
        after = self.app_update_status(fetch=False)
        changed = before_sha != after.get("local_sha")
        return {
            "changed": changed,
            "before": status,
            "after": after,
            "restart_required": changed,
            "output": (result.stdout or result.stderr or "").strip(),
        }

'''
text = replace_once(text, marker, methods + marker, "manager updater methods")
path.write_text(text, encoding="utf-8")


# ---------------- flet_app.py ----------------
path = ROOT / "flet_app.py"
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '''                                ft.Row(controls=[\n                                    toggle,\n                                    ft.IconButton(icon=ft.Icons.SYSTEM_UPDATE_ALT, tooltip="Update", data=mod["name"], on_click=self.update_one),\n                                    ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, tooltip="Remove", data=mod["name"], on_click=self.remove_one),\n                                ]),\n''',
    '''                                ft.Row(controls=[\n                                    toggle,\n                                    ft.IconButton(icon=ft.Icons.SETTINGS_OUTLINED, tooltip="Mod settings", data=mod["name"], on_click=self.show_mod_settings),\n                                    ft.IconButton(icon=ft.Icons.SYSTEM_UPDATE_ALT, tooltip="Update", data=mod["name"], on_click=self.update_one),\n                                    ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, tooltip="Remove", data=mod["name"], on_click=self.remove_one),\n                                ]),\n''',
    "Flet mod settings button",
)

mod_settings_method = r'''    async def show_mod_settings(self, e):
        name = str(e.control.data or "")
        mod = next((item for item in self.installed if item.get("name") == name), None)
        if not mod:
            self.notify(f"Mod {name} tidak ditemukan.", True)
            return

        status = ft.Text("", size=11, color="#a69d93")
        enabled = ft.Switch(label="Enabled", value=bool(mod.get("enabled")))
        dialog = None

        async def change_enabled(ev):
            wanted = bool(ev.control.value)
            try:
                await self.run_bg(manager.set_enabled, name, wanted)
                mod["enabled"] = wanted
                status.value = f'{name} {"enabled" if wanted else "disabled"}.'
                status.color = "#8fbf75"
            except Exception as exc:
                ev.control.value = not wanted
                status.value = str(exc)
                status.color = "#ff8c86"
            self.page.update()

        async def update_mod(ev):
            ev.control.disabled = True
            status.value = f"Checking {name}..."
            status.color = "#a69d93"
            self.page.update()
            try:
                result = await self.run_bg(manager.update_one, name)
                status.value = f'{name}: {result["from"]} → {result["to"]}' if result.get("updated") else f"{name} already current."
                status.color = "#8fbf75"
                self.installed = await self.run_bg(manager.list_installed)
            except Exception as exc:
                status.value = str(exc)
                status.color = "#ff8c86"
            finally:
                ev.control.disabled = False
                self.page.update()

        async def open_location(ev):
            try:
                result = await self.run_bg(manager.open_mod_location, name)
                status.value = f'Opened: {result["path"]}'
                status.color = "#8fbf75"
            except Exception as exc:
                status.value = str(exc)
                status.color = "#ff8c86"
            self.page.update()

        async def open_portal(ev):
            try:
                await self.run_bg(manager.open_mod_portal, name)
                status.value = "Opened Factorio Mod Portal."
                status.color = "#8fbf75"
            except Exception as exc:
                status.value = str(exc)
                status.color = "#ff8c86"
            self.page.update()

        def close_dialog(ev=None):
            try:
                self.page.pop_dialog()
            except Exception:
                if dialog is not None:
                    dialog.open = False
                self.page.update()

        enabled.on_change = change_enabled
        deps = []
        for dep in mod.get("dependencies") or []:
            raw = str(dep.get("raw") or dep.get("name") or "").strip()
            if raw:
                deps.append(ft.Text(f"• {raw}", size=11, color="#c8c0b7"))
        if not deps:
            deps.append(ft.Text("No declared dependencies.", size=11, color="#77716b"))

        settings_note = (
            ft.Text("settings.lua detected — configure gameplay values inside Factorio → Settings → Mod settings.", size=11, color="#8fbf75")
            if mod.get("has_settings")
            else ft.Text("This mod does not declare settings.lua.", size=11, color="#77716b")
        )

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row(controls=[ft.Icon(ft.Icons.SETTINGS_OUTLINED, color="#e48c30"), ft.Text(f'Mod Settings — {mod.get("title") or name}', weight=ft.FontWeight.BOLD)]),
            content=ft.Container(
                width=570,
                content=ft.Column(
                    scroll=ft.ScrollMode.AUTO,
                    tight=True,
                    spacing=10,
                    controls=[
                        ft.Row(controls=[enabled, ft.Container(expand=True), ft.Text(f'v{mod.get("version") or "?"}', color="#f2b25c")]),
                        ft.Text(f'ID: {name}', size=11, color="#a69d93"),
                        ft.Text(f'Author: {mod.get("author") or "?"}', size=11, color="#a69d93"),
                        ft.Text(f'Factorio: {mod.get("factorio_version") or "?"}', size=11, color="#a69d93"),
                        ft.Text(f'File: {mod.get("file") or "?"}', size=11, color="#70685f"),
                        settings_note,
                        ft.Divider(color="#39332b"),
                        ft.Text("Dependencies", weight=ft.FontWeight.BOLD),
                        *deps,
                        ft.Divider(color="#39332b"),
                        status,
                    ],
                ),
            ),
            actions=[
                ft.Button("Open folder", icon=ft.Icons.FOLDER_OPEN, on_click=open_location, bgcolor="#24211e", color="#d8d0c7"),
                ft.Button("Mod Portal", icon=ft.Icons.OPEN_IN_NEW, on_click=open_portal, bgcolor="#24211e", color="#d8d0c7"),
                ft.Button("Check / Update", icon=ft.Icons.SYSTEM_UPDATE_ALT, on_click=update_mod),
                ft.TextButton("Close", on_click=close_dialog),
            ],
        )
        self.page.show_dialog(dialog)
        self.page.update()

'''
text = replace_once(text, "    async def toggle_mod(self, e):\n", mod_settings_method + "    async def toggle_mod(self, e):\n", "Flet mod settings method")

old_settings = '''        async def backup(e):\n            try:\n                r = await self.run_bg(manager.backup_state, "flet"); self.notify(f'Backup: {r["path"]}')\n            except Exception as exc: self.notify(str(exc), True)\n        diag = await self.run_bg(manager.diagnostics)\n        self.body.controls.extend([\n            ft.Container(padding=16, border=ft.Border.all(1, "#39332b"), border_radius=10, bgcolor="#191714", content=ft.Column(controls=[mods_dir, factorio_version, exe, args, deps, ft.Row(controls=[ft.Button("Save Settings", icon=ft.Icons.SAVE, on_click=save), ft.Button("Backup state", icon=ft.Icons.BACKUP, on_click=backup)])])),\n'''
new_settings = '''        async def backup(e):\n            try:\n                r = await self.run_bg(manager.backup_state, "flet"); self.notify(f'Backup: {r["path"]}')\n            except Exception as exc: self.notify(str(exc), True)\n\n        app_update_text = ft.Text("Not checked yet.", size=11, color="#a69d93")\n        pull_update_btn = ft.Button("Pull Update", icon=ft.Icons.DOWNLOAD, disabled=True, bgcolor="#2b2824", color="#e6ded5")\n\n        async def check_app_update(e):\n            e.control.disabled = True\n            app_update_text.value = "Checking origin/main..."\n            app_update_text.color = "#a69d93"\n            self.page.update()\n            try:\n                result = await self.run_bg(manager.app_update_status, True)\n                if not result.get("git_repo"):\n                    app_update_text.value = result.get("message", "Not a Git clone.")\n                    app_update_text.color = "#e4b65f"\n                    pull_update_btn.disabled = True\n                elif result.get("update_available"):\n                    app_update_text.value = f'Update available: {result["local_short"]} → {result["remote_short"]} · {result["behind"]} commit(s) · {result.get("latest_subject") or ""}'\n                    app_update_text.color = "#e4b65f"\n                    pull_update_btn.disabled = bool(result.get("dirty") or result.get("ahead"))\n                    if result.get("dirty"):\n                        app_update_text.value += " · local changes detected; commit/stash first"\n                else:\n                    app_update_text.value = f'Up to date · {result.get("local_short", "?")}'\n                    app_update_text.color = "#8fbf75"\n                    pull_update_btn.disabled = True\n            except Exception as exc:\n                app_update_text.value = str(exc)\n                app_update_text.color = "#ff8c86"\n                pull_update_btn.disabled = True\n            finally:\n                e.control.disabled = False\n                self.page.update()\n\n        async def pull_app_update(e):\n            e.control.disabled = True\n            app_update_text.value = "Pulling update..."\n            app_update_text.color = "#a69d93"\n            self.page.update()\n            try:\n                result = await self.run_bg(manager.pull_app_update)\n                if result.get("changed"):\n                    after = result.get("after") or {}\n                    app_update_text.value = f'Updated to {after.get("local_short", "new commit")}. Restart Factorio Mod Manager to load the new code.'\n                    app_update_text.color = "#8fbf75"\n                    self.notify("Update pulled successfully. Restart the app to apply it.")\n                else:\n                    app_update_text.value = "Already up to date."\n                    app_update_text.color = "#8fbf75"\n            except Exception as exc:\n                app_update_text.value = str(exc)\n                app_update_text.color = "#ff8c86"\n            finally:\n                e.control.disabled = True\n                self.page.update()\n\n        check_update_btn = ft.Button("Check App Update", icon=ft.Icons.REFRESH, on_click=check_app_update, bgcolor="#24211e", color="#d8d0c7")\n        pull_update_btn.on_click = pull_app_update\n\n        diag = await self.run_bg(manager.diagnostics)\n        self.body.controls.extend([\n            ft.Container(padding=16, border=ft.Border.all(1, "#39332b"), border_radius=10, bgcolor="#191714", content=ft.Column(controls=[\n                mods_dir, factorio_version, exe, args, deps,\n                ft.Row(wrap=True, controls=[ft.Button("Save Settings", icon=ft.Icons.SAVE, on_click=save), ft.Button("Backup state", icon=ft.Icons.BACKUP, on_click=backup)]),\n                ft.Divider(color="#39332b"),\n                ft.Text("Application Update", weight=ft.FontWeight.BOLD),\n                ft.Text("Checks this Git clone against origin/main and only pulls fast-forward updates.", size=11, color="#77716b"),\n                ft.Row(wrap=True, controls=[check_update_btn, pull_update_btn]),\n                app_update_text,\n            ])),\n'''
text = replace_once(text, old_settings, new_settings, "Flet settings updater")
path.write_text(text, encoding="utf-8")


# ---------------- app.py ----------------
path = ROOT / "app.py"
text = path.read_text(encoding="utf-8")
marker = '''@app.post("/api/launch")\ndef launch_factorio():\n'''
endpoints = '''@app.post("/api/mod/open-location")\ndef open_mod_location():\n    try:\n        payload = request.get_json(silent=True) or {}\n        return ok(result=manager.open_mod_location(payload.get("mod", "")))\n    except ManagerError as exc:\n        return fail(exc)\n\n\n@app.get("/api/app-update")\ndef app_update_status():\n    try:\n        return ok(status=manager.app_update_status(fetch=True))\n    except ManagerError as exc:\n        return fail(exc)\n\n\n@app.post("/api/app-update/pull")\ndef app_update_pull():\n    try:\n        return ok(result=manager.pull_app_update())\n    except ManagerError as exc:\n        return fail(exc)\n\n\n'''
text = replace_once(text, marker, endpoints + marker, "Flask updater endpoints")
path.write_text(text, encoding="utf-8")


# ---------------- templates/index.html ----------------
path = ROOT / "templates" / "index.html"
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '''                <p class="hint" id="modListPath"></p>\n                <div id="diagnosticsBox"></div>\n''',
    '''                <p class="hint" id="modListPath"></p>\n\n                <div class="panel app-updater-panel">\n                    <h3>Application Update</h3>\n                    <p class="hint">Check this Git clone against <code>origin/main</code> and pull only fast-forward updates.</p>\n                    <div class="actions">\n                        <button class="ghost" id="checkAppUpdateBtn">Check App Update</button>\n                        <button id="pullAppUpdateBtn" disabled>Pull Update</button>\n                    </div>\n                    <p class="hint" id="appUpdateStatus">Not checked yet.</p>\n                </div>\n\n                <div id="diagnosticsBox"></div>\n''',
    "Web updater settings panel",
)
path.write_text(text, encoding="utf-8")


# ---------------- static/app.js ----------------
path = ROOT / "static" / "app.js"
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '''                <label class="switch" title="Enable/disable"><input type="checkbox" data-enable="${escapeHTML(mod.name)}" ${mod.enabled ? "checked" : ""}><span></span></label>\n                <button class="ghost small" data-update="${escapeHTML(mod.name)}">Update</button>\n''',
    '''                <label class="switch" title="Enable/disable"><input type="checkbox" data-enable="${escapeHTML(mod.name)}" ${mod.enabled ? "checked" : ""}><span></span></label>\n                <button class="ghost small" data-mod-settings="${escapeHTML(mod.name)}">⚙ Settings</button>\n                <button class="ghost small" data-update="${escapeHTML(mod.name)}">Update</button>\n''',
    "Web mod settings button",
)
text = replace_once(
    text,
    '''    document.querySelectorAll("[data-update]").forEach(el => el.addEventListener("click", () => updateOne(el.dataset.update, el)));\n    document.querySelectorAll("[data-remove]").forEach(el => el.addEventListener("click", () => removeMod(el.dataset.remove, el)));\n}\n''',
    '''    document.querySelectorAll("[data-mod-settings]").forEach(el => el.addEventListener("click", () => openModSettings(el.dataset.modSettings)));\n    document.querySelectorAll("[data-update]").forEach(el => el.addEventListener("click", () => updateOne(el.dataset.update, el)));\n    document.querySelectorAll("[data-remove]").forEach(el => el.addEventListener("click", () => removeMod(el.dataset.remove, el)));\n}\n\nfunction closeModal() {\n    $("modal").classList.add("hidden");\n    $("modalBody").innerHTML = "";\n}\n\nfunction openModSettings(name) {\n    const mod = state.installed.find(item => item.name === name);\n    if (!mod) { toast(`Mod ${name} not found.`, "error"); return; }\n    const deps = (mod.dependencies || []).map(dep => `<div class="mod-setting-dep">• ${escapeHTML(dep.raw || dep.name || "")}</div>`).join("") || `<div class="hint">No declared dependencies.</div>`;\n    $("modalBody").innerHTML = `\n        <div class="mod-settings-head"><div class="mod-icon">${escapeHTML((mod.title || mod.name).slice(0,2).toUpperCase())}</div><div><h2>${escapeHTML(mod.title || mod.name)}</h2><p>${escapeHTML(mod.name)} · v${escapeHTML(mod.version)} · Factorio ${escapeHTML(mod.factorio_version || "?")}</p></div></div>\n        <div class="mod-settings-grid">\n            <div><span>Author</span><strong>${escapeHTML(mod.author || "?")}</strong></div>\n            <div><span>Type</span><strong>${escapeHTML(mod.kind || "?")}</strong></div>\n            <div><span>In-game settings</span><strong>${mod.has_settings ? "settings.lua detected" : "None declared"}</strong></div>\n            <div><span>File</span><strong>${escapeHTML(mod.file || "?")}</strong></div>\n        </div>\n        <label class="checkbox-row"><input type="checkbox" id="modalModEnabled" ${mod.enabled ? "checked" : ""}><span>Enabled</span></label>\n        <div class="dependency-preview"><strong>Dependencies</strong>${deps}</div>\n        ${mod.has_settings ? `<p class="hint good-note">Gameplay values are configured in Factorio → Settings → Mod settings.</p>` : ""}\n        <div class="actions mod-settings-actions">\n            <button class="ghost" id="modalOpenFolder">Open Folder</button>\n            <button class="ghost" id="modalOpenPortal">Mod Portal</button>\n            <button id="modalUpdateMod">Check / Update</button>\n        </div>\n        <p class="hint" id="modalModStatus"></p>`;\n    $("modal").classList.remove("hidden");\n\n    $("modalModEnabled").addEventListener("change", async e => {\n        try { await api("/api/enable", {method:"POST", body:JSON.stringify({mod:name, enabled:e.target.checked})}); mod.enabled=e.target.checked; $("modalModStatus").textContent=`${name} ${e.target.checked ? "enabled" : "disabled"}.`; await loadInstalled(); }\n        catch(err){ e.target.checked=!e.target.checked; $("modalModStatus").textContent=err.message; }\n    });\n    $("modalOpenFolder").addEventListener("click", async () => {\n        try { const data=await api("/api/mod/open-location", {method:"POST", body:JSON.stringify({mod:name})}); $("modalModStatus").textContent=`Opened ${data.result.path}`; }\n        catch(err){ $("modalModStatus").textContent=err.message; }\n    });\n    $("modalOpenPortal").addEventListener("click", () => window.open(`https://mods.factorio.com/mod/${encodeURIComponent(name)}`, "_blank", "noopener"));\n    $("modalUpdateMod").addEventListener("click", async e => {\n        busy(e.currentTarget,true,"Updating...");\n        try { const data=await api("/api/update", {method:"POST", body:JSON.stringify({mod:name})}); $("modalModStatus").textContent=data.result.updated ? `${name}: ${data.result.from} → ${data.result.to}` : `${name} already current.`; await loadInstalled(); }\n        catch(err){ $("modalModStatus").textContent=err.message; }\n        finally{ busy(e.currentTarget,false); }\n    });\n}\n''',
    "Web mod settings modal functions",
)

insert_marker = '''async function loadDiagnostics() {\n'''
updater_funcs = '''async function checkAppUpdate(showToast = true) {\n    const button = $("checkAppUpdateBtn");\n    const pull = $("pullAppUpdateBtn");\n    const statusEl = $("appUpdateStatus");\n    busy(button, true, "Checking...");\n    statusEl.textContent = "Checking origin/main...";\n    try {\n        const data = await api("/api/app-update");\n        const s = data.status;\n        if (!s.git_repo) {\n            statusEl.textContent = s.message || "Not a Git clone.";\n            pull.disabled = true;\n        } else if (s.update_available) {\n            statusEl.textContent = `Update available: ${s.local_short} → ${s.remote_short} · ${s.behind} commit(s)${s.dirty ? " · local changes detected; commit/stash first" : ""}`;\n            pull.disabled = !!(s.dirty || s.ahead);\n            if (showToast) toast("Application update available.", "warn");\n        } else {\n            statusEl.textContent = `Up to date · ${s.local_short || "?"}`;\n            pull.disabled = true;\n            if (showToast) toast("Application is up to date.");\n        }\n    } catch(err) {\n        statusEl.textContent = err.message;\n        pull.disabled = true;\n        if (showToast) toast(err.message, "error");\n    } finally { busy(button, false); }\n}\n\nasync function pullAppUpdate() {\n    const button = $("pullAppUpdateBtn");\n    const statusEl = $("appUpdateStatus");\n    busy(button, true, "Pulling...");\n    try {\n        const data = await api("/api/app-update/pull", {method:"POST", body:"{}"});\n        if (data.result.changed) {\n            const after = data.result.after || {};\n            statusEl.textContent = `Updated to ${after.local_short || "new commit"}. Restart Factorio Mod Manager to load the new code.`;\n            toast("Update pulled. Restart the app to apply it.");\n        } else {\n            statusEl.textContent = "Already up to date.";\n            toast("Already up to date.");\n        }\n    } catch(err) {\n        statusEl.textContent = err.message;\n        toast(err.message, "error");\n    } finally { button.disabled = true; }\n}\n\n'''
text = replace_once(text, insert_marker, updater_funcs + insert_marker, "Web updater functions")

text = replace_once(
    text,
    '''$("saveProfileBtn").addEventListener("click", saveProfile);\n''',
    '''$("saveProfileBtn").addEventListener("click", saveProfile);\n$("checkAppUpdateBtn").addEventListener("click", () => checkAppUpdate(true));\n$("pullAppUpdateBtn").addEventListener("click", pullAppUpdate);\n$("modalClose").addEventListener("click", closeModal);\n$("modal").addEventListener("click", e => { if (e.target === $("modal")) closeModal(); });\n''',
    "Web updater/modal event listeners",
)
path.write_text(text, encoding="utf-8")


# ---------------- static/style.css ----------------
path = ROOT / "static" / "style.css"
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    ".modal { display: none; }\n",
    '''.modal {\n    position: fixed;\n    inset: 0;\n    z-index: 200;\n    display: grid;\n    place-items: center;\n    padding: 22px;\n    background: rgba(0, 0, 0, .68);\n    backdrop-filter: blur(3px);\n}\n.modal.hidden { display: none !important; }\n.modal-card {\n    position: relative;\n    width: min(680px, 100%);\n    max-height: min(760px, calc(100vh - 44px));\n    overflow: auto;\n    padding: 22px;\n    background: #171512;\n    border: 1px solid #4a433a;\n    border-radius: 12px;\n    box-shadow: 0 24px 80px rgba(0,0,0,.55);\n}\n.modal-close {\n    position: absolute;\n    top: 10px;\n    right: 10px;\n    width: 34px;\n    height: 34px;\n    padding: 0;\n    border-radius: 50%;\n    background: #27231f;\n    color: #d8d0c7;\n}\n.mod-settings-head { display:flex; gap:12px; align-items:center; padding-right:40px; }\n.mod-settings-head h2 { margin:0 0 4px; }\n.mod-settings-head p { margin:0; color:var(--muted); font-size:12px; }\n.mod-settings-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin:18px 0; }\n.mod-settings-grid > div { padding:10px; background:#211e19; border:1px solid var(--border); border-radius:8px; overflow-wrap:anywhere; }\n.mod-settings-grid span { display:block; color:var(--muted); font-size:10px; margin-bottom:3px; }\n.mod-settings-grid strong { font-size:12px; }\n.mod-setting-dep { margin-top:5px; color:#c8c0b7; font-size:11px; }\n.mod-settings-actions { margin-top:14px; flex-wrap:wrap; }\n.good-note { color:var(--good); }\n.app-updater-panel { margin-top:18px; background:#151412; }\n''',
    "Web modal CSS",
)
path.write_text(text, encoding="utf-8")


# ---------------- pyproject.toml ----------------
path = ROOT / "pyproject.toml"
text = path.read_text(encoding="utf-8")
text = replace_once(text, 'version = "2.2.0"', 'version = "2.3.0"', "version bump")
path.write_text(text, encoding="utf-8")


# ---------------- updater + per-mod settings offline test ----------------
test_path = ROOT / "tests" / "test_app_update_offline.py"
test_path.write_text(r'''from pathlib import Path
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
''', encoding="utf-8")

print("v2.3.0 patch applied")
