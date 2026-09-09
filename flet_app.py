from __future__ import annotations

import asyncio
import ctypes
import os
import shutil
import subprocess
import sys
from pathlib import Path

import flet as ft

from app_version import APP_VERSION
from manager import FactorioModManager, ManagerError, BUILTIN_MODS
from storage import app_data_dir
from process_restart import schedule_restart, schedule_executable_replace_and_restart

APP_DIR = Path(__file__).resolve().parent
manager = FactorioModManager(app_data_dir() / "manager-config.json")


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = []
    for item in str(value or "").strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in item if ch.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts or [0])


def _windows_desktop_dir() -> Path | None:
    if os.name != "nt":
        return None
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        # CSIDL_DESKTOPDIRECTORY = 0x0010. This follows redirected/OneDrive Desktop too.
        result = ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buffer)
        if result == 0 and buffer.value:
            return Path(buffer.value)
    except Exception:
        pass

    candidates = []
    if os.getenv("OneDrive"):
        candidates.append(Path(os.environ["OneDrive"]) / "Desktop")
    if os.getenv("USERPROFILE"):
        candidates.append(Path(os.environ["USERPROFILE"]) / "Desktop")
    candidates.append(Path.home() / "Desktop")
    return next((path for path in candidates if path.exists()), candidates[-1])


def _install_packaged_exe_on_desktop() -> bool:
    """Copy/relaunch the packaged Windows EXE from Desktop on first portable run."""
    if os.name != "nt" or not getattr(sys, "frozen", False) or "--web" in sys.argv:
        return False

    desktop = _windows_desktop_dir()
    if desktop is None:
        return False

    try:
        desktop.mkdir(parents=True, exist_ok=True)
        current = Path(sys.executable).resolve()
        target = (desktop / "FactorioModManager.exe").resolve()
        version_marker = app_data_dir() / "desktop-exe-version.txt"

        if current == target:
            version_marker.write_text(APP_VERSION, encoding="utf-8")
            return False

        installed_version = "0"
        if version_marker.exists():
            try:
                installed_version = version_marker.read_text(encoding="utf-8").strip() or "0"
            except OSError:
                pass

        should_copy = (not target.exists()) or _version_tuple(APP_VERSION) > _version_tuple(installed_version)
        if should_copy:
            temporary = target.with_name("FactorioModManager.new.exe")
            try:
                if temporary.exists():
                    temporary.unlink()
                shutil.copy2(current, temporary)
                os.replace(temporary, target)
                version_marker.write_text(APP_VERSION, encoding="utf-8")
            finally:
                try:
                    if temporary.exists():
                        temporary.unlink()
                except OSError:
                    pass

        if not target.exists():
            return False

        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen([str(target)], cwd=str(desktop), creationflags=flags)
        return True
    except OSError:
        # If Windows blocks the copy, keep running from the current location.
        return False


