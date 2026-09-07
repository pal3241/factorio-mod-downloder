from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import flet as ft

from manager import FactorioModManager, ManagerError, BUILTIN_MODS
from storage import app_data_dir

APP_DIR = Path(__file__).resolve().parent
manager = FactorioModManager(app_data_dir() / "manager-config.json")


class FactorioFletUI:
    def __init__(self, page: ft.Page):
        self.page = page
        self.current_index = 0
        self.installed = []
        self.issues = {"missing": [], "wrong_version": [], "incompatible": []}
        self.current_mod = None
        self.updates = []

        page.title = "Factorio Mod Manager"
        page.theme_mode = ft.ThemeMode.DARK
        page.padding = 0
        page.bgcolor = "#0e0d0c"
        if not page.web:
            page.window.width = 1180
            page.window.height = 760
            page.window.min_width = 840
            page.window.min_height = 580

        self.title = ft.Text("Installed Mods", size=28, weight=ft.FontWeight.BOLD)
        self.status = ft.Text("Ready", size=12, color="#a69d93")
        self.body = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=12)

        self.nav = ft.NavigationRail(
            selected_index=0,
            label_type=ft.NavigationRailLabelType.ALL,
            min_width=92,
            group_alignment=-0.9,
            bgcolor="#151310",
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
                ft.VerticalDivider(width=1, color="#39332b"),
                ft.Container(
                    expand=True,
                    padding=24,
                    content=ft.Column(
                        expand=True,
                        controls=[
                            ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                controls=[
                                    ft.Column(spacing=2, controls=[ft.Text("LOCAL MOD CONTROL", size=10, color="#e48c30"), self.title]),
                                    ft.Row(controls=[
                                        ft.IconButton(icon=ft.Icons.REFRESH, tooltip="Refresh", on_click=self.refresh_current),
                                        ft.Button("Launch Factorio", icon=ft.Icons.PLAY_ARROW, on_click=self.launch_factorio),
                                    ]),
                                ],
                            ),
                            ft.Divider(color="#39332b"),
                            ft.Container(expand=True, content=self.body),
                            ft.Divider(color="#39332b"),
                            self.status,
                        ],
                    ),
                ),
            ],
        )
        page.add(self.root)

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
            border=ft.Border.all(1, "#39332b"),
            border_radius=10,
            bgcolor="#191714",
            content=ft.Row(controls=[
                ft.Icon(icon, color="#e48c30"),
                ft.Column(spacing=1, controls=[ft.Text(label, size=11, color="#a69d93"), ft.Text(str(value), size=24, weight=ft.FontWeight.BOLD)]),
            ]),
        )

    async def render_installed(self):
        self.installed = await self.run_bg(manager.list_installed)
        self.issues = await self.run_bg(manager.dependency_issues)
        diag = await self.run_bg(manager.diagnostics)
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
                        border=ft.Border.all(1, "#39332b"),
                        border_radius=9,
                        bgcolor="#191714",
                        content=ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Row(expand=True, controls=[
                                    ft.CircleAvatar(content=ft.Text((mod["title"] or mod["name"])[:2].upper()), bgcolor="#2a241d", color="#e48c30"),
                                    ft.Column(expand=True, spacing=2, controls=[
                                        ft.Text(mod["title"], weight=ft.FontWeight.BOLD),
                                        ft.Text(f'{mod["name"]} · {mod["version"]} · Factorio {mod["factorio_version"] or "?"}', size=11, color="#a69d93"),
                                        ft.Text(mod["file"], size=10, color="#70685f"),
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

        status = ft.Text("", size=11, color="#a69d93")
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
                bgcolor="#1d1b18",
                border=ft.Border.all(1, "#39332b"),
                border_radius=8,
                content=ft.Column(spacing=5, controls=[
                    control,
                    *([ft.Text(helper_line, size=9, color="#77716b")] if setting.get("type") != "bool-setting" else []),
                    ft.Text(details, size=9, color="#77716b"),
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
                ft.Text(title, size=16, weight=ft.FontWeight.BOLD, color="#f2d29f"),
                ft.Text(note, size=9, color="#77716b"),
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
            status.color = "#a69d93"
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
            deps.append(ft.Text("No declared dependencies.", size=10, color="#77716b"))

        save_button = ft.Button(
            "Save Changes",
            icon=ft.Icons.SAVE,
            on_click=save_values,
            disabled=not bool(editors) or not bool(setting_state.get("dat_exists")),
        )
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row(controls=[
                ft.Icon(ft.Icons.SETTINGS_OUTLINED, color="#e48c30"),
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
                        ft.Text(f'ID: {name} · Factorio {mod.get("factorio_version") or "?"}', size=10, color="#a69d93"),
                        ft.Text(f'Settings stage: {files}', size=9, color="#77716b"),
                        ft.Text(dat_line, size=9, color="#e4b65f" if setting_state.get("factorio_running") else "#77716b"),
                        ft.Divider(color="#39332b"),
                        ft.Text("Factorio Mod Settings", weight=ft.FontWeight.BOLD),
                        *settings_controls,
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
                ft.Button("Check / Update", icon=ft.Icons.SYSTEM_UPDATE_ALT, on_click=update_mod, bgcolor="#24211e", color="#d8d0c7"),
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
            bgcolor="#171512",
            color="#eee7df",
            border_color="#49423a",
            focused_border_color="#a56d32",
            hint_style=ft.TextStyle(color="#77716b"),
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
                    bgcolor="#875a2e" if active else "#302d29",
                    color="#f5e5d3" if active else "#d8d0c7",
                ))

        def state_sets(group):
            if group == "category":
                return search_state["categories"], search_state["exclude_categories"]
            if group == "tag":
                return search_state["tags"], search_state["exclude_tags"]
            return search_state["expansions"], search_state["exclude_expansions"]

        def add_filter_group(title, group, items):
            filters_col.controls.append(ft.Text(title, size=17, weight=ft.FontWeight.BOLD, color="#f2d29f"))
            for item in items:
                inc_state, exc_state = state_sets(group)
                include = ft.Checkbox(label=item["label"], value=item["id"] in inc_state, expand=True)
                exclude = ft.IconButton(icon=ft.Icons.BLOCK, tooltip=f'Exclude {item["label"]}', icon_color="#d28b2f" if item["id"] in exc_state else "#77716b")

                async def include_changed(e, item_id=item["id"], g=group, checkbox=include, ban=exclude):
                    inc, exc = state_sets(g)
                    if checkbox.value:
                        inc.add(item_id); exc.discard(item_id); ban.icon_color = "#77716b"
                    else:
                        inc.discard(item_id)
                    search_state["page"] = 1
                    self.page.update()
                    await run_search(False)

                async def exclude_clicked(e, item_id=item["id"], g=group, checkbox=include, ban=exclude):
                    inc, exc = state_sets(g)
                    inc.discard(item_id); checkbox.value = False
                    if item_id in exc:
                        exc.remove(item_id); ban.icon_color = "#77716b"
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
        filters_col.controls.extend([ft.Text("Options", size=17, weight=ft.FontWeight.BOLD, color="#f2d29f"), deprecated])

        async def exact_lookup(e=None):
            value = query.value.strip()
            if not value:
                return
            self.set_status("Loading mod details...")
            detail_box.controls[:] = [ft.ProgressRing()]
            self.page.update()
            try:
                mod = await self.run_bg(manager.portal_view, value)
                branch = ".".join(str(manager.config["factorio_version"]).split(".")[:2])
                releases = [r for r in mod["releases"] if ".".join(str(r["factorio_version"] or "").split(".")[:2]) == branch]
                if not releases:
                    detail_box.controls[:] = [ft.Container(
                        padding=12, border=ft.Border.all(1, "#5c302d"), border_radius=8,
                        content=ft.Text(f'No compatible release for Factorio {branch}.', color="#ff8c86"),
                    )]
                    return

                versions = ft.Dropdown(
                    label="Version",
                    value=releases[0]["version"],
                    options=[ft.DropdownOption(key=r["version"], text=f'{r["version"]} — Factorio {r["factorio_version"]}') for r in releases],
                    expand=True,
                )

                async def install_selected(ev):
                    self.set_status(f'Installing {mod["name"]}...')
                    try:
                        result = await self.run_bg(manager.install, mod["name"], versions.value, None, True)
                        self.notify(f'Installed {mod["title"]} {versions.value}.' if result["installed"] else f'{mod["title"]} already current.')
                        await run_search(False)
                    except Exception as exc:
                        self.notify(str(exc), True)
                    finally:
                        self.set_status("Ready")

                if mod.get("thumbnail"):
                    icon = ft.Image(src=mod["thumbnail"], width=82, height=82, fit=ft.BoxFit.COVER)
                else:
                    icon = ft.Container(width=82, height=82, alignment=ft.Alignment.CENTER, bgcolor="#3a3733", content=ft.Text((mod["title"] or mod["name"])[:2].upper(), size=24, weight=ft.FontWeight.BOLD, color="#f2b25c"))

                detail_box.controls[:] = [ft.Container(
                    padding=14,
                    bgcolor="#191714",
                    border=ft.Border.all(1, "#493f34"),
                    border_radius=9,
                    content=ft.Column(spacing=10, controls=[
                        ft.Row(vertical_alignment=ft.CrossAxisAlignment.START, controls=[
                            icon,
                            ft.Column(expand=True, spacing=4, controls=[
                                ft.Text(mod["title"], size=20, weight=ft.FontWeight.BOLD, color="#f3d6a5"),
                                ft.Text(f'by {mod["owner"]} · {mod["downloads_count"]:,} downloads', size=11, color="#e99828"),
                                ft.Text(mod["summary"], size=12, color="#d8d0c7"),
                            ]),
                        ]),
                        ft.Row(controls=[versions, ft.Button("Install", icon=ft.Icons.DOWNLOAD, bgcolor="#49b65b", color="#07160a", on_click=install_selected)]),
                    ]),
                )]
            except Exception as exc:
                detail_box.controls[:] = [ft.Text(str(exc), color="#ff8c86")]
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
                            bgcolor="#373431", border=ft.Border.all(1, "#4a4641"), border_radius=3,
                            content=ft.Text(next((x["label"] for x in meta["tags"] if x["id"] == tag), tag), size=10, color="#c9c2ba"),
                        ) for tag in (mod.get("tags") or [])
                    ])
                    if not tags.controls:
                        tags.controls.append(ft.Text("No tags", size=10, color="#77716b"))

                    if mod.get("thumbnail"):
                        thumb = ft.Image(src=mod["thumbnail"], width=125, height=125, fit=ft.BoxFit.COVER)
                    else:
                        thumb = ft.Container(width=125, height=125, alignment=ft.Alignment.CENTER, bgcolor="#3a3733", content=ft.Text((mod["title"] or mod["name"])[:2].upper(), size=30, weight=ft.FontWeight.BOLD, color="#f2b25c"))

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
                                ft.Text(mod["summary"], size=12, color="#eee8df", max_lines=3),
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
                        bgcolor="#2d2b29",
                        border=ft.Border.all(1, "#49443e"),
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
                        bgcolor="#875a2e" if page_no == current_page else "#302d29",
                        color="#f5e5d3" if page_no == current_page else "#d8d0c7",
                    ))
            except Exception as exc:
                result_count.value = "Search failed"
                results_col.controls[:] = [ft.Text(str(exc), color="#ff8c86")]
            self.page.update()

        set_tab_styles()
        search_bar = ft.Row(controls=[query, ft.Button("Exact Lookup", on_click=exact_lookup, bgcolor="#24211e", color="#d8d0c7"), ft.Button("Search", icon=ft.Icons.SEARCH, on_click=submit_search, bgcolor="#2b2824", color="#e6ded5")])
        filter_panel = ft.Container(
            width=235,
            padding=14,
            bgcolor="#211f1c",
            border=ft.Border.all(1, "#403a33"),
            border_radius=7,
            content=filters_col,
        )
        results_panel = ft.Column(expand=True, spacing=9, controls=[
            ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[result_count, pagination]),
            results_col,
        ])

        self.body.controls.extend([
            tab_row,
            search_bar,
            detail_box,
            ft.Row(vertical_alignment=ft.CrossAxisAlignment.START, controls=[filter_panel, results_panel]),
        ])
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
                padding=12, border=ft.Border.all(1, "#39332b"), border_radius=9, bgcolor="#191714",
                content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                    ft.Column(spacing=2, controls=[ft.Text(item["title"] or item["name"], weight=ft.FontWeight.BOLD), ft.Text(f'{item["installed"]} → {item["latest"] or "?"}', size=11, color="#a69d93")]),
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
        self.body.controls.append(ft.Text("Profiles snapshot installed versions + enabled state.", size=11, color="#a69d93"))
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
                padding=12, border=ft.Border.all(1, "#39332b"), border_radius=9, bgcolor="#191714",
                content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                    ft.Column(spacing=2, controls=[ft.Text(profile["name"], weight=ft.FontWeight.BOLD), ft.Text(f'{profile["mod_count"]} mods · Factorio {profile["factorio_version"]}', size=11, color="#a69d93")]),
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
        async def save(e):
            try:
                await self.run_bg(manager.save_config, {
                    "mods_dir": mods_dir.value.strip(), "factorio_version": factorio_version.value.strip(),
                    "install_dependencies": deps.value, "factorio_executable": exe.value.strip(), "launch_args": args.value.strip(),
                })
                self.notify("Settings saved.")
            except Exception as exc: self.notify(str(exc), True)
        async def backup(e):
            try:
                r = await self.run_bg(manager.backup_state, "flet"); self.notify(f'Backup: {r["path"]}')
            except Exception as exc: self.notify(str(exc), True)

        app_update_text = ft.Text("Not checked yet.", size=11, color="#a69d93")
        pull_update_btn = ft.Button("Pull Update", icon=ft.Icons.DOWNLOAD, disabled=True, bgcolor="#2b2824", color="#e6ded5")

        async def check_app_update(e):
            e.control.disabled = True
            app_update_text.value = "Checking origin/main..."
            app_update_text.color = "#a69d93"
            self.page.update()
            try:
                result = await self.run_bg(manager.app_update_status, True)
                if not result.get("git_repo"):
                    app_update_text.value = result.get("message", "Not a Git clone.")
                    app_update_text.color = "#e4b65f"
                    pull_update_btn.disabled = True
                elif result.get("update_available"):
                    app_update_text.value = f'Update available: {result["local_short"]} → {result["remote_short"]} · {result["behind"]} commit(s) · {result.get("latest_subject") or ""}'
                    app_update_text.color = "#e4b65f"
                    pull_update_btn.disabled = bool(result.get("dirty") or result.get("ahead"))
                    if result.get("dirty"):
                        app_update_text.value += " · local changes detected; commit/stash first"
                else:
                    app_update_text.value = f'Up to date · {result.get("local_short", "?")}'
                    app_update_text.color = "#8fbf75"
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
            app_update_text.value = "Pulling update..."
            app_update_text.color = "#a69d93"
            self.page.update()
            try:
                result = await self.run_bg(manager.pull_app_update)
                if result.get("changed"):
                    after = result.get("after") or {}
                    app_update_text.value = f'Updated to {after.get("local_short", "new commit")}. Restart Factorio Mod Manager to load the new code.'
                    app_update_text.color = "#8fbf75"
                    self.notify("Update pulled successfully. Restart the app to apply it.")
                else:
                    app_update_text.value = "Already up to date."
                    app_update_text.color = "#8fbf75"
            except Exception as exc:
                app_update_text.value = str(exc)
                app_update_text.color = "#ff8c86"
            finally:
                e.control.disabled = True
                self.page.update()

        check_update_btn = ft.Button("Check App Update", icon=ft.Icons.REFRESH, on_click=check_app_update, bgcolor="#24211e", color="#d8d0c7")
        pull_update_btn.on_click = pull_app_update

        diag = await self.run_bg(manager.diagnostics)
        self.body.controls.extend([
            ft.Container(padding=16, border=ft.Border.all(1, "#39332b"), border_radius=10, bgcolor="#191714", content=ft.Column(controls=[
                mods_dir, factorio_version, exe, args, deps,
                ft.Row(wrap=True, controls=[ft.Button("Save Settings", icon=ft.Icons.SAVE, on_click=save), ft.Button("Backup state", icon=ft.Icons.BACKUP, on_click=backup)]),
                ft.Divider(color="#39332b"),
                ft.Text("Application Update", weight=ft.FontWeight.BOLD),
                ft.Text("Checks this Git clone against origin/main and only pulls fast-forward updates.", size=11, color="#77716b"),
                ft.Row(wrap=True, controls=[check_update_btn, pull_update_btn]),
                app_update_text,
            ])),
            ft.Container(padding=14, border=ft.Border.all(1, "#39332b"), border_radius=10, content=ft.Column(controls=[
                ft.Text("Diagnostics", weight=ft.FontWeight.BOLD),
                ft.Text(f'Mods dir: {diag["mods_dir"]}', size=11, color="#a69d93"),
                ft.Text(f'Installed: {diag["installed_count"]} · Enabled: {diag["enabled_count"]} · Dependency issues: {diag["dependency_issue_count"]}', size=11, color="#a69d93"),
                ft.Text(f'Duplicates: {len(diag["duplicates"])} · Invalid files: {len(diag["invalid_files"])}', size=11, color="#a69d93"),
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
    mode = "app"
    if "--web" in sys.argv:
        mode = "web"
    view = ft.AppView.WEB_BROWSER if mode == "web" else ft.AppView.FLET_APP
    ft.run(main, view=view, port=8550 if mode == "web" else 0)
