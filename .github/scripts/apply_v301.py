from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: Path, old: str, new: str):
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected text not found in {path}: {old[:180]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------
(ROOT / "app_version.py").write_text('APP_VERSION = "3.0.1"\n', encoding="utf-8")

pyproject = ROOT / "pyproject.toml"
replace_once(pyproject, 'version = "3.0.0"', 'version = "3.0.1"')

# ---------------------------------------------------------------------------
# Flet UI: visual color selector + self-installing desktop portable EXE.
# ---------------------------------------------------------------------------
flet = ROOT / "flet_app.py"
replace_once(
    flet,
    "import asyncio\nimport sys\nfrom pathlib import Path\n",
    "import asyncio\nimport ctypes\nimport os\nimport shutil\nimport subprocess\nimport sys\nfrom pathlib import Path\n",
)
replace_once(
    flet,
    "from manager import FactorioModManager, ManagerError, BUILTIN_MODS\n",
    "from app_version import APP_VERSION\nfrom manager import FactorioModManager, ManagerError, BUILTIN_MODS\n",
)

insert_anchor = 'manager = FactorioModManager(app_data_dir() / "manager-config.json")\n\n\nclass FactorioFletUI:'
insert_code = '''manager = FactorioModManager(app_data_dir() / "manager-config.json")


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


class FactorioFletUI:'''
replace_once(flet, insert_anchor, insert_code)

old_colors = '''        menu_color = ft.TextField(label="Menu / sidebar color", value=cfg.get("ui_menu_color", "#09111E"), width=200)
        background_color = ft.TextField(label="Main background color", value=cfg.get("ui_background_color", "#070B14"), width=200)
        accent_color = ft.TextField(label="Accent color", value=cfg.get("ui_accent_color", "#4EA1FF"), width=200)
        preset = ft.Dropdown(
            label="Color preset", value="custom", width=220,
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
                menu_color.value, background_color.value, accent_color.value = choices[e.control.value]
                self.page.update()
        preset.on_select = apply_preset
'''

new_colors = '''        menu_color = ft.TextField(label="Kode HEX", value=cfg.get("ui_menu_color", "#09111E"), width=165)
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
'''
replace_once(flet, old_colors, new_colors)

replace_once(
    flet,
    '''                ft.Text("Appearance", weight=ft.FontWeight.BOLD),
                ft.Text("Customize the menu/sidebar, main background and accent. Use #RRGGBB HEX colors.", size=11, color="#6F849B"),
                ft.Row(wrap=True, controls=[preset, menu_color, background_color, accent_color]),
                ft.Row(wrap=True, controls=[ft.Button("Save & Apply", icon=ft.Icons.PALETTE, on_click=save), ft.Button("Backup state", icon=ft.Icons.BACKUP, on_click=backup)]),
''',
    '''                ft.Text("Appearance", weight=ft.FontWeight.BOLD),
                ft.Text("Pilih preset atau atur tiap warna dari palet lingkaran. Kode HEX dan preview warna selalu terlihat.", size=11, color="#6F849B"),
                ft.Row(wrap=True, controls=[preset]),
                menu_color_editor,
                background_color_editor,
                accent_color_editor,
                ft.Row(wrap=True, controls=[ft.Button("Save & Apply", icon=ft.Icons.PALETTE, on_click=save), ft.Button("Backup state", icon=ft.Icons.BACKUP, on_click=backup)]),
''',
)

replace_once(
    flet,
    'ft.Text("Checks this Git clone against origin/main and only pulls fast-forward updates.", size=11, color="#6F849B"),',
    'ft.Text("Source mode checks origin/main; packaged EXE mode checks GitHub Releases and updates the Desktop EXE.", size=11, color="#6F849B"),',
)

replace_once(
    flet,
    '''if __name__ == "__main__":
    mode = "app"
''',
    '''if __name__ == "__main__":
    if _install_packaged_exe_on_desktop():
        raise SystemExit(0)

    mode = "app"
''',
)

# ---------------------------------------------------------------------------
# Tests: make previous version checks version-aware and add v3.0.1 checks.
# ---------------------------------------------------------------------------
test250 = ROOT / "tests" / "test_v250_optimization.py"
replace_once(test250, 'assert \'version = "3.0.0"\' in project', 'assert \'version = "3.0.1"\' in project')

test300 = ROOT / "tests" / "test_v300_release.py"
replace_once(test300, 'assert APP_VERSION == "3.0.0"', 'assert APP_VERSION == "3.0.1"')
replace_once(test300, 'assert "Menu / sidebar color" in flet', 'assert "Menu / sidebar" in flet')
replace_once(test300, 'print("v3.0.0 release tests: PASS")', 'print("v3.0.x release regression tests: PASS")')

(ROOT / "tests" / "test_v301_color_desktop.py").write_text('''from pathlib import Path

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
''', encoding="utf-8")

# ---------------------------------------------------------------------------
# Documentation / release notes.
# ---------------------------------------------------------------------------
readme = ROOT / "README.md"
text = readme.read_text(encoding="utf-8")
append = '''

## v3.0.1 — Visual color picker + Desktop portable install

The Appearance page now shows a circular live preview beside every editable theme color,
a visible `#RRGGBB` field, and a **Pilih warna** dialog with a palette of circular swatches.
Preset colors continue to work and update every preview immediately.

On Windows, a packaged `FactorioModManager.exe` launched from Downloads or another folder
installs/relaunches itself from the user's real Windows Desktop folder. The app stores the
Desktop build version in its application-data directory so an older portable copy cannot
overwrite a newer Desktop build.
'''
if "## v3.0.1 — Visual color picker + Desktop portable install" not in text:
    readme.write_text(text.rstrip() + append + "\n", encoding="utf-8")

(ROOT / "RELEASE_NOTES_3.0.1.md").write_text('''# Factorio Mod Manager 3.0.1

- New visual color controls in Settings → Appearance.
- Circular live preview for menu, main background and accent colors.
- **Pilih warna** dialog with clickable circular color swatches.
- HEX `#RRGGBB` input remains available for exact custom colors.
- Presets update both the HEX fields and circle previews instantly.
- Windows portable EXE now copies/relaunches itself as `FactorioModManager.exe` on the real Desktop folder.
- Desktop version marker prevents an older downloaded EXE from overwriting a newer Desktop copy.
- Existing GitHub Releases auto-updater remains supported.
''', encoding="utf-8")

print("Applied Factorio Mod Manager v3.0.1 patch")
