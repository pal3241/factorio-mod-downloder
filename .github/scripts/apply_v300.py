from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: Path, old: str, new: str):
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected text not found in {path}: {old[:180]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_between(path: Path, start: str, end: str, replacement: str):
    text = path.read_text(encoding="utf-8")
    a = text.find(start)
    if a < 0:
        raise SystemExit(f"Start marker not found in {path}: {start!r}")
    b = text.find(end, a)
    if b < 0:
        raise SystemExit(f"End marker not found in {path}: {end!r}")
    path.write_text(text[:a] + replacement + text[b:], encoding="utf-8")


# ---------------------------------------------------------------------------
# Version source used both by source mode and packaged EXE mode.
# ---------------------------------------------------------------------------
(ROOT / "app_version.py").write_text('APP_VERSION = "3.0.0"\n', encoding="utf-8")

# ---------------------------------------------------------------------------
# Manager: UI customization + richer Mod Portal detail + EXE updater mode.
# ---------------------------------------------------------------------------
manager = ROOT / "manager.py"
replace_once(manager, "import shutil\nimport subprocess\n", "import shutil\nimport subprocess\nimport sys\n")
replace_once(
    manager,
    "from factorio_settings import (\n",
    "from app_version import APP_VERSION\nfrom factorio_settings import (\n",
)

replace_once(
    manager,
    '''        defaults = {\n            "mods_dir": str(default_mods_dir()),\n            "factorio_version": "2.0",\n            "install_dependencies": True,\n            "factorio_executable": "",\n            "launch_args": "",\n        }\n''',
    '''        defaults = {\n            "mods_dir": str(default_mods_dir()),\n            "factorio_version": "2.0",\n            "install_dependencies": True,\n            "factorio_executable": "",\n            "launch_args": "",\n            "ui_background_color": "#070B14",\n            "ui_menu_color": "#09111E",\n            "ui_accent_color": "#4EA1FF",\n        }\n''',
)

replace_once(
    manager,
    '''        if "launch_args" in updates:\n            updates["launch_args"] = str(updates["launch_args"]).strip()\n\n        self.config.update(updates)\n''',
    '''        if "launch_args" in updates:\n            updates["launch_args"] = str(updates["launch_args"]).strip()\n\n        for color_key in ("ui_background_color", "ui_menu_color", "ui_accent_color"):\n            if color_key in updates:\n                value = str(updates[color_key]).strip().upper()\n                if not re.fullmatch(r"#[0-9A-F]{6}", value):\n                    raise ManagerError(f"{color_key} harus format HEX #RRGGBB, contoh #09111E.")\n                updates[color_key] = value\n\n        self.config.update(updates)\n''',
)

# Richer detail metadata.
replace_once(
    manager,
    '''        installed = self.installed_index().get(name)\n\n        return {\n            "name": name,\n            "title": data.get("title") or name,\n            "owner": data.get("owner") or "",\n            "summary": data.get("summary") or "",\n            "category": data.get("category") or "",\n            "downloads_count": data.get("downloads_count") or 0,\n            "deprecated": bool(data.get("deprecated", False)),\n            "thumbnail": thumbnail,\n            "releases": releases,\n            "installed": installed,\n        }\n''',
    '''        installed = self.installed_index().get(name)\n        license_data = data.get("license")\n        if isinstance(license_data, dict):\n            license_name = license_data.get("name") or license_data.get("title") or ""\n        else:\n            license_name = str(license_data or "")\n\n        factorio_branches = sorted(\n            {\n                factorio_branch(str(item.get("factorio_version") or ""))\n                for item in releases\n                if item.get("factorio_version")\n            },\n            key=version_obj,\n        )\n        factorio_display = (\n            f"{factorio_branches[0]} - {factorio_branches[-1]}"\n            if len(factorio_branches) > 1\n            else (factorio_branches[0] if factorio_branches else "?")\n        )\n\n        return {\n            "name": name,\n            "title": data.get("title") or name,\n            "owner": data.get("owner") or "",\n            "summary": data.get("summary") or "",\n            "description": data.get("description") or data.get("summary") or "",\n            "category": data.get("category") or "",\n            "downloads_count": data.get("downloads_count") or 0,\n            "deprecated": bool(data.get("deprecated", False)),\n            "thumbnail": thumbnail,\n            "releases": releases,\n            "installed": installed,\n            "created_at": data.get("created_at") or "",\n            "updated_at": data.get("updated_at") or "",\n            "source_url": data.get("source_url") or "",\n            "homepage": data.get("homepage") or "",\n            "license": license_name,\n            "tags": list(data.get("tags") or []),\n            "changelog": data.get("changelog") or "",\n            "factorio_version_display": factorio_display,\n            "release_count": len(releases),\n        }\n''',
)

# Replace updater functions with dual Git/source + packaged release updater.
replace_between(
    manager,
    "    def app_update_status(self, fetch: bool = True) -> dict[str, Any]:\n",
    "    def launch_factorio(self) -> dict[str, Any]:\n",
    r'''    def _release_update_status(self) -> dict[str, Any]:
        """Check GitHub Releases when running as a packaged executable."""
        url = "https://api.github.com/repos/pal3241/factorio-mod-downloder/releases/latest"
        try:
            response = self.session.get(url, timeout=20, headers={"Accept": "application/vnd.github+json"})
            response.raise_for_status()
            release = response.json()
        except requests.RequestException as exc:
            raise ManagerError(f"Gagal mengecek GitHub Release: {exc}") from exc

        tag = str(release.get("tag_name") or "").lstrip("vV")
        try:
            latest = version_obj(tag)
            current = version_obj(APP_VERSION)
        except Exception as exc:
            raise ManagerError("Versi GitHub Release tidak valid.") from exc

        asset = next(
            (
                item for item in (release.get("assets") or [])
                if str(item.get("name") or "").lower() == "factoriomodmanager.exe"
            ),
            None,
        )
        return {
            "git_repo": False,
            "mode": "release",
            "packaged": True,
            "current_version": APP_VERSION,
            "latest_version": tag or APP_VERSION,
            "local_short": f"v{APP_VERSION}",
            "remote_short": f"v{tag or APP_VERSION}",
            "behind": 1 if latest > current else 0,
            "ahead": 0,
            "dirty": False,
            "update_available": latest > current,
            "latest_subject": release.get("name") or release.get("tag_name") or "",
            "download_url": (asset or {}).get("browser_download_url") or "",
            "asset_size": int((asset or {}).get("size") or 0),
            "message": "Update available" if latest > current else "Up to date",
        }

    def app_update_status(self, fetch: bool = True) -> dict[str, Any]:
        if getattr(sys, "frozen", False):
            return self._release_update_status()

        git_dir = self.project_root / ".git"
        if not git_dir.exists():
            return {
                "git_repo": False,
                "mode": "source",
                "update_available": False,
                "dirty": False,
                "message": "Folder aplikasi bukan Git clone. Gunakan GitHub Release EXE untuk updater tanpa Git.",
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
            "mode": "git",
            "packaged": False,
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

        if status.get("mode") == "release":
            if not status.get("update_available"):
                return {"changed": False, "before": status, "after": status, "restart_required": False, "output": "Already up to date."}
            url = status.get("download_url") or ""
            if not url:
                raise ManagerError("Release terbaru tidak mempunyai asset FactorioModManager.exe.")
            update_dir = Path(tempfile.gettempdir()) / "FactorioModManagerUpdate"
            update_dir.mkdir(parents=True, exist_ok=True)
            target = update_dir / f"FactorioModManager-{status['latest_version']}.exe"
            try:
                with self.session.get(url, stream=True, timeout=(15, 180)) as response:
                    response.raise_for_status()
                    total = 0
                    with target.open("wb") as handle:
                        for chunk in response.iter_content(chunk_size=1024 * 512):
                            if not chunk:
                                continue
                            total += len(chunk)
                            if total > 750 * 1024 * 1024:
                                raise ManagerError("Ukuran update EXE tidak wajar (>750 MiB).")
                            handle.write(chunk)
            except (requests.RequestException, OSError) as exc:
                target.unlink(missing_ok=True)
                raise ManagerError(f"Gagal mengunduh update EXE: {exc}") from exc
            if not target.exists() or target.stat().st_size < 1024 * 1024:
                target.unlink(missing_ok=True)
                raise ManagerError("File update EXE tidak valid atau terlalu kecil.")
            after = dict(status)
            after["local_short"] = f"v{status['latest_version']}"
            return {
                "changed": True,
                "before": status,
                "after": after,
                "restart_required": True,
                "replacement_path": str(target),
                "output": "EXE update downloaded.",
            }

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

''',
)

# ---------------------------------------------------------------------------
# Restart helper: allow replacing a frozen EXE after it exits.
# ---------------------------------------------------------------------------
restart = ROOT / "process_restart.py"
restart_text = restart.read_text(encoding="utf-8")
if "def schedule_executable_replace_and_restart" not in restart_text:
    restart_text += r'''


def schedule_executable_replace_and_restart(replacement_path: Path | str, delay: float = 0.8) -> dict:
    """On Windows, exit this EXE, replace it with a downloaded EXE, then relaunch."""
    replacement = Path(replacement_path).resolve()
    current = Path(sys.executable).resolve()
    if os.name != "nt" or not getattr(sys, "frozen", False):
        raise RuntimeError("Executable replacement is only available in packaged Windows mode.")
    if not replacement.exists():
        raise FileNotFoundError(replacement)

    def worker():
        # PowerShell is external to the locked executable and survives our exit.
        command = (
            f'Start-Sleep -Milliseconds 1200; '
            f'Copy-Item -LiteralPath {json.dumps(str(replacement))} -Destination {json.dumps(str(current))} -Force; '
            f'Start-Process -FilePath {json.dumps(str(current))}'
        )
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", command],
            close_fds=True,
            creationflags=flags,
        )
        os._exit(0)

    timer = threading.Timer(max(0.1, float(delay)), worker)
    timer.daemon = True
    timer.start()
    return {"scheduled": True, "replacement": str(replacement), "current": str(current)}
'''
    restart.write_text(restart_text, encoding="utf-8")

# ---------------------------------------------------------------------------
# Flet: runtime color customization + full Mod Portal-style detail view.
# ---------------------------------------------------------------------------
flet = ROOT / "flet_app.py"
replace_once(
    flet,
    "from process_restart import schedule_restart\n",
    "from process_restart import schedule_restart, schedule_executable_replace_and_restart\n",
)
replace_once(
    flet,
    '''        page.title = "Factorio Mod Manager"\n        page.theme_mode = ft.ThemeMode.DARK\n        page.theme = ft.Theme(color_scheme_seed="#4EA1FF")\n        page.padding = 0\n        page.bgcolor = "#070B14"\n''',
    '''        cfg = manager.get_config()\n        self.ui_background_color = cfg.get("ui_background_color", "#070B14")\n        self.ui_menu_color = cfg.get("ui_menu_color", "#09111E")\n        self.ui_accent_color = cfg.get("ui_accent_color", "#4EA1FF")\n\n        page.title = "Factorio Mod Manager"\n        page.theme_mode = ft.ThemeMode.DARK\n        page.theme = ft.Theme(color_scheme_seed=self.ui_accent_color)\n        page.padding = 0\n        page.bgcolor = self.ui_background_color\n''',
)
replace_once(flet, '            bgcolor="#09111E",\n', '            bgcolor=self.ui_menu_color,\n')
replace_once(
    flet,
    '''        page.add(self.root)\n\n    def set_status(self, text: str):\n''',
    '''        page.add(self.root)\n\n    def apply_runtime_theme(self, cfg=None):\n        cfg = cfg or manager.get_config()\n        self.ui_background_color = cfg.get("ui_background_color", "#070B14")\n        self.ui_menu_color = cfg.get("ui_menu_color", "#09111E")\n        self.ui_accent_color = cfg.get("ui_accent_color", "#4EA1FF")\n        self.page.bgcolor = self.ui_background_color\n        self.page.theme = ft.Theme(color_scheme_seed=self.ui_accent_color)\n        self.nav.bgcolor = self.ui_menu_color\n        self.page.update()\n\n    def set_status(self, text: str):\n''',
)

# Full detail page replaces the compact exact lookup card.
replace_between(
    flet,
    "        async def exact_lookup(e=None):\n",
    "        async def submit_search(e=None):\n",
    r'''        async def exact_lookup(e=None):
            value = query.value.strip()
            if not value:
                return
            self.set_status("Loading mod details...")
            detail_box.visible = True
            detail_box.controls[:] = [ft.Container(padding=30, alignment=ft.Alignment.CENTER, content=ft.ProgressRing())]
            try:
                browse_area.visible = False
            except NameError:
                pass
            self.page.update()
            try:
                mod = await self.run_bg(manager.portal_view, value)
                self.title.value = mod["title"]
                branch = ".".join(str(manager.config["factorio_version"]).split(".")[:2])
                releases = [
                    r for r in mod["releases"]
                    if ".".join(str(r["factorio_version"] or "").split(".")[:2]) == branch
                ]
                versions = ft.Dropdown(
                    label="Version",
                    value=releases[0]["version"] if releases else None,
                    options=[
                        ft.DropdownOption(key=r["version"], text=f'{r["version"]} — Factorio {r["factorio_version"]}')
                        for r in releases
                    ],
                    width=270,
                    disabled=not bool(releases),
                )

                async def back_to_search(ev=None):
                    detail_box.visible = False
                    browse_area.visible = True
                    self.title.value = "Search Mods"
                    self.page.update()

                async def install_selected(ev):
                    if not versions.value:
                        self.notify(f'No compatible release for Factorio {branch}.', True)
                        return
                    ev.control.disabled = True
                    self.set_status(f'Installing {mod["name"]}...')
                    self.page.update()
                    try:
                        result = await self.run_bg(manager.install, mod["name"], versions.value, None, True)
                        self.notify(
                            f'Installed {mod["title"]} {versions.value}.'
                            if result["installed"] else f'{mod["title"]} already current.'
                        )
                    except Exception as exc:
                        self.notify(str(exc), True)
                    finally:
                        ev.control.disabled = False
                        self.set_status("Ready")
                        self.page.update()

                if mod.get("thumbnail"):
                    hero_icon = ft.Image(src=mod["thumbnail"], width=170, height=170, fit=ft.BoxFit.COVER)
                else:
                    hero_icon = ft.Container(
                        width=170, height=170, alignment=ft.Alignment.CENTER,
                        bgcolor="#13243A", border_radius=10,
                        content=ft.Text((mod["title"] or mod["name"])[:2].upper(), size=44, weight=ft.FontWeight.BOLD, color=self.ui_accent_color),
                    )

                release = releases[0] if releases else (mod["releases"][0] if mod["releases"] else None)
                tab_content = ft.Column(spacing=10)
                tab_buttons = ft.Row(spacing=5, scroll=ft.ScrollMode.AUTO)
                active_tab = {"name": "Information"}

                def text_or_na(value):
                    return str(value).strip() if str(value or "").strip() else "N/A"

                def metadata_row(left_label, left_value, right_label, right_value):
                    return ft.Row(controls=[
                        ft.Container(expand=True, padding=10, bgcolor="#101C2D", border=ft.Border.all(1, "#1C314A"), content=ft.Row(controls=[ft.Text(left_label + ":", width=105, weight=ft.FontWeight.BOLD), ft.Text(text_or_na(left_value), expand=True, selectable=True)])),
                        ft.Container(expand=True, padding=10, bgcolor="#101C2D", border=ft.Border.all(1, "#1C314A"), content=ft.Row(controls=[ft.Text(right_label + ":", width=115, weight=ft.FontWeight.BOLD), ft.Text(text_or_na(right_value), expand=True, selectable=True)])),
                    ])

                def render_tab(name):
                    active_tab["name"] = name
                    for button in tab_buttons.controls:
                        button.bgcolor = self.ui_accent_color if button.data == name else "#132033"
                        button.color = "#07101B" if button.data == name else "#DCE9F6"
                    tab_content.controls.clear()
                    current_release = next((r for r in mod["releases"] if r["version"] == versions.value), release)

                    if name == "Information":
                        latest = mod["releases"][0] if mod["releases"] else {}
                        tab_content.controls.extend([
                            metadata_row("Owner", mod.get("owner"), "Created", mod.get("created_at")),
                            metadata_row("Source", mod.get("source_url"), "Latest Version", latest.get("version")),
                            metadata_row("Homepage", mod.get("homepage"), "Factorio version", mod.get("factorio_version_display")),
                            metadata_row("License", mod.get("license"), "Downloaded by", f'{int(mod.get("downloads_count") or 0):,} users'),
                            ft.Container(
                                padding=16, margin=ft.Margin.only(top=6), bgcolor="#0D1726",
                                border=ft.Border.all(1, "#1C314A"), border_radius=8,
                                content=ft.Text(mod.get("description") or mod.get("summary") or "No description.", selectable=True),
                            ),
                        ])
                    elif name == "Downloads":
                        for item in mod["releases"]:
                            compatible = ".".join(str(item.get("factorio_version") or "").split(".")[:2]) == branch
                            tab_content.controls.append(ft.Container(
                                padding=11, bgcolor="#0D1726", border=ft.Border.all(1, "#1C314A"), border_radius=7,
                                content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                                    ft.Column(spacing=2, controls=[
                                        ft.Text(f'v{item["version"]}', weight=ft.FontWeight.BOLD),
                                        ft.Text(f'Factorio {item.get("factorio_version") or "?"} · {item.get("released_at") or ""}', size=10, color="#8FA6BF"),
                                    ]),
                                    ft.Text("Compatible" if compatible else "Other branch", color="#8FC7FF" if compatible else "#7C8DA1"),
                                ]),
                            ))
                    elif name == "Dependencies":
                        deps = (current_release or {}).get("dependencies") or []
                        if not deps:
                            tab_content.controls.append(ft.Text("No dependencies declared.", color="#8FA6BF"))
                        for dep in deps:
                            color = "#FF8C86" if dep.get("kind") == "incompatible" else ("#D8B56C" if dep.get("kind") == "optional" else "#DCE9F6")
                            tab_content.controls.append(ft.Container(
                                padding=10, bgcolor="#0D1726", border=ft.Border.all(1, "#1C314A"), border_radius=7,
                                content=ft.Row(controls=[ft.Icon(ft.Icons.ACCOUNT_TREE_OUTLINED, color=color), ft.Text(dep.get("raw") or dep.get("name"), color=color)]),
                            ))
                    elif name == "Changelog":
                        tab_content.controls.append(ft.Container(
                            padding=15, bgcolor="#0D1726", border=ft.Border.all(1, "#1C314A"), border_radius=8,
                            content=ft.Text(mod.get("changelog") or "No changelog supplied by the Mod Portal API.", selectable=True),
                        ))
                    else:
                        tab_content.controls.extend([
                            metadata_row("Total downloads", f'{int(mod.get("downloads_count") or 0):,}', "Releases", mod.get("release_count")),
                            metadata_row("Category", mod.get("category"), "Updated", mod.get("updated_at")),
                            metadata_row("Installed", (mod.get("installed") or {}).get("version") if mod.get("installed") else "No", "Portal ID", mod.get("name")),
                        ])
                    self.page.update()

                async def select_tab(ev):
                    render_tab(ev.control.data)

                for label in ("Information", "Downloads", "Dependencies", "Changelog", "Metrics"):
                    tab_buttons.controls.append(ft.Button(label, data=label, on_click=select_tab, bgcolor="#132033", color="#DCE9F6"))

                async def version_changed(ev):
                    if active_tab["name"] == "Dependencies":
                        render_tab("Dependencies")
                versions.on_select = version_changed

                header_stats = ft.Column(width=205, spacing=7, controls=[
                    ft.Text(mod.get("category") or "No category", size=12),
                    ft.Text(f'Factorio {mod.get("factorio_version_display") or "?"}', size=12),
                    ft.Text(f'↓ {int(mod.get("downloads_count") or 0):,}', size=12),
                    ft.Text(f'{mod.get("release_count", 0)} releases', size=12),
                ])

                detail_box.controls[:] = [
                    ft.Column(spacing=14, controls=[
                        ft.Row(controls=[ft.Button("Back to Search", icon=ft.Icons.ARROW_BACK, on_click=back_to_search)]),
                        ft.Container(
                            padding=14, bgcolor="#0B1422", border=ft.Border.all(1, "#1C314A"), border_radius=9,
                            content=ft.Column(spacing=12, controls=[
                                ft.Row(vertical_alignment=ft.CrossAxisAlignment.START, controls=[
                                    hero_icon,
                                    ft.Column(expand=True, spacing=7, controls=[
                                        ft.Text(mod["title"], size=25, weight=ft.FontWeight.BOLD, color="#EAF3FC"),
                                        ft.Text(f'by {mod["owner"]}', color=self.ui_accent_color, weight=ft.FontWeight.BOLD),
                                        ft.Divider(color="#1C314A"),
                                        ft.Text(mod.get("summary") or "", size=13, selectable=True),
                                    ]),
                                    header_stats,
                                ]),
                                ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                                    ft.Row(wrap=True, controls=[
                                        ft.Container(padding=ft.Padding.symmetric(horizontal=9, vertical=6), bgcolor="#13243A", border_radius=5, content=ft.Text(tag, size=10))
                                        for tag in (mod.get("tags") or [])[:8]
                                    ]),
                                    ft.Row(controls=[versions, ft.Button("Download / Install", icon=ft.Icons.DOWNLOAD, on_click=install_selected, disabled=not bool(releases))]),
                                ]),
                            ]),
                        ),
                        ft.Container(
                            padding=10, bgcolor="#0B1422", border=ft.Border.all(1, "#1C314A"), border_radius=9,
                            content=ft.Column(spacing=10, controls=[tab_buttons, ft.Divider(color="#1C314A"), tab_content]),
                        ),
                    ])
                ]
                render_tab("Information")
            except Exception as exc:
                detail_box.controls[:] = [
                    ft.Button("Back to Search", icon=ft.Icons.ARROW_BACK, on_click=lambda e: None),
                    ft.Text(str(exc), color="#ff8c86"),
                ]
            finally:
                self.set_status("Ready")
                self.page.update()

''',
)

# Replace Search final layout so full detail can hide the browser area.
replace_once(
    flet,
    '''        self.body.controls.extend([\n            tab_row,\n            search_bar,\n            detail_box,\n            ft.Row(vertical_alignment=ft.CrossAxisAlignment.START, controls=[filter_panel, results_panel]),\n        ])\n        await run_search(False)\n''',
    '''        browse_area = ft.Column(spacing=12, controls=[\n            tab_row,\n            search_bar,\n            ft.Row(vertical_alignment=ft.CrossAxisAlignment.START, controls=[filter_panel, results_panel]),\n        ])\n        detail_box.visible = False\n        self.body.controls.extend([detail_box, browse_area])\n        await run_search(False)\n''',
)

# Settings: add appearance customization and make updater wording mode-aware.
replace_once(
    flet,
    '''        deps = ft.Switch(label="Automatically install required dependencies", value=bool(cfg.get("install_dependencies", True)))\n        async def save(e):\n''',
    '''        deps = ft.Switch(label="Automatically install required dependencies", value=bool(cfg.get("install_dependencies", True)))\n        menu_color = ft.TextField(label="Menu / sidebar color", value=cfg.get("ui_menu_color", "#09111E"), width=200)\n        background_color = ft.TextField(label="Main background color", value=cfg.get("ui_background_color", "#070B14"), width=200)\n        accent_color = ft.TextField(label="Accent color", value=cfg.get("ui_accent_color", "#4EA1FF"), width=200)\n        preset = ft.Dropdown(\n            label="Color preset", value="custom", width=220,\n            options=[\n                ft.DropdownOption(key="custom", text="Custom"),\n                ft.DropdownOption(key="midnight", text="Midnight Blue"),\n                ft.DropdownOption(key="black", text="Pure Black"),\n                ft.DropdownOption(key="slate", text="Blue Slate"),\n                ft.DropdownOption(key="factorio", text="Factorio Dark"),\n            ],\n        )\n\n        async def apply_preset(e):\n            choices = {\n                "midnight": ("#09111E", "#070B14", "#4EA1FF"),\n                "black": ("#080A0E", "#030407", "#65A9FF"),\n                "slate": ("#111B2A", "#0B1220", "#68A7E8"),\n                "factorio": ("#17130F", "#0E0D0C", "#E48C30"),\n            }\n            if e.control.value in choices:\n                menu_color.value, background_color.value, accent_color.value = choices[e.control.value]\n                self.page.update()\n        preset.on_select = apply_preset\n\n        async def save(e):\n''',
)
replace_once(
    flet,
    '''                    "install_dependencies": deps.value, "factorio_executable": exe.value.strip(), "launch_args": args.value.strip(),\n                })\n                self.notify("Settings saved.")\n''',
    '''                    "install_dependencies": deps.value, "factorio_executable": exe.value.strip(), "launch_args": args.value.strip(),\n                    "ui_menu_color": menu_color.value.strip(), "ui_background_color": background_color.value.strip(),\n                    "ui_accent_color": accent_color.value.strip(),\n                })\n                self.apply_runtime_theme(manager.get_config())\n                self.notify("Settings saved and appearance applied.")\n''',
)
replace_once(
    flet,
    '''                mods_dir, factorio_version, exe, args, deps,\n                ft.Row(wrap=True, controls=[ft.Button("Save Settings", icon=ft.Icons.SAVE, on_click=save), ft.Button("Backup state", icon=ft.Icons.BACKUP, on_click=backup)]),\n                ft.Divider(color="#1C314A"),\n                ft.Text("Application Update", weight=ft.FontWeight.BOLD),\n''',
    '''                mods_dir, factorio_version, exe, args, deps,\n                ft.Divider(color="#1C314A"),\n                ft.Text("Appearance", weight=ft.FontWeight.BOLD),\n                ft.Text("Customize the menu/sidebar, main background and accent. Use #RRGGBB HEX colors.", size=11, color="#6F849B"),\n                ft.Row(wrap=True, controls=[preset, menu_color, background_color, accent_color]),\n                ft.Row(wrap=True, controls=[ft.Button("Save & Apply", icon=ft.Icons.PALETTE, on_click=save), ft.Button("Backup state", icon=ft.Icons.BACKUP, on_click=backup)]),\n                ft.Divider(color="#1C314A"),\n                ft.Text("Application Update", weight=ft.FontWeight.BOLD),\n''',
)
# Make update handler use EXE replacement when packaged.
replace_once(
    flet,
    '''                    self.notify("Update pulled successfully. Restarting Factorio Mod Manager...")\n                    self.page.update()\n                    schedule_restart(APP_DIR, delay=0.8)\n                    return\n''',
    '''                    self.notify("Update installed successfully. Restarting Factorio Mod Manager...")\n                    self.page.update()\n                    replacement = result.get("replacement_path")\n                    if replacement:\n                        schedule_executable_replace_and_restart(replacement, delay=0.8)\n                    else:\n                        schedule_restart(APP_DIR, delay=0.8)\n                    return\n''',
)

# ---------------------------------------------------------------------------
# Icon generator: original midnight-blue gear/download mark.
# ---------------------------------------------------------------------------
tools = ROOT / "tools"
tools.mkdir(exist_ok=True)
(tools / "generate_icon.py").write_text(r'''from pathlib import Path
import math
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
ASSETS.mkdir(exist_ok=True)
SIZE = 1024
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# Rounded midnight tile.
d.rounded_rectangle((44, 44, 980, 980), radius=210, fill="#08111F", outline="#1C314A", width=18)

# Gear teeth + body.
cx = cy = 512
for i in range(12):
    a = math.radians(i * 30)
    x = cx + math.cos(a) * 292
    y = cy + math.sin(a) * 292
    w, h = 92, 150
    box = (x - w/2, y - h/2, x + w/2, y + h/2)
    tooth = Image.new("RGBA", (SIZE, SIZE), (0,0,0,0))
    td = ImageDraw.Draw(tooth)
    td.rounded_rectangle(box, radius=22, fill="#4EA1FF")
    tooth = tooth.rotate(-(i * 30), center=(cx, cy), resample=Image.Resampling.BICUBIC)
    img.alpha_composite(tooth)
d = ImageDraw.Draw(img)
d.ellipse((242, 242, 782, 782), fill="#4EA1FF")
d.ellipse((344, 344, 680, 680), fill="#08111F")

# Download arrow in Factorio-orange for identity/contrast.
orange = "#F39A36"
d.rounded_rectangle((474, 320, 550, 590), radius=30, fill=orange)
d.polygon([(380, 540), (644, 540), (512, 704)], fill=orange)
d.rounded_rectangle((342, 724, 682, 786), radius=28, fill=orange)

png = ASSETS / "icon.png"
ico = ASSETS / "icon.ico"
img.save(png)
img.save(ico, sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
print(png)
print(ico)
''', encoding="utf-8")

# ---------------------------------------------------------------------------
# Packaging: EXE is primary Windows distribution. Remove BAT launchers.
# ---------------------------------------------------------------------------
for name in (
    "run_app.bat", "run_web.bat", "run_flet_web.bat", "install_windows.bat",
    "build_windows.bat", "build_web.bat",
):
    (ROOT / name).unlink(missing_ok=True)

scripts = ROOT / "scripts"
scripts.mkdir(exist_ok=True)
(scripts / "build_exe.ps1").write_text(r'''$ErrorActionPreference = "Stop"
python -m pip install -r requirements.txt
python -m pip install pyinstaller pillow
python tools/generate_icon.py
flet pack flet_app.py `
  --name FactorioModManager `
  --icon assets/icon.ico `
  --product-name "Factorio Mod Manager" `
  --product-version "3.0.0" `
  --file-version "3.0.0.0" `
  --file-description "Factorio Mod Manager" `
  --company-name "Community" `
  --bundle-id "dev.factorio.modmanager" `
  --yes
Write-Host "Built: dist\\FactorioModManager.exe"
''', encoding="utf-8")

# Persistent manual Windows release workflow for future versions.
workflows = ROOT / ".github" / "workflows"
workflows.mkdir(parents=True, exist_ok=True)
(workflows / "windows-exe-release.yml").write_text(r'''name: Build Windows EXE Release

on:
  workflow_dispatch:

permissions:
  contents: write

jobs:
  build:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'
      - name: Install dependencies
        shell: pwsh
        run: |
          python -m pip install --upgrade pip
          python -m pip install -r requirements.txt
          python -m pip install pyinstaller pillow
      - name: Generate icon
        run: python tools/generate_icon.py
      - name: Read version
        id: version
        shell: pwsh
        run: |
          $v = python -c "from app_version import APP_VERSION; print(APP_VERSION)"
          "version=$v" >> $env:GITHUB_OUTPUT
      - name: Build single-file EXE
        shell: pwsh
        run: |
          flet pack flet_app.py --name FactorioModManager --icon assets/icon.ico --product-name "Factorio Mod Manager" --product-version "${{ steps.version.outputs.version }}" --file-version "${{ steps.version.outputs.version }}.0" --file-description "Factorio Mod Manager" --company-name "Community" --bundle-id "dev.factorio.modmanager" --yes
      - uses: actions/upload-artifact@v4
        with:
          name: FactorioModManager-Windows-${{ steps.version.outputs.version }}
          path: dist/FactorioModManager.exe
      - name: Create/update GitHub Release
        shell: pwsh
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          $tag = "v${{ steps.version.outputs.version }}"
          gh release view $tag 2>$null
          if ($LASTEXITCODE -ne 0) {
            gh release create $tag dist/FactorioModManager.exe --title "Factorio Mod Manager $tag" --notes "Windows single-file EXE release. No Python or BAT launcher required."
          } else {
            gh release upload $tag dist/FactorioModManager.exe --clobber
          }
''', encoding="utf-8")

# Version/config metadata.
replace_once(ROOT / "pyproject.toml", 'version = "2.5.0"', 'version = "3.0.0"')
pyproject = ROOT / "pyproject.toml"
text = pyproject.read_text(encoding="utf-8")
if 'icon_background = "#08111F"' not in text:
    text = text.replace('[tool.flet]\n', '[tool.flet]\nicon_background = "#08111F"\n')
pyproject.write_text(text, encoding="utf-8")

# Changelog / release notes.
changelog = ROOT / "CHANGELOG.md"
old = changelog.read_text(encoding="utf-8")
changelog.write_text('''# Changelog\n\n## 3.0.0\n\n- Windows distribution moved from BAT launchers to a single-file `FactorioModManager.exe`.\n- New custom application icon for EXE, taskbar and window identity.\n- Added appearance customization for menu/sidebar, main background and accent colors.\n- Search results now open a full Mod Portal-style detail page with Information, Downloads, Dependencies, Changelog and Metrics views.\n- Packaged EXE updater now checks GitHub Releases instead of requiring Git.\n- Source-clone updater keeps fast-forward `git pull` support.\n- Retains v2.5 installed-mod and Mod Portal caching optimizations.\n\n'''+old.replace('# Changelog\n','',1), encoding='utf-8')

(ROOT / "RELEASE_NOTES_3.0.0.md").write_text('''# Factorio Mod Manager 3.0.0\n\nMajor desktop release.\n\n- Single-file Windows EXE; no Python/BAT launcher required for end users.\n- Original custom midnight-blue app icon.\n- Customizable sidebar/menu, main background and accent colors.\n- Full Mod Portal-style detail page when a Search result is opened.\n- Information / Downloads / Dependencies / Changelog / Metrics views.\n- EXE-aware GitHub Releases updater with automatic replacement + restart.\n''', encoding='utf-8')

# Static tests for the release changes.
tests = ROOT / "tests"
(tests / "test_v300_release.py").write_text(r'''from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]

from manager import FactorioModManager, ManagerError
from app_version import APP_VERSION


def main():
    assert APP_VERSION == "3.0.0"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        mgr = FactorioModManager(root / "config.json", project_root=ROOT)
        cfg = mgr.save_config({
            "mods_dir": str(root / "mods"),
            "ui_menu_color": "#123456",
            "ui_background_color": "#050A10",
            "ui_accent_color": "#55AAFF",
        })
        assert cfg["ui_menu_color"] == "#123456"
        try:
            mgr.save_config({"ui_menu_color": "blue"})
        except ManagerError:
            pass
        else:
            raise AssertionError("invalid color accepted")

    flet = (ROOT / "flet_app.py").read_text(encoding="utf-8")
    manager = (ROOT / "manager.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "windows-exe-release.yml").read_text(encoding="utf-8")
    assert "Menu / sidebar color" in flet
    assert "Information\", \"Downloads\", \"Dependencies\", \"Changelog\", \"Metrics" in flet
    assert "schedule_executable_replace_and_restart" in flet
    assert "_release_update_status" in manager
    assert "flet pack flet_app.py" in workflow
    assert not (ROOT / "run_app.bat").exists()
    print("v3.0.0 release tests: PASS")


if __name__ == "__main__":
    main()
''', encoding="utf-8")

# Make old updater regression version-agnostic.
updater_test = tests / "test_auto_restart_update.py"
if updater_test.exists():
    t = updater_test.read_text(encoding="utf-8")
    t = re.sub(r"assert 'version = \\\"[^\\\"]+\\\"' in pyproject", "assert 'version = \\\"3.0.0\\\"' in pyproject", t)
    t = t.replace('assert \'version = "2.5.0"\' in pyproject', 'assert \'version = "3.0.0"\' in pyproject')
    t = t.replace('assert \'version = "2.4.2"\' in pyproject', 'assert \'version = "3.0.0"\' in pyproject')
    updater_test.write_text(t, encoding="utf-8")

print("Applied Factorio Mod Manager v3.0.0 patch")
