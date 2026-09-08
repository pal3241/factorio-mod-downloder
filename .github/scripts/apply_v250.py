from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: Path, old: str, new: str):
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected text not found in {path}: {old[:160]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_all(path: Path, mapping: dict[str, str]):
    text = path.read_text(encoding="utf-8")
    for old, new in mapping.items():
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Core performance pass
# ---------------------------------------------------------------------------
manager = ROOT / "manager.py"
replace_once(
    manager,
    "import json\nimport os\nimport platform\n",
    "import copy\nimport json\nimport os\nimport platform\n",
)
replace_once(
    manager,
    "import hashlib\nimport uuid\nimport webbrowser\n",
    "import hashlib\nimport threading\nimport time\nimport uuid\nimport webbrowser\n",
)
replace_once(
    manager,
    '''        self.session.headers.update({\n            "User-Agent": "Factorio-Local-Mod-Manager/1.0"\n        })\n\n        self.config = self._load_config()\n''',
    '''        self.session.headers.update({\n            "User-Agent": "Factorio-Local-Mod-Manager/1.0"\n        })\n        self._cache_lock = threading.RLock()\n        self._installed_cache_signature = None\n        self._installed_cache_items: list[dict[str, Any]] = []\n        self._portal_mod_cache: dict[str, tuple[float, dict[str, Any]]] = {}\n        self._portal_cache_ttl = 120.0\n\n        self.config = self._load_config()\n''',
)

old_list = '''    def list_installed(self) -> list[dict[str, Any]]:\n        self.mods_dir.mkdir(parents=True, exist_ok=True)\n        enabled = self._enabled_map()\n        items: list[dict[str, Any]] = []\n\n        for path in sorted(self.mods_dir.iterdir(), key=lambda p: p.name.lower()):\n            if path.name.startswith(".") or path.name in {"mod-list.json", "mod-list.json.bak"}:\n                continue\n\n            info = None\n            kind = None\n\n            if path.is_file() and path.suffix.lower() == ".zip":\n                info = self._read_info_from_zip(path)\n                kind = "zip"\n            elif path.is_dir():\n                info = self._read_info_from_dir(path)\n                kind = "folder"\n\n            if not info or not isinstance(info.get("name"), str):\n                continue\n\n            name = info["name"]\n            dependencies = [\n                parse_dependency(dep).__dict__\n                for dep in (info.get("dependencies") or [])\n                if isinstance(dep, str)\n            ]\n\n            items.append({\n                "name": name,\n                "title": info.get("title") or name,\n                "version": str(info.get("version") or ""),\n                "factorio_version": str(info.get("factorio_version") or ""),\n                "author": info.get("author") or "",\n                "description": info.get("description") or "",\n                "enabled": enabled.get(name, True),\n                "file": path.name,\n                "path": str(path),\n                "kind": kind,\n                "has_settings": self._mod_has_settings(path, kind),\n                "dependencies": dependencies,\n            })\n\n        items.sort(key=lambda x: (x["title"].lower(), version_obj(x["version"] or "0")), reverse=False)\n        return items\n'''

new_list = '''    def _installed_signature(self) -> tuple[Any, ...]:\n        """Cheap filesystem fingerprint used to avoid reopening every mod ZIP."""\n        self.mods_dir.mkdir(parents=True, exist_ok=True)\n        signature: list[Any] = []\n        try:\n            mod_list_stat = self.mod_list_path.stat()\n            signature.append(("mod-list", mod_list_stat.st_mtime_ns, mod_list_stat.st_size))\n        except OSError:\n            signature.append(("mod-list", 0, 0))\n\n        for path in sorted(self.mods_dir.iterdir(), key=lambda p: p.name.lower()):\n            if path.name.startswith(".") or path.name in {"mod-list.json", "mod-list.json.bak"}:\n                continue\n            try:\n                if path.is_file() and path.suffix.lower() == ".zip":\n                    stat = path.stat()\n                    signature.append(("zip", path.name, stat.st_mtime_ns, stat.st_size))\n                elif path.is_dir():\n                    info_path = path / "info.json"\n                    try:\n                        stat = info_path.stat()\n                        info_sig = (stat.st_mtime_ns, stat.st_size)\n                    except OSError:\n                        info_sig = (0, 0)\n                    stage_presence = tuple(name for name in SETTINGS_STAGE_FILES if (path / name).exists())\n                    signature.append(("dir", path.name, info_sig, stage_presence))\n            except OSError:\n                continue\n        return tuple(signature)\n\n    def _read_mod_zip_manifest(self, path: Path) -> tuple[dict[str, Any] | None, bool]:\n        """Read info.json and settings-stage presence with one ZIP open."""\n        try:\n            with zipfile.ZipFile(path, "r") as archive:\n                names = archive.namelist()\n                candidates = [name for name in names if name.endswith("/info.json") or name == "info.json"]\n                if not candidates:\n                    return None, False\n                candidates.sort(key=lambda x: (x.count("/"), len(x)))\n                raw = archive.read(candidates[0]).decode("utf-8-sig")\n                info = json.loads(raw)\n                if not isinstance(info, dict):\n                    return None, False\n                has_settings = any(\n                    member.rsplit("/", 1)[-1] in SETTINGS_STAGE_FILES\n                    for member in names\n                )\n                return info, has_settings\n        except (OSError, zipfile.BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError):\n            return None, False\n\n    def list_installed(self) -> list[dict[str, Any]]:\n        self.mods_dir.mkdir(parents=True, exist_ok=True)\n        signature = self._installed_signature()\n        with self._cache_lock:\n            if signature == self._installed_cache_signature:\n                return copy.deepcopy(self._installed_cache_items)\n\n        enabled = self._enabled_map()\n        items: list[dict[str, Any]] = []\n\n        for path in sorted(self.mods_dir.iterdir(), key=lambda p: p.name.lower()):\n            if path.name.startswith(".") or path.name in {"mod-list.json", "mod-list.json.bak"}:\n                continue\n\n            info = None\n            kind = None\n            has_settings = False\n\n            if path.is_file() and path.suffix.lower() == ".zip":\n                info, has_settings = self._read_mod_zip_manifest(path)\n                kind = "zip"\n            elif path.is_dir():\n                info = self._read_info_from_dir(path)\n                kind = "folder"\n                has_settings = any((path / name).exists() for name in SETTINGS_STAGE_FILES)\n\n            if not info or not isinstance(info.get("name"), str):\n                continue\n\n            name = info["name"]\n            dependencies = [\n                parse_dependency(dep).__dict__\n                for dep in (info.get("dependencies") or [])\n                if isinstance(dep, str)\n            ]\n\n            items.append({\n                "name": name,\n                "title": info.get("title") or name,\n                "version": str(info.get("version") or ""),\n                "factorio_version": str(info.get("factorio_version") or ""),\n                "author": info.get("author") or "",\n                "description": info.get("description") or "",\n                "enabled": enabled.get(name, True),\n                "file": path.name,\n                "path": str(path),\n                "kind": kind,\n                "has_settings": has_settings,\n                "dependencies": dependencies,\n            })\n\n        items.sort(key=lambda x: (x["title"].lower(), version_obj(x["version"] or "0")), reverse=False)\n        with self._cache_lock:\n            self._installed_cache_signature = signature\n            self._installed_cache_items = copy.deepcopy(items)\n        return copy.deepcopy(items)\n'''
replace_once(manager, old_list, new_list)

old_portal = '''    def portal_mod(self, name: str) -> dict[str, Any]:\n        name = parse_mod_name(name)\n        response = self.session.get(f"{API_BASE}/{name}/full", timeout=20)\n\n        if response.status_code == 404:\n            raise ManagerError(f"Mod '{name}' tidak ditemukan di Mod Portal.")\n\n        try:\n            response.raise_for_status()\n        except requests.RequestException as exc:\n            raise ManagerError(f"Factorio Mod Portal error: {exc}") from exc\n\n        data = response.json()\n        if not isinstance(data, dict):\n            raise ManagerError("Respons Mod Portal tidak valid.")\n        return data\n'''

new_portal = '''    def portal_mod(self, name: str) -> dict[str, Any]:\n        name = parse_mod_name(name)\n        now = time.monotonic()\n        with self._cache_lock:\n            cached = self._portal_mod_cache.get(name)\n            if cached and now - cached[0] <= self._portal_cache_ttl:\n                return copy.deepcopy(cached[1])\n\n        response = self.session.get(f"{API_BASE}/{name}/full", timeout=20)\n\n        if response.status_code == 404:\n            raise ManagerError(f"Mod '{name}' tidak ditemukan di Mod Portal.")\n\n        try:\n            response.raise_for_status()\n        except requests.RequestException as exc:\n            raise ManagerError(f"Factorio Mod Portal error: {exc}") from exc\n\n        data = response.json()\n        if not isinstance(data, dict):\n            raise ManagerError("Respons Mod Portal tidak valid.")\n\n        with self._cache_lock:\n            self._portal_mod_cache[name] = (now, copy.deepcopy(data))\n            if len(self._portal_mod_cache) > 256:\n                oldest = min(self._portal_mod_cache.items(), key=lambda item: item[1][0])[0]\n                self._portal_mod_cache.pop(oldest, None)\n        return copy.deepcopy(data)\n'''
replace_once(manager, old_portal, new_portal)

# Add a one-scan dashboard state before diagnostics().
dashboard_method = '''    def dashboard_state(self) -> dict[str, Any]:\n        """Build Installed-tab state from a single mod scan."""\n        installed = self.list_installed()\n        index: dict[str, dict[str, Any]] = {}\n        groups: dict[str, list[dict[str, Any]]] = {}\n        for item in installed:\n            groups.setdefault(item["name"], []).append(item)\n            current = index.get(item["name"])\n            if current is None or version_obj(item["version"] or "0") > version_obj(current["version"] or "0"):\n                index[item["name"]] = item\n\n        missing: list[dict[str, Any]] = []\n        wrong_version: list[dict[str, Any]] = []\n        incompatible: list[dict[str, Any]] = []\n        for name, item in index.items():\n            if not item.get("enabled"):\n                continue\n            for raw_dep in item.get("dependencies", []):\n                dep = Dependency(**raw_dep)\n                if dep.name in BUILTIN_MODS:\n                    continue\n                target = index.get(dep.name)\n                if dep.kind == "required":\n                    if not target or not target.get("enabled"):\n                        missing.append({"mod": name, "dependency": dep.name, "requirement": dep.raw})\n                    elif not satisfies(target["version"], dep.operator, dep.version):\n                        wrong_version.append({\n                            "mod": name,\n                            "dependency": dep.name,\n                            "installed": target["version"],\n                            "requirement": dep.raw,\n                        })\n                elif dep.kind == "incompatible" and target and target.get("enabled"):\n                    incompatible.append({"mod": name, "dependency": dep.name, "requirement": dep.raw})\n\n        duplicates = []\n        for name, items in groups.items():\n            if len(items) > 1:\n                ordered = sorted(items, key=lambda x: version_obj(x["version"] or "0"), reverse=True)\n                duplicates.append({"name": name, "keep": ordered[0], "extras": ordered[1:]})\n\n        valid_paths = {str(Path(item["path"]).resolve()) for item in installed}\n        invalid_files = []\n        for path in sorted(self.mods_dir.iterdir(), key=lambda p: p.name.lower()):\n            if path.name.startswith(".") or path.name in {"mod-list.json", "mod-list.json.bak", "mod-settings.dat"}:\n                continue\n            if path.is_file() and path.suffix.lower() == ".zip" and str(path.resolve()) not in valid_paths:\n                invalid_files.append({"file": path.name, "reason": "ZIP rusak atau info.json tidak valid"})\n            elif path.is_dir() and (path / "info.json").exists() and str(path.resolve()) not in valid_paths:\n                invalid_files.append({"file": path.name, "reason": "info.json tidak valid"})\n\n        return {\n            "mods": installed,\n            "issues": {\n                "missing": missing,\n                "wrong_version": wrong_version,\n                "incompatible": incompatible,\n            },\n            "duplicates": duplicates,\n            "invalid_files": invalid_files,\n        }\n\n'''
replace_once(manager, "    def diagnostics(self) -> dict[str, Any]:\n", dashboard_method + "    def diagnostics(self) -> dict[str, Any]:\n")

old_diag = '''    def diagnostics(self) -> dict[str, Any]:\n        installed = self.list_installed()\n        issues = self.dependency_issues()\n        duplicates = self.duplicate_mods()\n        invalid = self.invalid_mod_files()\n        return {\n            "mods_dir": str(self.mods_dir),\n            "mods_dir_exists": self.mods_dir.exists(),\n            "mod_list_exists": self.mod_list_path.exists(),\n            "installed_count": len(installed),\n            "enabled_count": sum(1 for x in installed if x["enabled"]),\n            "dependency_issue_count": sum(len(v) for v in issues.values()),\n            "duplicates": duplicates,\n            "invalid_files": invalid,\n        }\n'''
new_diag = '''    def diagnostics(self) -> dict[str, Any]:\n        state = self.dashboard_state()\n        installed = state["mods"]\n        issues = state["issues"]\n        return {\n            "mods_dir": str(self.mods_dir),\n            "mods_dir_exists": self.mods_dir.exists(),\n            "mod_list_exists": self.mod_list_path.exists(),\n            "installed_count": len(installed),\n            "enabled_count": sum(1 for x in installed if x["enabled"]),\n            "dependency_issue_count": sum(len(v) for v in issues.values()),\n            "duplicates": state["duplicates"],\n            "invalid_files": state["invalid_files"],\n        }\n'''
replace_once(manager, old_diag, new_diag)

# ---------------------------------------------------------------------------
# Flask Installed endpoint now uses one scan too.
# ---------------------------------------------------------------------------
app = ROOT / "app.py"
replace_once(
    app,
    '''@app.get("/api/installed")\ndef installed():\n    try:\n        return ok(\n            mods=manager.list_installed(),\n            issues=manager.dependency_issues(),\n        )\n    except ManagerError as exc:\n        return fail(exc)\n''',
    '''@app.get("/api/installed")\ndef installed():\n    try:\n        state = manager.dashboard_state()\n        return ok(\n            mods=state["mods"],\n            issues=state["issues"],\n            duplicates=state["duplicates"],\n            invalid_files=state["invalid_files"],\n        )\n    except ManagerError as exc:\n        return fail(exc)\n''',
)

# ---------------------------------------------------------------------------
# Flet: midnight-blue design + single-scan Installed screen.
# ---------------------------------------------------------------------------
flet = ROOT / "flet_app.py"
replace_once(
    flet,
    '''        page.theme_mode = ft.ThemeMode.DARK\n        page.padding = 0\n        page.bgcolor = "#0e0d0c"\n''',
    '''        page.theme_mode = ft.ThemeMode.DARK\n        page.theme = ft.Theme(color_scheme_seed="#4EA1FF")\n        page.padding = 0\n        page.bgcolor = "#070B14"\n''',
)
replace_once(
    flet,
    '''    async def render_installed(self):\n        self.installed = await self.run_bg(manager.list_installed)\n        self.issues = await self.run_bg(manager.dependency_issues)\n        diag = await self.run_bg(manager.diagnostics)\n        issue_count = sum(len(v) for v in self.issues.values())\n''',
    '''    async def render_installed(self):\n        dashboard = await self.run_bg(manager.dashboard_state)\n        self.installed = dashboard["mods"]\n        self.issues = dashboard["issues"]\n        diag = {"duplicates": dashboard["duplicates"], "invalid_files": dashboard["invalid_files"]}\n        issue_count = sum(len(v) for v in self.issues.values())\n''',
)

flet_colors = {
    "#0e0d0c": "#070B14",
    "#151310": "#09111E",
    "#39332b": "#1C314A",
    "#191714": "#0D1726",
    "#2a241d": "#10243A",
    "#e48c30": "#4EA1FF",
    "#a69d93": "#8FA6BF",
    "#70685f": "#5F748C",
    "#1d1b18": "#0C1624",
    "#77716b": "#6F849B",
    "#f2d29f": "#B9D8FF",
    "#2b2824": "#102033",
    "#24211e": "#0F1C2D",
    "#211e19": "#101C2D",
    "#d8d0c7": "#D7E7F8",
    "#171512": "#0A1422",
    "#49423a": "#233B55",
    "#a56d32": "#4EA1FF",
    "#875a2e": "#173A5E",
    "#302d29": "#101B2A",
    "#f5e5d3": "#E7F2FF",
    "#3a3733": "#13263C",
    "#493f34": "#24415F",
    "#373431": "#132238",
    "#4a4641": "#29445F",
    "#c9c2ba": "#BDD0E2",
    "#2d2b29": "#0F1B2B",
    "#49443e": "#223A54",
    "#211f1c": "#0D1828",
    "#403a33": "#203852",
    "#eee7df": "#EAF2FB",
    "#eee8df": "#EAF2FB",
    "#e6ded5": "#DCE9F6",
}
replace_all(flet, flet_colors)

# Give the desktop window a little more room for the wider blue UI.
replace_once(flet, "            page.window.width = 1180\n            page.window.height = 760\n", "            page.window.width = 1240\n            page.window.height = 800\n")

# ---------------------------------------------------------------------------
# Flask/Web CSS: blue-black visual system.
# ---------------------------------------------------------------------------
css = ROOT / "static" / "style.css"
css_colors = {
    "--bg: #0e0d0c;": "--bg: #070B14;",
    "--sidebar: #151310;": "--sidebar: #08111F;",
    "--panel: #191714;": "--panel: #0D1726;",
    "--panel2: #211e19;": "--panel2: #111E30;",
    "--border: #39332b;": "--border: #1B314A;",
    "--text: #f2ede7;": "--text: #EAF2FB;",
    "--muted: #a69d93;": "--muted: #8EA4BA;",
    "--accent: #e48c30;": "--accent: #4EA1FF;",
    "--accent2: #ffab51;": "--accent2: #79B9FF;",
    "--danger: #d95c58;": "--danger: #E66B72;",
    "--good: #8fbf75;": "--good: #68C587;",
    "--warn: #d4a94c;": "--warn: #E1B65A;",
    "#2d2319": "#102943",
    "#17100a": "#04111F",
    "#0f0e0c": "#080F1A",
    "rgba(21, 19, 16, .96)": "rgba(8, 17, 31, .98)",
    "#2a241d": "#10243A",
    "#786f66": "#5E7389",
    "#39342e": "#1A2B3D",
    "#b5aca2": "#9FB2C5",
    "#e9e3db": "#EFF7FF",
    "#5a4b3c": "#31577A",
    "#d4a56f": "#78B7F1",
    "#25211c": "#102033",
    "#c9beb2": "#B4C7DA",
    "#12110f": "#08111D",
    "#1d1b18": "#0D1726",
    "#171512": "#0B1421",
    "#4a433a": "#29415C",
    "#27231f": "#132238",
    "#d8d0c7": "#D7E5F3",
    "#211e19": "#101C2D",
    "#c8c0b7": "#B6C7D7",
    "#151412": "#0A1422",
}
replace_all(css, css_colors)

with css.open("a", encoding="utf-8") as handle:
    handle.write('''\n\n/* v2.5.0 Midnight Blue polish */\n.sidebar {\n    background: linear-gradient(180deg, #08111f 0%, #070d17 100%);\n    box-shadow: 14px 0 40px rgba(0, 0, 0, .20);\n}\n.nav-item {\n    border: 1px solid transparent;\n    transition: background .14s ease, border-color .14s ease, color .14s ease;\n}\n.nav-item:hover {\n    background: #0f1d2e;\n    border-color: #19314a;\n}\n.nav-item.active {\n    background: linear-gradient(90deg, #132b45 0%, #0e1d2f 100%);\n    border-color: #24496c;\n    box-shadow: inset 3px 0 #4ea1ff;\n}\n.stat, .panel, .detail-card, .mini-card, .mod-row {\n    box-shadow: 0 10px 28px rgba(0, 0, 0, .12);\n}\n.mod-row:hover, .mini-card:hover {\n    border-color: #315779;\n}\ninput:focus, select:focus {\n    box-shadow: 0 0 0 3px rgba(78, 161, 255, .10);\n}\n''')

# Version bump.
replace_once(ROOT / "pyproject.toml", 'version = "2.4.2"', 'version = "2.5.0"')

# Regression/performance checks.
(ROOT / "tests" / "test_v250_optimization.py").write_text('''from pathlib import Path\nimport sys\nimport tempfile\nimport zipfile\nimport json\n\nROOT = Path(__file__).resolve().parents[1]\nsys.path.insert(0, str(ROOT))\n\nfrom manager import FactorioModManager\n\n\ndef make_mod(path: Path):\n    info = {\n        "name": "cache-test",\n        "title": "Cache Test",\n        "version": "1.0.0",\n        "factorio_version": "2.0",\n        "dependencies": ["base >= 2.0"],\n    }\n    with zipfile.ZipFile(path, "w") as archive:\n        archive.writestr("cache-test_1.0.0/info.json", json.dumps(info))\n        archive.writestr("cache-test_1.0.0/settings.lua", "data:extend({})")\n\n\ndef main():\n    with tempfile.TemporaryDirectory() as tmp:\n        base = Path(tmp)\n        mods = base / "mods"\n        mods.mkdir()\n        make_mod(mods / "cache-test_1.0.0.zip")\n        cfg = base / "config.json"\n        cfg.write_text(json.dumps({"mods_dir": str(mods), "factorio_version": "2.0"}), encoding="utf-8")\n        manager = FactorioModManager(cfg, project_root=ROOT)\n\n        first = manager.list_installed()\n        second = manager.list_installed()\n        assert first == second\n        assert first[0]["has_settings"] is True\n        assert manager._installed_cache_signature is not None\n\n        state = manager.dashboard_state()\n        assert state["mods"][0]["name"] == "cache-test"\n        assert not state["issues"]["missing"]\n        assert not state["duplicates"]\n\n    flet = (ROOT / "flet_app.py").read_text(encoding="utf-8")\n    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")\n    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")\n    assert "#070B14" in flet\n    assert "#09111E" in flet\n    assert "#4EA1FF" in flet\n    assert "--sidebar: #08111F" in css\n    assert "#4ea1ff" in css.lower()\n    assert 'version = "2.5.0"' in project\n    print("v2.5.0 optimization/theme tests: PASS")\n\n\nif __name__ == "__main__":\n    main()\n''', encoding="utf-8")

print("Applied v2.5.0 optimization + Midnight Blue UI patch")