class FactorioFletUI:
    def __init__(self, page: ft.Page):
        self.page = page
        self.current_index = 0
        self.installed = []
        self.issues = {"missing": [], "wrong_version": [], "incompatible": []}
        self.current_mod = None
        self.updates = []

        cfg = manager.get_config()
        self.ui_background_color = cfg.get("ui_background_color", "#070B14")
        self.ui_menu_color = cfg.get("ui_menu_color", "#09111E")
        self.ui_accent_color = cfg.get("ui_accent_color", "#4EA1FF")

        page.title = "Factorio Mod Manager"
        page.theme_mode = ft.ThemeMode.DARK
        page.theme = ft.Theme(color_scheme_seed=self.ui_accent_color)
        page.padding = 0
        page.bgcolor = self.ui_background_color
        if not page.web:
            page.window.width = 1240
            page.window.height = 800
            page.window.min_width = 840
            page.window.min_height = 580

        self.title = ft.Text("Installed Mods", size=28, weight=ft.FontWeight.BOLD)
        self.status = ft.Text("Ready", size=12, color="#8FA6BF")
        self.body = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=12)

        self.nav = ft.NavigationRail(
            selected_index=0,
            label_type=ft.NavigationRailLabelType.ALL,
            min_width=92,
            group_alignment=-0.9,
            bgcolor=self.ui_menu_color,
            destinations=[
                ft.NavigationRailDestination(icon=ft.Icons.INVENTORY_2_OUTLINED, selected_icon=ft.Icons.INVENTORY_2, label="Installed"),
                ft.NavigationRailDestination(icon=ft.Icons.SEARCH, selected_icon=ft.Icons.TRAVEL_EXPLORE, label="Search"),
                ft.NavigationRailDestination(icon=ft.Icons.UPDATE, selected_icon=ft.Icons.SYSTEM_UPDATE_ALT, label="Updates"),
                ft.NavigationRailDestination(icon=ft.Icons.LAYERS_OUTLINED, selected_icon=ft.Icons.LAYERS, label="Profiles"),
                ft.NavigationRailDestination(icon=ft.Icons.SETTINGS_OUTLINED, selected_icon=ft.Icons.SETTINGS, label="Settings"),
            ],
            on_change=self.on_nav,
        )

        self.root = ft.Row(
            expand=True,
            spacing=0,
            controls=[
                self.nav,
                ft.VerticalDivider(width=1, color="#1C314A"),
                ft.Container(
                    expand=True,
                    padding=24,
                    content=ft.Column(
                        expand=True,
                        controls=[
                            ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                controls=[
                                    ft.Column(spacing=2, controls=[ft.Text("LOCAL MOD CONTROL", size=10, color="#4EA1FF"), self.title]),
                                    ft.Row(controls=[
                                        ft.IconButton(icon=ft.Icons.REFRESH, tooltip="Refresh", on_click=self.refresh_current),
                                        ft.Button("Launch Factorio", icon=ft.Icons.PLAY_ARROW, on_click=self.launch_factorio),
                                    ]),
                                ],
                            ),
                            ft.Divider(color="#1C314A"),
                            ft.Container(expand=True, content=self.body),
                            ft.Divider(color="#1C314A"),
                            self.status,
                        ],
                    ),
                ),
            ],
        )
        page.add(self.root)

    def apply_runtime_theme(self, cfg=None):
        cfg = cfg or manager.get_config()
        self.ui_background_color = cfg.get("ui_background_color", "#070B14")
        self.ui_menu_color = cfg.get("ui_menu_color", "#09111E")
        self.ui_accent_color = cfg.get("ui_accent_color", "#4EA1FF")
        self.page.bgcolor = self.ui_background_color
        self.page.theme = ft.Theme(color_scheme_seed=self.ui_accent_color)
        self.nav.bgcolor = self.ui_menu_color
        self.page.update()

    def set_status(self, text: str):
        self.status.value = text
        self.page.update()

    def notify(self, message: str, error: bool = False):
        self.page.show_dialog(
            ft.SnackBar(
                content=ft.Text(message),
                bgcolor="#5b2f2b" if error else "#26351f",
            )
        )
        self.page.update()

    async def run_bg(self, func, *args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)

    async def on_nav(self, e):
        self.current_index = int(e.control.selected_index)
        await self.render_current()

    async def refresh_current(self, e=None):
        await self.render_current(force=True)

    async def render_current(self, force=False):
        titles = ["Installed Mods", "Search Mods", "Updates", "Profiles", "Settings"]
        self.title.value = titles[self.current_index]
        self.body.controls.clear()
        self.set_status("Loading...")
        try:
            if self.current_index == 0:
                await self.render_installed()
            elif self.current_index == 1:
                await self.render_discover()
            elif self.current_index == 2:
                await self.render_updates(check=force)
            elif self.current_index == 3:
                await self.render_profiles()
            else:
                await self.render_settings()
            self.set_status("Ready")
        except Exception as exc:
            self.body.controls[:] = [ft.Text(str(exc), color="#ff8c86")]
            self.set_status("Error")
        self.page.update()

    def stat_card(self, label, value, icon):
        return ft.Container(
            expand=True,
            padding=16,
            border=ft.Border.all(1, "#1C314A"),
            border_radius=10,
            bgcolor="#0D1726",
            content=ft.Row(controls=[
                ft.Icon(icon, color="#4EA1FF"),
                ft.Column(spacing=1, controls=[ft.Text(label, size=11, color="#8FA6BF"), ft.Text(str(value), size=24, weight=ft.FontWeight.BOLD)]),
            ]),
        )

    async def render_installed(self):
        dashboard = await self.run_bg(manager.dashboard_state)
        self.installed = dashboard["mods"]
        self.issues = dashboard["issues"]
        diag = {"duplicates": dashboard["duplicates"], "invalid_files": dashboard["invalid_files"]}
        issue_count = sum(len(v) for v in self.issues.values())
        self.body.controls.append(ft.Row(controls=[
            self.stat_card("Installed", len(self.installed), ft.Icons.INVENTORY_2),
            self.stat_card("Enabled", sum(1 for m in self.installed if m["enabled"]), ft.Icons.CHECK_CIRCLE_OUTLINE),
            self.stat_card("Issues", issue_count, ft.Icons.WARNING_AMBER),
            self.stat_card("Duplicates", len(diag["duplicates"]), ft.Icons.CONTENT_COPY),
        ]))

        search = ft.TextField(label="Filter installed mods", prefix_icon=ft.Icons.SEARCH)
        list_col = ft.Column(spacing=8)

        def build_rows(query=""):
            q = query.lower().strip()
            list_col.controls.clear()
            for mod in self.installed:
                if q and q not in f'{mod["title"]} {mod["name"]} {mod["version"]}'.lower():
                    continue
                toggle = ft.Switch(value=bool(mod["enabled"]), data=mod["name"], on_change=self.toggle_mod)
                list_col.controls.append(
                    ft.Container(
                        padding=12,
                        border=ft.Border.all(1, "#1C314A"),
                        border_radius=9,
                        bgcolor="#0D1726",
                        content=ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Row(expand=True, controls=[
                                    ft.CircleAvatar(content=ft.Text((mod["title"] or mod["name"])[:2].upper()), bgcolor="#10243A", color="#4EA1FF"),
                                    ft.Column(expand=True, spacing=2, controls=[
                                        ft.Text(mod["title"], weight=ft.FontWeight.BOLD),
                                        ft.Text(f'{mod["name"]} · {mod["version"]} · Factorio {mod["factorio_version"] or "?"}', size=11, color="#8FA6BF"),
                                        ft.Text(mod["file"], size=10, color="#5F748C"),
                                    ]),
                                ]),
                                ft.Row(controls=[
                                    toggle,
                                    ft.IconButton(icon=ft.Icons.SETTINGS_OUTLINED, tooltip="Mod settings", data=mod["name"], on_click=self.show_mod_settings),
                                    ft.IconButton(icon=ft.Icons.SYSTEM_UPDATE_ALT, tooltip="Update", data=mod["name"], on_click=self.update_one),
                                    ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, tooltip="Remove", data=mod["name"], on_click=self.remove_one),
                                ]),
                            ],
                        ),
                    )
                )
            self.page.update()

        search.on_change = lambda e: build_rows(e.control.value)
        self.body.controls.append(search)

        if issue_count:
            issue_lines = []
            for item in self.issues["missing"]:
                issue_lines.append(ft.Text(f'Missing: {item["mod"]} → {item["requirement"]}', size=11, color="#e4b65f"))
            for item in self.issues["wrong_version"]:
                issue_lines.append(ft.Text(f'Version: {item["mod"]} → {item["requirement"]}', size=11, color="#e4b65f"))
            for item in self.issues["incompatible"]:
                issue_lines.append(ft.Text(f'Conflict: {item["mod"]} ↔ {item["dependency"]}', size=11, color="#ff8c86"))
            self.body.controls.append(ft.Container(
                padding=12, border=ft.Border.all(1, "#5c4828"), border_radius=9, bgcolor="#211c13",
                content=ft.Column(controls=[
                    ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[ft.Text("Dependency problems", weight=ft.FontWeight.BOLD), ft.Button("Repair", icon=ft.Icons.BUILD, on_click=self.repair_dependencies)]),
                    *issue_lines,
                ]),
            ))

        if diag["duplicates"]:
            self.body.controls.append(ft.Row(controls=[ft.Text(f'{len(diag["duplicates"])} duplicate mod group(s) detected.'), ft.Button("Clean duplicates", on_click=self.clean_duplicates)]))
        if diag["invalid_files"]:
            self.body.controls.append(ft.Text(f'{len(diag["invalid_files"])} invalid mod file(s) detected.', color="#ff8c86"))

        self.body.controls.append(list_col)
        build_rows()

    async def show_mod_settings(self, e):
        name = str(e.control.data or "")
        mod = next((item for item in self.installed if item.get("name") == name), None)
        if not mod:
            self.notify(f"Mod {name} tidak ditemukan.", True)
            return

        self.set_status(f"Reading settings for {name}...")
        try:
            setting_state = await self.run_bg(manager.mod_settings_state, name)
        except Exception as exc:
            self.notify(str(exc), True)
            self.set_status("Ready")
            return

        status = ft.Text("", size=11, color="#8FA6BF")
        enabled = ft.Switch(label="Enabled", value=bool(mod.get("enabled")))
        editors = {}
        dialog = None

        def value_text(value):
            if isinstance(value, dict) and {"r", "g", "b"}.issubset(value):
                return ", ".join(str(value.get(key, 1.0 if key == "a" else 0.0)) for key in ("r", "g", "b", "a"))
            if value is None:
                return ""
            return str(value)

        def setting_control(setting):
            setting_name = setting["name"]
            label = setting.get("display_name") or setting_name
            disabled = not bool(setting.get("editable", True))
            current = setting.get("current_value")
            if setting.get("type") == "bool-setting":
                control = ft.Switch(label=label, value=bool(current), disabled=disabled)
            else:
                helper = [f'{setting.get("type", "setting")} · {setting_name}']
                allowed = setting.get("allowed_values")
                if allowed:
                    helper.append("allowed: " + ", ".join(map(str, allowed)))
                minimum = setting.get("minimum_value")
                maximum = setting.get("maximum_value")
                if minimum is not None or maximum is not None:
                    helper.append(f'range: {minimum if minimum is not None else "-∞"} .. {maximum if maximum is not None else "∞"}')
                helper_line = " · ".join(helper)
                control = ft.TextField(
                    label=label,
                    value=value_text(current),
                    disabled=disabled,
                    dense=True,
                )
            editors[setting_name] = {"control": control, "setting": setting}
            source = setting.get("source") or "?"
            extra = " · detected from mod-settings.dat" if setting.get("detected_from_dat") else ""
            default = setting.get("default_value")
            details = f'Source: {source}{extra}'
            if default is not None:
                details += f' · default: {value_text(default)}'
            return ft.Container(
                padding=10,
                bgcolor="#0C1624",
                border=ft.Border.all(1, "#1C314A"),
                border_radius=8,
                content=ft.Column(spacing=5, controls=[
                    control,
                    *([ft.Text(helper_line, size=9, color="#6F849B")] if setting.get("type") != "bool-setting" else []),
                    ft.Text(details, size=9, color="#6F849B"),
                ]),
            )

        section_labels = {
            "startup": ("Startup", "Loaded before the data stage; restart Factorio after changing."),
            "runtime-global": ("Map", "Global runtime settings; an existing save can synchronize/override these values."),
            "runtime-per-user": ("Per player", "Local per-player runtime settings."),
        }
        settings_controls = []
        for section in ("startup", "runtime-global", "runtime-per-user"):
            items = [item for item in setting_state["settings"] if item.get("setting_type") == section]
            if not items:
                continue
            title, note = section_labels[section]
            settings_controls.extend([
                ft.Text(title, size=16, weight=ft.FontWeight.BOLD, color="#B9D8FF"),
                ft.Text(note, size=9, color="#6F849B"),
                *[setting_control(item) for item in items],
                ft.Container(height=3),
            ])

        if not settings_controls:
            settings_controls = [
                ft.Container(
                    padding=12,
                    bgcolor="#211c13",
                    border=ft.Border.all(1, "#5c4828"),
                    border_radius=8,
                    content=ft.Column(spacing=4, controls=[
                        ft.Text("No editable Factorio settings detected", weight=ft.FontWeight.BOLD, color="#e4b65f"),
                        *[ft.Text(text, size=10, color="#b9aea1") for text in setting_state.get("warnings", [])],
                    ]),
                )
            ]
        elif setting_state.get("warnings"):
            settings_controls = [
                *[ft.Text("⚠ " + text, size=9, color="#e4b65f") for text in setting_state["warnings"]],
                *settings_controls,
            ]

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

        async def save_values(ev):
            ev.control.disabled = True
            status.value = "Saving mod-settings.dat..."
            status.color = "#8FA6BF"
            self.page.update()
            changes = {}
            for setting_name, entry in editors.items():
                control = entry["control"]
                if control.disabled:
                    continue
                if entry["setting"].get("type") == "bool-setting":
                    changes[setting_name] = bool(control.value)
                else:
                    changes[setting_name] = control.value
            try:
                result = await self.run_bg(manager.save_mod_settings, name, changes)
                status.value = f'Saved {result["changed_count"]} setting(s). Backup: {result["backup"]}'
                if result.get("restart_required"):
                    status.value += " · Restart Factorio required for startup settings."
                status.color = "#8fbf75"
                self.notify("Mod settings saved." + (" Restart Factorio." if result.get("restart_required") else ""))
            except Exception as exc:
                status.value = str(exc)
                status.color = "#ff8c86"
            finally:
                ev.control.disabled = False
                self.page.update()

        async def update_mod(ev):
            ev.control.disabled = True
            status.value = f"Checking {name}..."
            self.page.update()
            try:
                result = await self.run_bg(manager.update_one, name)
                status.value = f'{name}: {result["from"]} → {result["to"]}' if result.get("updated") else f"{name} already current."
                status.color = "#8fbf75"
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
        files = ", ".join(setting_state.get("settings_files") or []) or "none detected"
        dat_line = f'mod-settings.dat: {setting_state.get("dat_version") or "not available"}'
        if setting_state.get("factorio_running"):
            dat_line += " · Factorio is running; close it before Save Changes"

        deps = []
        for dep in mod.get("dependencies") or []:
            raw = str(dep.get("raw") or dep.get("name") or "").strip()
            if raw:
                deps.append(ft.Text(f"• {raw}", size=10, color="#b9aea1"))
        if not deps:
            deps.append(ft.Text("No declared dependencies.", size=10, color="#6F849B"))

        save_button = ft.Button(
            "Save Changes",
            icon=ft.Icons.SAVE,
            on_click=save_values,
            disabled=not bool(editors) or not bool(setting_state.get("dat_exists")),
        )
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row(controls=[
                ft.Icon(ft.Icons.SETTINGS_OUTLINED, color="#4EA1FF"),
                ft.Text(f'Mod Settings — {mod.get("title") or name}', weight=ft.FontWeight.BOLD),
            ]),
            content=ft.Container(
                width=720,
                height=560,
                content=ft.Column(
                    scroll=ft.ScrollMode.AUTO,
                    spacing=9,
                    controls=[
                        ft.Row(controls=[enabled, ft.Container(expand=True), ft.Text(f'v{mod.get("version") or "?"}', color="#f2b25c")]),
                        ft.Text(f'ID: {name} · Factorio {mod.get("factorio_version") or "?"}', size=10, color="#8FA6BF"),
                        ft.Text(f'Settings stage: {files}', size=9, color="#6F849B"),
                        ft.Text(dat_line, size=9, color="#e4b65f" if setting_state.get("factorio_running") else "#6F849B"),
                        ft.Divider(color="#1C314A"),
                        ft.Text("Factorio Mod Settings", weight=ft.FontWeight.BOLD),
                        *settings_controls,
                        ft.Divider(color="#1C314A"),
                        ft.Text("Dependencies", weight=ft.FontWeight.BOLD),
                        *deps,
                        ft.Divider(color="#1C314A"),
                        status,
                    ],
                ),
            ),
            actions=[
                ft.Button("Open folder", icon=ft.Icons.FOLDER_OPEN, on_click=open_location, bgcolor="#0F1C2D", color="#D7E7F8"),
                ft.Button("Mod Portal", icon=ft.Icons.OPEN_IN_NEW, on_click=open_portal, bgcolor="#0F1C2D", color="#D7E7F8"),
                ft.Button("Check / Update", icon=ft.Icons.SYSTEM_UPDATE_ALT, on_click=update_mod, bgcolor="#0F1C2D", color="#D7E7F8"),
                save_button,
                ft.TextButton("Close", on_click=close_dialog),
            ],
        )
        self.page.show_dialog(dialog)
        self.set_status("Ready")
        self.page.update()

    async def toggle_mod(self, e):
        try:
            await self.run_bg(manager.set_enabled, e.control.data, bool(e.control.value))
            self.notify(f'{e.control.data} {"enabled" if e.control.value else "disabled"}.')
        except Exception as exc:
            e.control.value = not e.control.value
            self.notify(str(exc), True)

    async def update_one(self, e):
        name = e.control.data
        self.set_status(f"Updating {name}...")
        try:
            result = await self.run_bg(manager.update_one, name)
            if result.get("updated"):
                self.notify(f'{name}: {result["from"]} → {result["to"]}')
            else:
                self.notify(f'{name} already current.')
            await self.render_current()
        except Exception as exc:
            self.notify(str(exc), True)
            self.set_status("Ready")

    async def remove_one(self, e):
        name = e.control.data
        async def do_remove(force=False):
            try:
                await self.run_bg(manager.remove, name, force)
                self.notify(f"{name} removed.")
                await self.render_current()
            except Exception as exc:
                self.notify(str(exc), True)
        await do_remove(False)

    async def repair_dependencies(self, e):
        self.set_status("Repairing dependencies...")
        try:
            result = await self.run_bg(manager.repair_dependencies)
            self.notify(f'Repaired {len(result["repaired"])} dependency mod(s).')
            await self.render_current()
        except Exception as exc:
            self.notify(str(exc), True)

    async def clean_duplicates(self, e):
        try:
            result = await self.run_bg(manager.clean_duplicates)
            self.notify(f'Removed {len(result["removed"])} duplicate file(s).')
            await self.render_current()
        except Exception as exc:
            self.notify(str(exc), True)

    async def render_discover(self):
        meta = await self.run_bg(manager.portal_search_meta)
        search_state = {
            "sort": "last_updated_at",
            "page": 1,
            "query": "",
            "categories": set(),
            "exclude_categories": {"internal"},
            "tags": set(),
            "exclude_tags": set(),
            "expansions": set(),
            "exclude_expansions": set(),
            "show_deprecated": False,
        }

        query = ft.TextField(
            hint_text="Search mods by title, ID, summary, or author...",
            prefix_icon=ft.Icons.SEARCH,
            expand=True,
            bgcolor="#0A1422",
            color="#EAF2FB",
            border_color="#233B55",
            focused_border_color="#4EA1FF",
            hint_style=ft.TextStyle(color="#6F849B"),
        )
        result_count = ft.Text("Loading...", size=15, weight=ft.FontWeight.BOLD)
        results_col = ft.Column(spacing=10)
        pagination = ft.Row(spacing=4, alignment=ft.MainAxisAlignment.END)
        tab_row = ft.Row(spacing=4, scroll=ft.ScrollMode.AUTO)
        filters_col = ft.Column(spacing=2)
        detail_box = ft.Column(spacing=8)

        def set_tab_styles():
            tab_row.controls.clear()
            for mode in meta["sort_modes"]:
                active = search_state["sort"] == mode["id"]
                async def choose(e, mode_id=mode["id"]):
                    search_state["sort"] = mode_id
                    search_state["page"] = 1
                    set_tab_styles()
                    self.page.update()
                    await run_search(False)
                tab_row.controls.append(ft.Button(
                    mode["label"],
                    on_click=choose,
                    bgcolor="#173A5E" if active else "#101B2A",
                    color="#E7F2FF" if active else "#D7E7F8",
                ))

        def state_sets(group):
            if group == "category":
                return search_state["categories"], search_state["exclude_categories"]
            if group == "tag":
                return search_state["tags"], search_state["exclude_tags"]
            return search_state["expansions"], search_state["exclude_expansions"]

        def add_filter_group(title, group, items):
            filters_col.controls.append(ft.Text(title, size=17, weight=ft.FontWeight.BOLD, color="#B9D8FF"))
            for item in items:
                inc_state, exc_state = state_sets(group)
                include = ft.Checkbox(label=item["label"], value=item["id"] in inc_state, expand=True)
                exclude = ft.IconButton(icon=ft.Icons.BLOCK, tooltip=f'Exclude {item["label"]}', icon_color="#d28b2f" if item["id"] in exc_state else "#6F849B")

                async def include_changed(e, item_id=item["id"], g=group, checkbox=include, ban=exclude):
                    inc, exc = state_sets(g)
                    if checkbox.value:
                        inc.add(item_id); exc.discard(item_id); ban.icon_color = "#6F849B"
                    else:
                        inc.discard(item_id)
                    search_state["page"] = 1
                    self.page.update()
                    await run_search(False)

                async def exclude_clicked(e, item_id=item["id"], g=group, checkbox=include, ban=exclude):
                    inc, exc = state_sets(g)
                    inc.discard(item_id); checkbox.value = False
                    if item_id in exc:
                        exc.remove(item_id); ban.icon_color = "#6F849B"
                    else:
                        exc.add(item_id); ban.icon_color = "#d28b2f"
                    search_state["page"] = 1
                    self.page.update()
                    await run_search(False)

                include.on_change = include_changed
                exclude.on_click = exclude_clicked
                filters_col.controls.append(ft.Row(spacing=0, controls=[include, exclude]))

        add_filter_group("Expansion", "expansion", meta["expansions"])
        add_filter_group("Categories", "category", meta["categories"])
        add_filter_group("Tags", "tag", meta["tags"])

        deprecated = ft.Checkbox(label="Include deprecated mods", value=False)
        async def deprecated_changed(e):
            search_state["show_deprecated"] = bool(deprecated.value)
            search_state["page"] = 1
            await run_search(False)
        deprecated.on_change = deprecated_changed
        filters_col.controls.extend([ft.Text("Options", size=17, weight=ft.FontWeight.BOLD, color="#B9D8FF"), deprecated])

        async def exact_lookup(e=None):
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

        async def submit_search(e=None):
            search_state["query"] = query.value.strip()
            if search_state["query"] and search_state["sort"] == "highlighted":
                search_state["sort"] = "relevancy"
                set_tab_styles()
            search_state["page"] = 1
            await run_search(False)

        query.on_submit = submit_search

        def pretty_downloads(n):
            n = int(n or 0)
            if n >= 1_000_000:
                return f"{n/1_000_000:.1f}M"
            if n >= 1_000:
                return f"{n/1_000:.1f}K"
            return str(n)

        async def run_search(reset=False):
            if reset:
                search_state["page"] = 1
            result_count.value = "Searching Mod Portal..."
            results_col.controls[:] = [ft.ProgressRing()]
            pagination.controls.clear()
            self.page.update()
            try:
                data = await self.run_bg(
                    manager.search_mods,
                    search_state["query"],
                    sort_attribute=search_state["sort"],
                    page=search_state["page"],
                    page_size=20,
                    categories=list(search_state["categories"]),
                    exclude_categories=list(search_state["exclude_categories"]),
                    tags=list(search_state["tags"]),
                    exclude_tags=list(search_state["exclude_tags"]),
                    expansions=list(search_state["expansions"]),
                    exclude_expansions=list(search_state["exclude_expansions"]),
                    show_deprecated=search_state["show_deprecated"],
                )
                p = data["pagination"]
                search_state["page"] = p["page"]
                result_count.value = f'{p["count"]:,} mods found'
                results_col.controls.clear()

                for mod in data["results"]:
                    async def install_mod(e, name=mod["name"]):
                        self.set_status(f"Installing {name}...")
                        try:
                            result = await self.run_bg(manager.install, name, None, None, True)
                            self.notify(f'Installed {name}.' if result["installed"] else f'{name} already current.')
                            await run_search(False)
                        except Exception as exc:
                            self.notify(str(exc), True)
                        finally:
                            self.set_status("Ready")

                    async def open_details(e, name=mod["name"]):
                        query.value = name
                        await exact_lookup()

                    tags = ft.Row(spacing=4, wrap=True, controls=[
                        ft.Container(
                            padding=ft.Padding.symmetric(horizontal=8, vertical=5),
                            bgcolor="#132238", border=ft.Border.all(1, "#29445F"), border_radius=3,
                            content=ft.Text(next((x["label"] for x in meta["tags"] if x["id"] == tag), tag), size=10, color="#BDD0E2"),
                        ) for tag in (mod.get("tags") or [])
                    ])
                    if not tags.controls:
                        tags.controls.append(ft.Text("No tags", size=10, color="#6F849B"))

                    if mod.get("thumbnail"):
                        thumb = ft.Image(src=mod["thumbnail"], width=125, height=125, fit=ft.BoxFit.COVER)
                    else:
                        thumb = ft.Container(width=125, height=125, alignment=ft.Alignment.CENTER, bgcolor="#13263C", content=ft.Text((mod["title"] or mod["name"])[:2].upper(), size=30, weight=ft.FontWeight.BOLD, color="#f2b25c"))

                    local = mod.get("installed")
                    if local and not mod.get("update_available"):
                        install_btn = ft.Button(f'Installed {local["version"]}', disabled=True)
                    else:
                        label = "Update" if local else "Download"
                        install_btn = ft.Button(label, icon=ft.Icons.DOWNLOAD, bgcolor="#49b65b", color="#07160a", on_click=install_mod)

                    result_body = ft.Row(
                        vertical_alignment=ft.CrossAxisAlignment.START,
                        controls=[
                            thumb,
                            ft.Column(expand=True, spacing=5, controls=[
                                ft.TextButton(mod["title"], on_click=open_details, style=ft.ButtonStyle(color="#f3d6a5")),
                                ft.Text(f'by {mod["owner"]}', size=11, color="#e99828"),
                                ft.Text(mod["summary"], size=12, color="#EAF2FB", max_lines=3),
                                tags,
                            ]),
                            ft.Column(width=150, spacing=5, controls=[
                                ft.Text(mod.get("category") or "no-category", size=11),
                                ft.Text(f'Factorio {mod.get("factorio_version_display") or "?"}', size=11),
                                ft.Text(f'↓ {pretty_downloads(mod.get("downloads_count"))}', size=11),
                                ft.Text("Space Age" if mod.get("requires_space_age") else "", size=10, color="#cab9ff"),
                                install_btn,
                            ]),
                        ],
                    )
                    results_col.controls.append(ft.Container(
                        padding=12,
                        bgcolor="#0F1B2B",
                        border=ft.Border.all(1, "#223A54"),
                        border_radius=6,
                        content=result_body,
                    ))

                page_count = int(p.get("page_count") or 1)
                current_page = int(p.get("page") or 1)
                candidate_pages = sorted({1, page_count, current_page - 1, current_page, current_page + 1})
                candidate_pages = [x for x in candidate_pages if 1 <= x <= page_count]
                for page_no in candidate_pages:
                    async def go_page(e, target=page_no):
                        search_state["page"] = target
                        await run_search(False)
                    pagination.controls.append(ft.Button(
                        str(page_no), on_click=go_page,
                        bgcolor="#173A5E" if page_no == current_page else "#101B2A",
                        color="#E7F2FF" if page_no == current_page else "#D7E7F8",
                    ))
            except Exception as exc:
                result_count.value = "Search failed"
                results_col.controls[:] = [ft.Text(str(exc), color="#ff8c86")]
            self.page.update()

        set_tab_styles()
        search_bar = ft.Row(controls=[query, ft.Button("Exact Lookup", on_click=exact_lookup, bgcolor="#0F1C2D", color="#D7E7F8"), ft.Button("Search", icon=ft.Icons.SEARCH, on_click=submit_search, bgcolor="#102033", color="#DCE9F6")])
        filter_panel = ft.Container(
            width=235,
            padding=14,
            bgcolor="#0D1828",
            border=ft.Border.all(1, "#203852"),
            border_radius=7,
            content=filters_col,
        )
        results_panel = ft.Column(expand=True, spacing=9, controls=[
            ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[result_count, pagination]),
            results_col,
        ])

        browse_area = ft.Column(spacing=12, controls=[
            tab_row,
            search_bar,
            ft.Row(vertical_alignment=ft.CrossAxisAlignment.START, controls=[filter_panel, results_panel]),
        ])
        detail_box.visible = False
        self.body.controls.extend([detail_box, browse_area])
        await run_search(False)

    async def render_updates(self, check=False):
        if check or not self.updates:
            self.updates = await self.run_bg(manager.check_updates)
        update_count = sum(1 for x in self.updates if x.get("update_available"))
        self.body.controls.append(ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
            ft.Text(f"{update_count} update(s) available", size=16),
            ft.Row(controls=[ft.Button("Check", on_click=self.check_updates), ft.Button("Update All", icon=ft.Icons.SYSTEM_UPDATE_ALT, on_click=self.update_all)]),
        ]))
        for item in self.updates:
            async def do_update(e, name=item["name"]):
                e.control.data = name
                await self.update_one(e)
            self.body.controls.append(ft.Container(
                padding=12, border=ft.Border.all(1, "#1C314A"), border_radius=9, bgcolor="#0D1726",
                content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                    ft.Column(spacing=2, controls=[ft.Text(item["title"] or item["name"], weight=ft.FontWeight.BOLD), ft.Text(f'{item["installed"]} → {item["latest"] or "?"}', size=11, color="#8FA6BF")]),
                    ft.Button("Update", on_click=do_update) if item.get("update_available") else ft.Text("Current" if not item.get("error") else "Unavailable", color="#8fbf75" if not item.get("error") else "#ff8c86"),
                ]),
            ))

    async def check_updates(self, e):
        self.updates = await self.run_bg(manager.check_updates)
        await self.render_current()

    async def update_all(self, e):
        self.set_status("Updating all mods...")
        try:
            result = await self.run_bg(manager.update_all)
            self.notify(f'Updated {len(result["updated"])} mod(s); {len(result["errors"])} failed.')
            self.updates = []
            await self.render_current(force=True)
        except Exception as exc:
            self.notify(str(exc), True)

    async def render_profiles(self):
        profiles = await self.run_bg(manager.list_profiles)
        name = ft.TextField(label="New profile name", expand=True)
        async def save(e):
            try:
                result = await self.run_bg(manager.save_profile, name.value)
                self.notify(f'Profile {result["name"]} saved.')
                await self.render_current()
            except Exception as exc: self.notify(str(exc), True)
        self.body.controls.append(ft.Row(controls=[name, ft.Button("Save current", icon=ft.Icons.SAVE, on_click=save)]))
        self.body.controls.append(ft.Text("Profiles snapshot installed versions + enabled state.", size=11, color="#8FA6BF"))
        for profile in profiles:
            async def apply(e, n=profile["name"]):
                self.set_status(f"Applying profile {n}...")
                try:
                    result = await self.run_bg(manager.apply_profile, n)
                    self.notify(f'Applied {n}; {len(result["errors"])} error(s).')
                    self.set_status("Ready")
                except Exception as exc: self.notify(str(exc), True)
            async def delete(e, n=profile["name"]):
                try:
                    await self.run_bg(manager.delete_profile, n); self.notify(f'Deleted {n}.'); await self.render_current()
                except Exception as exc: self.notify(str(exc), True)
            self.body.controls.append(ft.Container(
                padding=12, border=ft.Border.all(1, "#1C314A"), border_radius=9, bgcolor="#0D1726",
                content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                    ft.Column(spacing=2, controls=[ft.Text(profile["name"], weight=ft.FontWeight.BOLD), ft.Text(f'{profile["mod_count"]} mods · Factorio {profile["factorio_version"]}', size=11, color="#8FA6BF")]),
                    ft.Row(controls=[ft.Button("Apply", on_click=apply), ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, on_click=delete)]),
                ]),
            ))

    async def render_settings(self):
        cfg = manager.get_config()
        mods_dir = ft.TextField(label="Factorio mods folder", value=cfg.get("mods_dir", ""))
        factorio_version = ft.TextField(label="Factorio version", value=cfg.get("factorio_version", "2.0"))
        exe = ft.TextField(label="Factorio executable", value=cfg.get("factorio_executable", ""), hint_text="C:\\Program Files\\Factorio\\bin\\x64\\factorio.exe")
        args = ft.TextField(label="Launch arguments", value=cfg.get("launch_args", ""))
        deps = ft.Switch(label="Automatically install required dependencies", value=bool(cfg.get("install_dependencies", True)))
        menu_color = ft.TextField(label="Kode HEX", value=cfg.get("ui_menu_color", "#09111E"), width=165)
        background_color = ft.TextField(label="Kode HEX", value=cfg.get("ui_background_color", "#070B14"), width=165)
        accent_color = ft.TextField(label="Kode HEX", value=cfg.get("ui_accent_color", "#4EA1FF"), width=165)

        palette_colors = [
            "#030407", "#070B14", "#09111E", "#0B1220", "#111827", "#1F2937",
            "#334155", "#64748B", "#E2E8F0", "#FFFFFF", "#EF4444", "#F97316",
            "#E48C30", "#F59E0B", "#EAB308", "#84CC16", "#22C55E", "#10B981",
            "#14B8A6", "#06B6D4", "#0EA5E9", "#3B82F6", "#4EA1FF", "#6366F1",
            "#8B5CF6", "#A855F7", "#D946EF", "#EC4899", "#F43F5E", "#A16207",
        ]

        def normalize_hex(value):
            text = str(value or "").strip().upper()
            if text and not text.startswith("#"):
                text = "#" + text
            if len(text) == 7 and text[0] == "#" and all(ch in "0123456789ABCDEF" for ch in text[1:]):
                return text
            return None

        def make_color_editor(label, field):
            initial = normalize_hex(field.value) or "#000000"
            field.value = initial
            preview = ft.Container(
                width=44,
                height=44,
                bgcolor=initial,
                border_radius=22,
                border=ft.Border.all(2, "#71839A"),
            )

            def sync_field_preview(e):
                selected = normalize_hex(field.value)
                if selected:
                    preview.bgcolor = selected
                    self.page.update()

            field.on_change = sync_field_preview

            def open_color_dialog(e):
                dialog_preview = ft.Container(
                    width=70,
                    height=70,
                    bgcolor=preview.bgcolor,
                    border_radius=35,
                    border=ft.Border.all(3, "#B7C7D9"),
                )
                dialog_code = ft.TextField(label="Kode warna HEX", value=field.value, width=205)
                error_text = ft.Text("", size=11, color="#FF8C86")

                def set_dialog_color(value):
                    selected = normalize_hex(value)
                    if selected:
                        dialog_code.value = selected
                        dialog_preview.bgcolor = selected
                        error_text.value = ""
                        self.page.update()

                def dialog_code_changed(ev):
                    selected = normalize_hex(dialog_code.value)
                    if selected:
                        dialog_preview.bgcolor = selected
                        error_text.value = ""
                    else:
                        error_text.value = "Gunakan format #RRGGBB, contoh #4EA1FF."
                    self.page.update()

                dialog_code.on_change = dialog_code_changed
                swatches = [
                    ft.Container(
                        width=34,
                        height=34,
                        bgcolor=color,
                        border_radius=17,
                        border=ft.Border.all(2, "#D8E4F0" if color in ("#030407", "#070B14", "#09111E") else "#2A3A4E"),
                        ink=True,
                        on_click=lambda ev, selected=color: set_dialog_color(selected),
                    )
                    for color in palette_colors
                ]

                def apply_dialog_color(ev):
                    selected = normalize_hex(dialog_code.value)
                    if not selected:
                        error_text.value = "Kode warna belum valid. Gunakan #RRGGBB."
                        self.page.update()
                        return
                    field.value = selected
                    preview.bgcolor = selected
                    self.page.pop_dialog()
                    self.page.update()

                dialog = ft.AlertDialog(
                    modal=True,
                    title=ft.Text(f"Pilih warna — {label}"),
                    content=ft.Container(
                        width=430,
                        content=ft.Column(spacing=13, controls=[
                            ft.Row(spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                                dialog_preview,
                                ft.Column(spacing=3, controls=[
                                    ft.Text("Preview warna", weight=ft.FontWeight.BOLD),
                                    ft.Text("Pilih lingkaran warna atau masukkan kode HEX.", size=11, color="#8FA6BF"),
                                ]),
                            ]),
                            ft.Divider(color="#263B52"),
                            ft.Text("Pilihan warna", weight=ft.FontWeight.BOLD),
                            ft.Row(wrap=True, spacing=8, run_spacing=8, controls=swatches),
                            ft.Divider(color="#263B52"),
                            ft.Row(wrap=True, controls=[dialog_code]),
                            error_text,
                        ]),
                    ),
                    actions=[
                        ft.TextButton("Batal", on_click=lambda ev: self.page.pop_dialog()),
                        ft.Button("Gunakan warna", icon=ft.Icons.CHECK, on_click=apply_dialog_color),
                    ],
                    actions_alignment=ft.MainAxisAlignment.END,
                )
                self.page.show_dialog(dialog)

            card = ft.Container(
                padding=12,
                bgcolor="#101A29",
                border=ft.Border.all(1, "#223A54"),
                border_radius=9,
                content=ft.Row(wrap=True, spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                    ft.Column(width=185, spacing=2, controls=[
                        ft.Text(label, weight=ft.FontWeight.BOLD),
                        ft.Text("Klik Pilih warna untuk membuka palet.", size=10, color="#7F93AA"),
                    ]),
                    preview,
                    field,
                    ft.Button("Pilih warna", icon=ft.Icons.COLOR_LENS_OUTLINED, on_click=open_color_dialog),
                ]),
            )
            return card, preview

        menu_color_editor, menu_color_preview = make_color_editor("Menu / sidebar", menu_color)
        background_color_editor, background_color_preview = make_color_editor("Background utama", background_color)
        accent_color_editor, accent_color_preview = make_color_editor("Accent / highlight", accent_color)

        preset = ft.Dropdown(
            label="Preset warna", value="custom", width=240,
            options=[
                ft.DropdownOption(key="custom", text="Custom"),
                ft.DropdownOption(key="midnight", text="Midnight Blue"),
                ft.DropdownOption(key="black", text="Pure Black"),
                ft.DropdownOption(key="slate", text="Blue Slate"),
                ft.DropdownOption(key="factorio", text="Factorio Dark"),
            ],
        )

        async def apply_preset(e):
            choices = {
                "midnight": ("#09111E", "#070B14", "#4EA1FF"),
                "black": ("#080A0E", "#030407", "#65A9FF"),
                "slate": ("#111B2A", "#0B1220", "#68A7E8"),
                "factorio": ("#17130F", "#0E0D0C", "#E48C30"),
            }
            if e.control.value in choices:
                menu_value, background_value, accent_value = choices[e.control.value]
                menu_color.value = menu_value
                background_color.value = background_value
                accent_color.value = accent_value
                menu_color_preview.bgcolor = menu_value
                background_color_preview.bgcolor = background_value
                accent_color_preview.bgcolor = accent_value
                self.page.update()
        preset.on_select = apply_preset

        async def save(e):
            try:
                await self.run_bg(manager.save_config, {
                    "mods_dir": mods_dir.value.strip(), "factorio_version": factorio_version.value.strip(),
                    "install_dependencies": deps.value, "factorio_executable": exe.value.strip(), "launch_args": args.value.strip(),
                    "ui_menu_color": menu_color.value.strip(), "ui_background_color": background_color.value.strip(),
                    "ui_accent_color": accent_color.value.strip(),
                })
                self.apply_runtime_theme(manager.get_config())
                self.notify("Settings saved and appearance applied.")
            except Exception as exc: self.notify(str(exc), True)
        async def backup(e):
            try:
                r = await self.run_bg(manager.backup_state, "flet"); self.notify(f'Backup: {r["path"]}')
            except Exception as exc: self.notify(str(exc), True)

        app_update_text = ft.Text("Not checked yet.", size=11, color="#8FA6BF")
        pull_update_btn = ft.Button("Pull Update", icon=ft.Icons.DOWNLOAD, disabled=True, bgcolor="#102033", color="#DCE9F6")

        async def check_app_update(e):
            e.control.disabled = True
            app_update_text.value = "Checking origin/main..."
            app_update_text.color = "#8FA6BF"
            self.page.update()
            try:
                result = await self.run_bg(manager.app_update_status, True)
                mode = result.get("mode")
                if mode == "release":
                    if result.get("update_available"):
                        size_mb = int(result.get("asset_size") or 0) / (1024 * 1024)
                        app_update_text.value = f'EXE update available: v{result.get("current_version", "?")} → v{result.get("latest_version", "?")} · {size_mb:.1f} MB · {result.get("latest_subject") or ""}'
                        app_update_text.color = "#e4b65f"
                        pull_update_btn.text = "Download & Install"
                        pull_update_btn.disabled = not bool(result.get("download_url"))
                    else:
                        app_update_text.value = f'Up to date · v{result.get("current_version", "?")}'
                        app_update_text.color = "#8fbf75"
                        pull_update_btn.text = "Download & Install"
                        pull_update_btn.disabled = True
                elif not result.get("git_repo"):
                    app_update_text.value = result.get("message", "Not a Git clone.")
                    app_update_text.color = "#e4b65f"
                    pull_update_btn.disabled = True
                elif result.get("update_available"):
                    app_update_text.value = f'Update available: {result["local_short"]} → {result["remote_short"]} · {result["behind"]} commit(s) · {result.get("latest_subject") or ""}'
                    app_update_text.color = "#e4b65f"
                    pull_update_btn.text = "Pull Update"
                    pull_update_btn.disabled = bool(result.get("dirty") or result.get("ahead"))
                    if result.get("dirty"):
                        app_update_text.value += " · local changes detected; commit/stash first"
                else:
                    app_update_text.value = f'Up to date · {result.get("local_short", "?")}'
                    app_update_text.color = "#8fbf75"
                    pull_update_btn.text = "Pull Update"
                    pull_update_btn.disabled = True
            except Exception as exc:
                app_update_text.value = str(exc)
                app_update_text.color = "#ff8c86"
                pull_update_btn.disabled = True
            finally:
                e.control.disabled = False
                self.page.update()

        async def pull_app_update(e):
            e.control.disabled = True
            app_update_text.value = "Downloading / applying update..."
            app_update_text.color = "#8FA6BF"
            self.page.update()
            try:
                result = await self.run_bg(manager.pull_app_update)
                if result.get("changed"):
                    after = result.get("after") or {}
                    app_update_text.value = f'Updated to {after.get("local_short", "new commit")}. Restarting automatically...'
                    app_update_text.color = "#8fbf75"
                    self.notify("Update installed successfully. Restarting Factorio Mod Manager...")
                    self.page.update()
                    replacement = result.get("replacement_path")
                    if replacement:
                        schedule_executable_replace_and_restart(replacement, delay=0.8)
                    else:
                        schedule_restart(APP_DIR, delay=0.8)
                    return
                else:
                    app_update_text.value = "Already up to date."
                    app_update_text.color = "#8fbf75"
            except Exception as exc:
                app_update_text.value = str(exc)
                app_update_text.color = "#ff8c86"
            finally:
                e.control.disabled = True
                self.page.update()

        check_update_btn = ft.Button("Check App Update", icon=ft.Icons.REFRESH, on_click=check_app_update, bgcolor="#0F1C2D", color="#D7E7F8")
        pull_update_btn.on_click = pull_app_update

        diag = await self.run_bg(manager.diagnostics)
        self.body.controls.extend([
            ft.Container(padding=16, border=ft.Border.all(1, "#1C314A"), border_radius=10, bgcolor="#0D1726", content=ft.Column(controls=[
                mods_dir, factorio_version, exe, args, deps,
                ft.Divider(color="#1C314A"),
                ft.Text("Appearance", weight=ft.FontWeight.BOLD),
                ft.Text("Pilih preset atau atur tiap warna dari palet lingkaran. Kode HEX dan preview warna selalu terlihat.", size=11, color="#6F849B"),
                ft.Row(wrap=True, controls=[preset]),
                menu_color_editor,
                background_color_editor,
                accent_color_editor,
                ft.Row(wrap=True, controls=[ft.Button("Save & Apply", icon=ft.Icons.PALETTE, on_click=save), ft.Button("Backup state", icon=ft.Icons.BACKUP, on_click=backup)]),
                ft.Divider(color="#1C314A"),
                ft.Text("Application Update", weight=ft.FontWeight.BOLD),
                ft.Text("Source mode checks origin/main; packaged EXE mode checks GitHub Releases and updates the Desktop EXE.", size=11, color="#6F849B"),
                ft.Row(wrap=True, controls=[check_update_btn, pull_update_btn]),
                app_update_text,
            ])),
            ft.Container(padding=14, border=ft.Border.all(1, "#1C314A"), border_radius=10, content=ft.Column(controls=[
                ft.Text("Diagnostics", weight=ft.FontWeight.BOLD),
                ft.Text(f'Mods dir: {diag["mods_dir"]}', size=11, color="#8FA6BF"),
                ft.Text(f'Installed: {diag["installed_count"]} · Enabled: {diag["enabled_count"]} · Dependency issues: {diag["dependency_issue_count"]}', size=11, color="#8FA6BF"),
                ft.Text(f'Duplicates: {len(diag["duplicates"])} · Invalid files: {len(diag["invalid_files"])}', size=11, color="#8FA6BF"),
            ])),
        ])

    async def launch_factorio(self, e):
        try:
            result = await self.run_bg(manager.launch_factorio)
            self.notify(f'Factorio started (PID {result["pid"]}).')
        except Exception as exc:
            self.notify(str(exc), True)


async def main(page: ft.Page):
    ui = FactorioFletUI(page)
    await ui.render_current()


if __name__ == "__main__":
    if _install_packaged_exe_on_desktop():
        raise SystemExit(0)

    mode = "app"
    if "--web" in sys.argv:
        mode = "web"
    view = ft.AppView.WEB_BROWSER if mode == "web" else ft.AppView.FLET_APP
    ft.run(main, view=view, port=8550 if mode == "web" else 0)
