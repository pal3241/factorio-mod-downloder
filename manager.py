from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
import hashlib
import uuid
import webbrowser

import requests
from packaging.version import InvalidVersion, Version
from factorio_settings import (
    SETTINGS_STAGE_FILES,
    SettingsCodecError,
    coerce_setting_value,
    infer_prototype_type,
    read_mod_settings,
    read_settings_stage_sources,
    scan_setting_prototypes,
    set_document_setting,
    setting_name_likely_belongs_to_mod,
    settings_values,
    write_mod_settings,
)


MOD_PORTAL = "https://mods.factorio.com"
API_BASE = f"{MOD_PORTAL}/api/mods"
MIRROR_BASE = "https://mods-storage.re146.dev"

BUILTIN_MODS = {
    "base",
    "core",
    "quality",
    "space-age",
    "elevated-rails",
}

MOD_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")
DEPENDENCY_RE = re.compile(
    r"^([A-Za-z0-9_.\-]+)"
    r"(?:\s*(>=|<=|=|>|<)\s*([A-Za-z0-9_.+\-]+))?$"
)


PORTAL_CATEGORIES = [
    {"id": "content", "label": "Content"},
    {"id": "overhaul", "label": "Overhaul"},
    {"id": "tweaks", "label": "Tweaks"},
    {"id": "utilities", "label": "Utilities"},
    {"id": "scenarios", "label": "Scenarios"},
    {"id": "mod-packs", "label": "Mod packs"},
    {"id": "localizations", "label": "Localizations"},
    {"id": "internal", "label": "Internal"},
    {"id": "no-category", "label": "No category"},
]

PORTAL_TAGS = [
    {"id": "planets", "label": "Planets"},
    {"id": "transportation", "label": "Transportation"},
    {"id": "logistics", "label": "Logistics"},
    {"id": "trains", "label": "Trains"},
    {"id": "combat", "label": "Combat"},
    {"id": "armor", "label": "Armor"},
    {"id": "character", "label": "Character"},
    {"id": "enemies", "label": "Enemies"},
    {"id": "environment", "label": "Environment"},
    {"id": "mining", "label": "Mining"},
    {"id": "fluids", "label": "Fluids"},
    {"id": "logistic-network", "label": "Logistic network"},
    {"id": "circuit-network", "label": "Circuit network"},
    {"id": "manufacturing", "label": "Manufacturing"},
    {"id": "power", "label": "Power"},
    {"id": "storage", "label": "Storage"},
    {"id": "blueprints", "label": "Blueprints"},
    {"id": "cheats", "label": "Cheats"},
]

PORTAL_SORT_MODES = [
    {"id": "highlighted", "label": "Highlighted mods"},
    {"id": "last_updated_at", "label": "Recently updated"},
    {"id": "most_downloads", "label": "Most downloaded"},
    {"id": "trending", "label": "Trending"},
    {"id": "relevancy", "label": "Search mods"},
]


class ManagerError(RuntimeError):
    pass


@dataclass(frozen=True)
class Dependency:
    name: str
    kind: str
    operator: str | None = None
    version: str | None = None
    raw: str = ""


@dataclass(frozen=True)
class Release:
    mod_name: str
    version: str
    file_name: str
    factorio_version: str
    sha1: str
    dependencies: tuple[Dependency, ...]
    released_at: str = ""


def version_obj(value: str) -> Version:
    try:
        return Version(str(value))
    except InvalidVersion:
        # Factorio mod versions are normally numeric/semver-like.
        # Keep a deterministic fallback for unusual versions.
        cleaned = re.sub(r"[^0-9.]", ".", str(value))
        cleaned = re.sub(r"\.+", ".", cleaned).strip(".") or "0"
        return Version(cleaned)


def factorio_branch(version: str) -> str:
    parts = str(version).strip().split(".")
    if len(parts) >= 2:
        return ".".join(parts[:2])
    return str(version).strip()


def default_mods_dir() -> Path:
    system = platform.system().lower()

    if system == "windows":
        appdata = os.getenv("APPDATA")
        if appdata:
            return Path(appdata) / "Factorio" / "mods"

    if system == "darwin":
        return Path.home() / "Library" / "Application Support" / "factorio" / "mods"

    return Path.home() / ".factorio" / "mods"


def parse_mod_name(value: str) -> str:
    value = (value or "").strip()
    if not value:
        raise ManagerError("Masukkan URL atau ID mod.")

    if value.startswith(("http://", "https://")):
        parsed = urlparse(value)
        if parsed.netloc not in {"mods.factorio.com", "www.mods.factorio.com"}:
            raise ManagerError("URL harus berasal dari mods.factorio.com.")
        match = re.match(r"^/mod/([^/?#]+)", parsed.path)
        if not match:
            raise ManagerError("URL Mod Portal tidak valid.")
        value = match.group(1)

    if not MOD_ID_RE.fullmatch(value):
        raise ManagerError("ID mod tidak valid.")

    return value


def parse_dependency(value: str) -> Dependency:
    raw = (value or "").strip()
    body = raw
    kind = "required"

    if body.startswith("(?)"):
        kind = "optional"
        body = body[3:].strip()
    elif body.startswith("?"):
        kind = "optional"
        body = body[1:].strip()
    elif body.startswith("!"):
        kind = "incompatible"
        body = body[1:].strip()
    elif body.startswith("~"):
        # Required dependency with relaxed load-order relation.
        kind = "required"
        body = body[1:].strip()

    match = DEPENDENCY_RE.match(body)
    if not match:
        # Fall back to the first token to keep malformed metadata visible.
        name = body.split()[0] if body else ""
        return Dependency(name=name, kind=kind, raw=raw)

    return Dependency(
        name=match.group(1),
        kind=kind,
        operator=match.group(2),
        version=match.group(3),
        raw=raw,
    )


def satisfies(version: str, operator: str | None, required: str | None) -> bool:
    if not operator or not required:
        return True

    left = version_obj(version)
    right = version_obj(required)

    return {
        "=": left == right,
        ">=": left >= right,
        "<=": left <= right,
        ">": left > right,
        "<": left < right,
    }[operator]


class FactorioModManager:
    def __init__(self, config_path: Path, project_root: Path | None = None):
        self.config_path = config_path
        self.project_root = Path(project_root).resolve() if project_root else Path(__file__).resolve().parent
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Factorio-Local-Mod-Manager/1.0"
        })

        self.config = self._load_config()
        self.mods_dir.mkdir(parents=True, exist_ok=True)

    def _load_config(self) -> dict[str, Any]:
        defaults = {
            "mods_dir": str(default_mods_dir()),
            "factorio_version": "2.0",
            "install_dependencies": True,
            "factorio_executable": "",
            "launch_args": "",
        }

        if not self.config_path.exists():
            return defaults

        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return defaults
            defaults.update(data)
        except (OSError, json.JSONDecodeError):
            pass

        return defaults

    def save_config(self, updates: dict[str, Any]) -> dict[str, Any]:
        if "mods_dir" in updates:
            candidate = Path(str(updates["mods_dir"])).expanduser()
            if not candidate.is_absolute():
                raise ManagerError("Folder mods harus berupa absolute path.")
            candidate.mkdir(parents=True, exist_ok=True)
            updates["mods_dir"] = str(candidate.resolve())

        if "factorio_version" in updates:
            value = str(updates["factorio_version"]).strip()
            if not re.fullmatch(r"\d+(?:\.\d+){1,2}", value):
                raise ManagerError("Versi Factorio tidak valid. Contoh: 2.0 atau 2.0.72.")
            updates["factorio_version"] = value

        if "install_dependencies" in updates:
            updates["install_dependencies"] = bool(updates["install_dependencies"])

        if "factorio_executable" in updates:
            updates["factorio_executable"] = str(updates["factorio_executable"]).strip()

        if "launch_args" in updates:
            updates["launch_args"] = str(updates["launch_args"]).strip()

        self.config.update(updates)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(self.config, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self.mods_dir.mkdir(parents=True, exist_ok=True)
        return dict(self.config)

    @property
    def mods_dir(self) -> Path:
        return Path(self.config["mods_dir"]).expanduser()

    @property
    def mod_list_path(self) -> Path:
        return self.mods_dir / "mod-list.json"

    def get_config(self) -> dict[str, Any]:
        return {
            **self.config,
            "mods_dir_exists": self.mods_dir.exists(),
            "mod_list_path": str(self.mod_list_path),
        }

    def _read_mod_list(self) -> dict[str, Any]:
        if not self.mod_list_path.exists():
            return {"mods": [{"name": "base", "enabled": True}]}

        try:
            data = json.loads(self.mod_list_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ManagerError(f"mod-list.json tidak dapat dibaca: {exc}") from exc

        if not isinstance(data, dict):
            data = {}
        if not isinstance(data.get("mods"), list):
            data["mods"] = []

        return data

    def _write_mod_list(self, data: dict[str, Any]) -> None:
        self.mods_dir.mkdir(parents=True, exist_ok=True)

        if self.mod_list_path.exists():
            backup = self.mod_list_path.with_suffix(".json.bak")
            try:
                shutil.copy2(self.mod_list_path, backup)
            except OSError:
                pass

        temp = self.mod_list_path.with_suffix(".json.tmp")
        temp.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temp.replace(self.mod_list_path)

    def _enabled_map(self) -> dict[str, bool]:
        data = self._read_mod_list()
        result: dict[str, bool] = {}
        for item in data["mods"]:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                result[item["name"]] = bool(item.get("enabled", True))
        return result

    def _set_mod_enabled_in_data(self, data: dict[str, Any], name: str, enabled: bool) -> None:
        for item in data["mods"]:
            if isinstance(item, dict) and item.get("name") == name:
                item["enabled"] = bool(enabled)
                return

        data["mods"].append({"name": name, "enabled": bool(enabled)})

    def set_enabled(self, name: str, enabled: bool) -> None:
        name = parse_mod_name(name)
        data = self._read_mod_list()
        self._set_mod_enabled_in_data(data, name, enabled)
        self._write_mod_list(data)

    def _read_info_from_zip(self, path: Path) -> dict[str, Any] | None:
        try:
            with zipfile.ZipFile(path, "r") as archive:
                candidates = [
                    name for name in archive.namelist()
                    if name.endswith("/info.json") or name == "info.json"
                ]
                if not candidates:
                    return None
                candidates.sort(key=lambda x: (x.count("/"), len(x)))
                raw = archive.read(candidates[0]).decode("utf-8-sig")
                info = json.loads(raw)
                return info if isinstance(info, dict) else None
        except (OSError, zipfile.BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError):
            return None

    def _read_info_from_dir(self, path: Path) -> dict[str, Any] | None:
        info_path = path / "info.json"
        if not info_path.exists():
            return None
        try:
            info = json.loads(info_path.read_text(encoding="utf-8-sig"))
            return info if isinstance(info, dict) else None
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return None

    def _mod_has_settings(self, path: Path, kind: str) -> bool:
        # Factorio has three settings-stage files, not only settings.lua.
        return bool(read_settings_stage_sources(path, kind))

    def list_installed(self) -> list[dict[str, Any]]:
        self.mods_dir.mkdir(parents=True, exist_ok=True)
        enabled = self._enabled_map()
        items: list[dict[str, Any]] = []

        for path in sorted(self.mods_dir.iterdir(), key=lambda p: p.name.lower()):
            if path.name.startswith(".") or path.name in {"mod-list.json", "mod-list.json.bak"}:
                continue

            info = None
            kind = None

            if path.is_file() and path.suffix.lower() == ".zip":
                info = self._read_info_from_zip(path)
                kind = "zip"
            elif path.is_dir():
                info = self._read_info_from_dir(path)
                kind = "folder"

            if not info or not isinstance(info.get("name"), str):
                continue

            name = info["name"]
            dependencies = [
                parse_dependency(dep).__dict__
                for dep in (info.get("dependencies") or [])
                if isinstance(dep, str)
            ]

            items.append({
                "name": name,
                "title": info.get("title") or name,
                "version": str(info.get("version") or ""),
                "factorio_version": str(info.get("factorio_version") or ""),
                "author": info.get("author") or "",
                "description": info.get("description") or "",
                "enabled": enabled.get(name, True),
                "file": path.name,
                "path": str(path),
                "kind": kind,
                "has_settings": self._mod_has_settings(path, kind),
                "dependencies": dependencies,
            })

        items.sort(key=lambda x: (x["title"].lower(), version_obj(x["version"] or "0")), reverse=False)
        return items

    def installed_index(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for item in self.list_installed():
            current = result.get(item["name"])
            if current is None or version_obj(item["version"] or "0") > version_obj(current["version"] or "0"):
                result[item["name"]] = item
        return result

    def portal_mod(self, name: str) -> dict[str, Any]:
        name = parse_mod_name(name)
        response = self.session.get(f"{API_BASE}/{name}/full", timeout=20)

        if response.status_code == 404:
            raise ManagerError(f"Mod '{name}' tidak ditemukan di Mod Portal.")

        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ManagerError(f"Factorio Mod Portal error: {exc}") from exc

        data = response.json()
        if not isinstance(data, dict):
            raise ManagerError("Respons Mod Portal tidak valid.")
        return data


    def portal_search_meta(self) -> dict[str, Any]:
        return {
            "categories": PORTAL_CATEGORIES,
            "tags": PORTAL_TAGS,
            "sort_modes": PORTAL_SORT_MODES,
            "expansions": [{"id": "space-age", "label": "Space Age"}],
            "factorio_version": self.config["factorio_version"],
        }

    def _release_summary_for_names(self, names: list[str]) -> dict[str, dict[str, Any]]:
        """Fetch release metadata for a page of search results in one request."""
        if not names:
            return {}

        params: list[tuple[str, str]] = [
            ("hide_deprecated", "false"),
            ("page_size", "max"),
        ]
        params.extend(("namelist", name) for name in names)

        response = self.session.get(API_BASE, params=params, timeout=25)
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ManagerError(f"Gagal mengambil release metadata: {exc}") from exc

        data = response.json()
        results = data.get("results", []) if isinstance(data, dict) else []
        target_branch = factorio_branch(self.config["factorio_version"])
        output: dict[str, dict[str, Any]] = {}

        for mod in results:
            name = str(mod.get("name") or "")
            releases = mod.get("releases") or []
            branches = sorted(
                {
                    factorio_branch((release.get("info_json") or {}).get("factorio_version", ""))
                    for release in releases
                    if (release.get("info_json") or {}).get("factorio_version")
                },
                key=version_obj,
            )
            compatible = [
                release for release in releases
                if factorio_branch((release.get("info_json") or {}).get("factorio_version", "")) == target_branch
            ]
            latest = None
            if compatible:
                latest = max(compatible, key=lambda release: version_obj(str(release.get("version") or "0")))

            if len(branches) > 1:
                branch_display = f"{branches[0]} - {branches[-1]}"
            elif branches:
                branch_display = branches[0]
            else:
                branch_display = "?"

            output[name] = {
                "latest_version": str((latest or {}).get("version") or ""),
                "factorio_version_display": branch_display,
                "compatible": latest is not None,
            }

        return output

    def _decorate_search_results(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        names = [str(mod.get("name") or "") for mod in results if mod.get("name")]
        release_meta = self._release_summary_for_names(names)
        installed = self.installed_index()
        output = []

        for mod in results:
            name = str(mod.get("name") or "")
            thumbnail = mod.get("thumbnail")
            if thumbnail and str(thumbnail).startswith("/"):
                thumbnail = f"https://assets-mod.factorio.com{thumbnail}"

            rel = release_meta.get(name, {})
            local = installed.get(name)
            latest_version = rel.get("latest_version") or ""
            update_available = False
            if local and latest_version:
                try:
                    update_available = version_obj(latest_version) > version_obj(local.get("version") or "0")
                except Exception:
                    update_available = False

            output.append({
                "name": name,
                "title": mod.get("title") or name,
                "owner": mod.get("owner") or "",
                "summary": mod.get("summary") or "",
                "category": mod.get("category") or "no-category",
                "downloads_count": int(mod.get("downloads_count") or 0),
                "thumbnail": thumbnail,
                "tags": list(mod.get("tags") or []),
                "updated_at": mod.get("updated_at") or "",
                "created_at": mod.get("created_at") or "",
                "source_url": mod.get("source_url") or "",
                "deprecated": bool(mod.get("deprecated", False)),
                "requires_space_age": bool(mod.get("requires_space_age", False)),
                "latest_version": latest_version,
                "factorio_version_display": rel.get("factorio_version_display") or "?",
                "compatible": bool(rel.get("compatible", False)),
                "installed": local,
                "update_available": update_available,
            })

        return output

    def _public_mod_details(self, names: list[str]) -> list[dict[str, Any]]:
        # Fetch public full metadata for the visible page without credentials.
        unique: list[str] = []
        for raw_name in names:
            name = unquote(str(raw_name or "")).strip()
            if MOD_ID_RE.fullmatch(name) and name not in unique:
                unique.append(name)

        if not unique:
            return []

        by_name: dict[str, dict[str, Any]] = {}

        def fetch_one(name: str):
            return name, self.portal_mod(name)

        with ThreadPoolExecutor(max_workers=min(8, len(unique))) as executor:
            futures = [executor.submit(fetch_one, name) for name in unique]
            for future in as_completed(futures):
                try:
                    name, data = future.result()
                    by_name[name] = data
                except Exception:
                    # A deleted/private card should not fail the entire page.
                    continue

        ordered = [by_name[name] for name in unique if name in by_name]
        return self._decorate_search_results(ordered)

    @staticmethod
    def _mod_names_from_portal_html(html: str, limit: int = 20) -> list[str]:
        names: list[str] = []
        for raw_name in re.findall(r"/mod/([A-Za-z0-9_.\-]+)", html, flags=re.IGNORECASE):
            name = unquote(raw_name).strip()
            if MOD_ID_RE.fullmatch(name) and name not in names:
                names.append(name)
            if len(names) >= limit:
                break
        return names

    @staticmethod
    def _portal_html_pagination(html: str, page: int, page_size: int, result_count: int) -> dict[str, int]:
        count = 0
        found = re.search(r"Found\s+([0-9][0-9.,\s]*)\s+mods?", html, flags=re.IGNORECASE)
        if found:
            digits = re.sub(r"\D", "", found.group(1))
            if digits:
                count = int(digits)

        page_numbers = [int(value) for value in re.findall(r"[?&]page=(\d+)", html)]
        if count:
            page_count = max(1, (count + page_size - 1) // page_size)
        elif page_numbers:
            page_count = max(max(page_numbers), page)
        else:
            page_count = page

        if not count:
            count = result_count if page == 1 else max(result_count, (page - 1) * page_size + result_count)

        return {
            "count": count,
            "page": page,
            "page_count": page_count,
            "page_size": page_size,
        }

    def highlighted_mods(self, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 20))
        response = self.session.get(
            f"{MOD_PORTAL}/highlights",
            params={"page": page},
            headers={"Accept": "text/html,application/xhtml+xml"},
            timeout=25,
        )
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ManagerError(f"Gagal mengambil highlighted mods: {exc}") from exc

        names = self._mod_names_from_portal_html(response.text, page_size)
        results = self._public_mod_details(names)
        pagination = self._portal_html_pagination(response.text, page, page_size, len(results))
        return {
            "pagination": pagination,
            "results": results,
            "sort_attribute": "highlighted",
        }

    def search_mods(
        self,
        query: str = "",
        *,
        sort_attribute: str = "last_updated_at",
        page: int = 1,
        page_size: int = 20,
        categories: list[str] | None = None,
        exclude_categories: list[str] | None = None,
        tags: list[str] | None = None,
        exclude_tags: list[str] | None = None,
        expansions: list[str] | None = None,
        exclude_expansions: list[str] | None = None,
        show_deprecated: bool = False,
    ) -> dict[str, Any]:
        # POST /api/search requires Factorio credentials. This manager is
        # intentionally tokenless, so use public website routes to get ordered
        # mod IDs and public /api/mods/<name>/full for metadata.
        allowed_sorts = {item["id"] for item in PORTAL_SORT_MODES}
        if sort_attribute not in allowed_sorts:
            raise ManagerError("Sort mode tidak valid.")

        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 20))
        query = str(query or "").strip()

        if sort_attribute == "highlighted" and not query:
            return self.highlighted_mods(page=page, page_size=page_size)
        if sort_attribute == "highlighted":
            sort_attribute = "relevancy"

        category_ids = {item["id"] for item in PORTAL_CATEGORIES}
        tag_ids = {item["id"] for item in PORTAL_TAGS}
        expansion_ids = {"space-age"}

        def clean(values, allowed):
            return [value for value in (values or []) if value in allowed]

        if query or sort_attribute == "relevancy":
            endpoint = f"{MOD_PORTAL}/search"
        else:
            endpoint = {
                "last_updated_at": f"{MOD_PORTAL}/browse/updated",
                "most_downloads": f"{MOD_PORTAL}/browse/downloaded",
                "trending": f"{MOD_PORTAL}/browse/trending",
            }.get(sort_attribute, f"{MOD_PORTAL}/search")

        params: list[tuple[str, str]] = [
            ("factorio_version", factorio_branch(self.config["factorio_version"])),
            ("sort_attribute", sort_attribute),
            ("page", str(page)),
        ]
        if query:
            params.append(("query", query))
        if show_deprecated:
            params.append(("show_deprecated", "true"))

        for value in clean(categories, category_ids):
            params.append(("category", value))
        for value in clean(exclude_categories, category_ids):
            params.append(("exclude_category", value))
        for value in clean(tags, tag_ids):
            params.append(("tag", value))
        for value in clean(exclude_tags, tag_ids):
            params.append(("exclude_tag", value))
        for value in clean(expansions, expansion_ids):
            params.append(("expansion", value))
        for value in clean(exclude_expansions, expansion_ids):
            params.append(("exclude_expansion", value))

        response = self.session.get(
            endpoint,
            params=params,
            headers={"Accept": "text/html,application/xhtml+xml"},
            timeout=30,
        )
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ManagerError(f"Factorio Mod Portal public search error: {exc}") from exc

        names = self._mod_names_from_portal_html(response.text, page_size)
        results = self._public_mod_details(names)
        pagination = self._portal_html_pagination(response.text, page, page_size, len(results))
        return {
            "pagination": pagination,
            "results": results,
            "sort_attribute": sort_attribute,
        }

    def recent_mods(self, limit: int = 24) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 50))
        response = self.session.get(
            API_BASE,
            params={
                "page": 1,
                "page_size": limit,
                "sort": "updated_at",
                "sort_order": "desc",
                "hide_deprecated": "true",
                "version": self.config["factorio_version"],
            },
            timeout=25,
        )
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ManagerError(f"Gagal mengambil daftar mod: {exc}") from exc

        data = response.json()
        results = data.get("results", []) if isinstance(data, dict) else []
        output = []
        for mod in results:
            latest = mod.get("latest_release") or {}
            output.append({
                "name": mod.get("name"),
                "title": mod.get("title"),
                "owner": mod.get("owner"),
                "summary": mod.get("summary"),
                "downloads_count": mod.get("downloads_count"),
                "latest_version": latest.get("version"),
                "factorio_version": (latest.get("info_json") or {}).get("factorio_version"),
            })
        return output

    def portal_view(self, name_or_url: str) -> dict[str, Any]:
        name = parse_mod_name(name_or_url)
        data = self.portal_mod(name)
        releases = []

        for raw in reversed(data.get("releases", [])):
            info = raw.get("info_json") or {}
            deps = [
                parse_dependency(dep).__dict__
                for dep in (info.get("dependencies") or [])
                if isinstance(dep, str)
            ]

            releases.append({
                "version": raw.get("version"),
                "file_name": raw.get("file_name"),
                "factorio_version": info.get("factorio_version"),
                "released_at": raw.get("released_at"),
                "sha1": raw.get("sha1"),
                "dependencies": deps,
            })

        thumbnail = data.get("thumbnail")
        if thumbnail:
            thumbnail = f"https://assets-mod.factorio.com{thumbnail}"

        installed = self.installed_index().get(name)

        return {
            "name": name,
            "title": data.get("title") or name,
            "owner": data.get("owner") or "",
            "summary": data.get("summary") or "",
            "category": data.get("category") or "",
            "downloads_count": data.get("downloads_count") or 0,
            "deprecated": bool(data.get("deprecated", False)),
            "thumbnail": thumbnail,
            "releases": releases,
            "installed": installed,
        }

    def _raw_to_release(self, mod_name: str, raw: dict[str, Any]) -> Release:
        info = raw.get("info_json") or {}
        deps = tuple(
            parse_dependency(dep)
            for dep in (info.get("dependencies") or [])
            if isinstance(dep, str)
        )

        return Release(
            mod_name=mod_name,
            version=str(raw.get("version") or ""),
            file_name=str(raw.get("file_name") or f"{mod_name}_{raw.get('version')}.zip"),
            factorio_version=str(info.get("factorio_version") or ""),
            sha1=str(raw.get("sha1") or "").lower(),
            dependencies=deps,
            released_at=str(raw.get("released_at") or ""),
        )

    def _select_release(
        self,
        mod_name: str,
        *,
        requested_version: str | None = None,
        operator: str | None = None,
        required_version: str | None = None,
    ) -> Release:
        data = self.portal_mod(mod_name)
        target_branch = factorio_branch(self.config["factorio_version"])
        candidates: list[Release] = []

        for raw in data.get("releases", []):
            release = self._raw_to_release(mod_name, raw)
            if factorio_branch(release.factorio_version) != target_branch:
                continue
            if requested_version and release.version != requested_version:
                continue
            if not satisfies(release.version, operator, required_version):
                continue
            candidates.append(release)

        if not candidates:
            constraint = ""
            if requested_version:
                constraint = f" versi {requested_version}"
            elif operator and required_version:
                constraint = f" {operator} {required_version}"
            raise ManagerError(
                f"Tidak ada release kompatibel untuk {mod_name}{constraint} "
                f"pada Factorio {target_branch}."
            )

        return max(candidates, key=lambda r: version_obj(r.version))

    def _resolve_plan(
        self,
        root_name: str,
        requested_version: str | None,
        include_dependencies: bool,
    ) -> dict[str, Release]:
        plan: dict[str, Release] = {}
        visiting: set[str] = set()

        def visit(
            name: str,
            version: str | None = None,
            operator: str | None = None,
            required_version: str | None = None,
        ) -> None:
            if name in BUILTIN_MODS:
                return

            existing = plan.get(name)
            if existing:
                if not satisfies(existing.version, operator, required_version):
                    raise ManagerError(
                        f"Konflik dependency untuk {name}: "
                        f"{existing.version} tidak memenuhi {operator or ''} {required_version or ''}."
                    )
                return

            if name in visiting:
                return

            visiting.add(name)
            release = self._select_release(
                name,
                requested_version=version,
                operator=operator,
                required_version=required_version,
            )
            plan[name] = release

            if include_dependencies:
                for dep in release.dependencies:
                    if dep.kind != "required" or dep.name in BUILTIN_MODS:
                        continue
                    visit(
                        dep.name,
                        operator=dep.operator,
                        required_version=dep.version,
                    )

            visiting.remove(name)

        visit(root_name, version=requested_version)
        return plan

    def _mirror_url(self, release: Release) -> str:
        return (
            f"{MIRROR_BASE}/{release.mod_name}/{release.version}.zip"
            f"?anticache={uuid.uuid4().hex}"
        )

    def _download_release(self, release: Release, target: Path) -> None:
        response = self.session.get(
            self._mirror_url(release),
            stream=True,
            timeout=(15, 45),
        )

        if response.status_code == 404:
            response.close()
            raise ManagerError(
                f"{release.mod_name} {release.version} belum tersedia di mirror re146."
            )

        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            response.close()
            raise ManagerError(
                f"Gagal download {release.mod_name} {release.version}: {exc}"
            ) from exc

        sha1 = hashlib.sha1()
        total = 0

        try:
            with target.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=256 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > 2 * 1024 * 1024 * 1024:
                        raise ManagerError("Ukuran mod melewati batas 2 GiB.")
                    handle.write(chunk)
                    sha1.update(chunk)
        finally:
            response.close()

        if total == 0:
            target.unlink(missing_ok=True)
            raise ManagerError(f"File {release.mod_name} kosong.")

        if release.sha1:
            actual = sha1.hexdigest().lower()
            if actual != release.sha1:
                target.unlink(missing_ok=True)
                raise ManagerError(
                    f"Checksum {release.mod_name} {release.version} tidak cocok."
                )

        # Ensure the mirror really supplied a Factorio mod ZIP.
        info = self._read_info_from_zip(target)
        if not info or info.get("name") != release.mod_name:
            target.unlink(missing_ok=True)
            raise ManagerError(
                f"ZIP {release.mod_name} {release.version} tidak valid."
            )

    def _matching_entries(self, mod_name: str) -> list[Path]:
        result: list[Path] = []
        for item in self.list_installed():
            if item["name"] == mod_name:
                result.append(Path(item["path"]))
        return result

    def install(
        self,
        name_or_url: str,
        version: str | None = None,
        include_dependencies: bool | None = None,
        enable: bool = True,
    ) -> dict[str, Any]:
        root_name = parse_mod_name(name_or_url)
        if include_dependencies is None:
            include_dependencies = bool(self.config.get("install_dependencies", True))

        plan = self._resolve_plan(root_name, version, include_dependencies)
        installed_before = self.installed_index()

        # Skip exact installed versions.
        needed = {
            name: release
            for name, release in plan.items()
            if name not in installed_before
            or installed_before[name]["version"] != release.version
        }

        if not needed:
            if enable:
                self.set_enabled(root_name, True)
            return {
                "installed": [],
                "already_current": sorted(plan),
                "root": root_name,
            }

        self.mods_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="factorio_mod_manager_") as tmp:
            staging = Path(tmp)

            # Download every file first. Nothing in Factorio folder changes until all verify.
            for release in needed.values():
                target = staging / release.file_name
                self._download_release(release, target)

            # Commit verified ZIPs.
            committed = []
            for name, release in needed.items():
                destination = self.mods_dir / release.file_name

                # Remove older copies only after verified replacement is available.
                for old in self._matching_entries(name):
                    if old.resolve() == destination.resolve():
                        continue
                    if old.is_dir():
                        shutil.rmtree(old)
                    else:
                        old.unlink(missing_ok=True)

                shutil.move(str(staging / release.file_name), str(destination))
                committed.append({
                    "name": name,
                    "version": release.version,
                    "file": release.file_name,
                })

        data = self._read_mod_list()
        for name in plan:
            previous_enabled = self._enabled_map().get(name, True)
            desired = True if name == root_name and enable else previous_enabled
            # Required newly-installed dependencies should be enabled.
            if name != root_name and name not in installed_before:
                desired = True
            self._set_mod_enabled_in_data(data, name, desired)

        self._write_mod_list(data)

        return {
            "installed": committed,
            "already_current": sorted(set(plan) - set(needed)),
            "root": root_name,
        }

    def update_one(self, name: str) -> dict[str, Any]:
        name = parse_mod_name(name)
        installed = self.installed_index().get(name)
        if not installed:
            raise ManagerError(f"{name} belum terpasang.")

        release = self._select_release(name)
        if version_obj(release.version) <= version_obj(installed["version"]):
            return {
                "name": name,
                "updated": False,
                "current": installed["version"],
                "latest": release.version,
            }

        enabled = bool(installed["enabled"])
        result = self.install(
            name,
            version=release.version,
            include_dependencies=True,
            enable=enabled,
        )

        return {
            "name": name,
            "updated": True,
            "from": installed["version"],
            "to": release.version,
            "result": result,
        }

    def check_updates(self) -> list[dict[str, Any]]:
        output = []
        for name, installed in sorted(self.installed_index().items()):
            if name in BUILTIN_MODS:
                continue
            try:
                release = self._select_release(name)
                available = version_obj(release.version) > version_obj(installed["version"])
                output.append({
                    "name": name,
                    "title": installed["title"],
                    "installed": installed["version"],
                    "latest": release.version,
                    "update_available": available,
                    "error": None,
                })
            except ManagerError as exc:
                output.append({
                    "name": name,
                    "title": installed["title"],
                    "installed": installed["version"],
                    "latest": None,
                    "update_available": False,
                    "error": str(exc),
                })
        return output

    def update_all(self) -> dict[str, Any]:
        checked = self.check_updates()
        results = []
        errors = []

        for item in checked:
            if not item["update_available"]:
                continue
            try:
                results.append(self.update_one(item["name"]))
            except ManagerError as exc:
                errors.append({
                    "name": item["name"],
                    "error": str(exc),
                })

        return {
            "updated": results,
            "errors": errors,
        }

    def dependency_issues(self) -> dict[str, list[dict[str, Any]]]:
        installed = self.installed_index()
        missing = []
        wrong_version = []
        incompatible = []

        for name, item in installed.items():
            if not item["enabled"]:
                continue

            for raw_dep in item.get("dependencies", []):
                dep = Dependency(**raw_dep)

                if dep.name in BUILTIN_MODS:
                    continue

                target = installed.get(dep.name)

                if dep.kind == "required":
                    if not target or not target["enabled"]:
                        missing.append({
                            "mod": name,
                            "dependency": dep.name,
                            "requirement": dep.raw,
                        })
                    elif not satisfies(target["version"], dep.operator, dep.version):
                        wrong_version.append({
                            "mod": name,
                            "dependency": dep.name,
                            "installed": target["version"],
                            "requirement": dep.raw,
                        })

                elif dep.kind == "incompatible":
                    if target and target["enabled"]:
                        incompatible.append({
                            "mod": name,
                            "dependency": dep.name,
                            "requirement": dep.raw,
                        })

        return {
            "missing": missing,
            "wrong_version": wrong_version,
            "incompatible": incompatible,
        }

    def dependents_of(self, name: str) -> list[str]:
        installed = self.installed_index()
        dependents = []

        for other_name, item in installed.items():
            if other_name == name:
                continue

            for raw_dep in item.get("dependencies", []):
                dep = Dependency(**raw_dep)
                if dep.kind == "required" and dep.name == name:
                    dependents.append(other_name)
                    break

        return sorted(set(dependents))

    def remove(self, name: str, force: bool = False) -> dict[str, Any]:
        name = parse_mod_name(name)
        dependents = self.dependents_of(name)

        if dependents and not force:
            raise ManagerError(
                f"{name} dibutuhkan oleh: {', '.join(dependents)}. "
                "Gunakan force jika tetap ingin menghapus."
            )

        entries = self._matching_entries(name)
        if not entries:
            raise ManagerError(f"{name} tidak ditemukan di folder mods.")

        removed = []
        for path in entries:
            removed.append(path.name)
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)

        data = self._read_mod_list()
        data["mods"] = [
            item
            for item in data["mods"]
            if not (isinstance(item, dict) and item.get("name") == name)
        ]
        self._write_mod_list(data)

        return {
            "name": name,
            "removed": removed,
            "dependents": dependents,
        }

    @property
    def profiles_dir(self) -> Path:
        path = self.config_path.parent / "profiles"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def backups_dir(self) -> Path:
        path = self.config_path.parent / "backups"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def diagnostics(self) -> dict[str, Any]:
        installed = self.list_installed()
        issues = self.dependency_issues()
        duplicates = self.duplicate_mods()
        invalid = self.invalid_mod_files()
        return {
            "mods_dir": str(self.mods_dir),
            "mods_dir_exists": self.mods_dir.exists(),
            "mod_list_exists": self.mod_list_path.exists(),
            "installed_count": len(installed),
            "enabled_count": sum(1 for x in installed if x["enabled"]),
            "dependency_issue_count": sum(len(v) for v in issues.values()),
            "duplicates": duplicates,
            "invalid_files": invalid,
        }

    def invalid_mod_files(self) -> list[dict[str, str]]:
        self.mods_dir.mkdir(parents=True, exist_ok=True)
        invalid = []
        for path in sorted(self.mods_dir.iterdir(), key=lambda x: x.name.lower()):
            if path.name.startswith('.') or path.name in {"mod-list.json", "mod-list.json.bak"}:
                continue
            if path.is_file() and path.suffix.lower() == '.zip':
                if self._read_info_from_zip(path) is None:
                    invalid.append({"file": path.name, "reason": "ZIP rusak atau info.json tidak valid"})
            elif path.is_dir() and (path / 'info.json').exists():
                if self._read_info_from_dir(path) is None:
                    invalid.append({"file": path.name, "reason": "info.json tidak valid"})
        return invalid

    def duplicate_mods(self) -> list[dict[str, Any]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in self.list_installed():
            groups.setdefault(item["name"], []).append(item)
        output = []
        for name, items in groups.items():
            if len(items) > 1:
                items = sorted(items, key=lambda x: version_obj(x["version"] or "0"), reverse=True)
                output.append({"name": name, "keep": items[0], "extras": items[1:]})
        return output

    def clean_duplicates(self) -> dict[str, Any]:
        removed = []
        for group in self.duplicate_mods():
            for item in group["extras"]:
                path = Path(item["path"])
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink(missing_ok=True)
                removed.append(item["file"])
        return {"removed": removed}

    def backup_state(self, label: str = "manual") -> dict[str, str]:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip("-") or "manual"
        target = self.backups_dir / f"{stamp}-{safe}"
        target.mkdir(parents=True, exist_ok=False)

        if self.mod_list_path.exists():
            shutil.copy2(self.mod_list_path, target / "mod-list.json")

        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "mods_dir": str(self.mods_dir),
            "factorio_version": self.config.get("factorio_version"),
            "mods": [
                {k: item.get(k) for k in ("name", "title", "version", "enabled", "file", "kind")}
                for item in self.list_installed()
            ],
        }
        (target / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"path": str(target), "manifest": str(target / "manifest.json")}

    def _profile_path(self, name: str) -> Path:
        clean = re.sub(r"[^A-Za-z0-9_. -]+", "", (name or "").strip()).strip()
        if not clean:
            raise ManagerError("Nama profile tidak valid.")
        return self.profiles_dir / f"{clean}.json"

    def list_profiles(self) -> list[dict[str, Any]]:
        result = []
        for path in sorted(self.profiles_dir.glob("*.json"), key=lambda p: p.name.lower()):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                result.append({
                    "name": data.get("name") or path.stem,
                    "created_at": data.get("created_at", ""),
                    "factorio_version": data.get("factorio_version", ""),
                    "mod_count": len(data.get("mods", [])),
                    "file": str(path),
                })
            except (OSError, json.JSONDecodeError):
                continue
        return result

    def save_profile(self, name: str) -> dict[str, Any]:
        path = self._profile_path(name)
        installed = self.list_installed()
        payload = {
            "format": 1,
            "name": path.stem,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "factorio_version": self.config.get("factorio_version", "2.0"),
            "mods": [
                {"name": x["name"], "version": x["version"], "enabled": bool(x["enabled"])}
                for x in installed
            ],
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"name": path.stem, "path": str(path), "mod_count": len(installed)}

    def delete_profile(self, name: str) -> None:
        path = self._profile_path(name)
        if not path.exists():
            raise ManagerError(f"Profile '{name}' tidak ditemukan.")
        path.unlink()

    def apply_profile(self, name: str) -> dict[str, Any]:
        path = self._profile_path(name)
        if not path.exists():
            raise ManagerError(f"Profile '{name}' tidak ditemukan.")
        data = json.loads(path.read_text(encoding="utf-8"))
        mods = data.get("mods", [])
        installed_results = []
        errors = []

        for item in mods:
            mod_name = item.get("name")
            version = item.get("version")
            if not mod_name or mod_name in BUILTIN_MODS:
                continue
            try:
                result = self.install(mod_name, version=version or None, include_dependencies=True, enable=bool(item.get("enabled", True)))
                installed_results.append({"name": mod_name, "result": result})
            except ManagerError as exc:
                errors.append({"name": mod_name, "error": str(exc)})

        # Apply enabled state after installs.
        for item in mods:
            mod_name = item.get("name")
            if mod_name and mod_name not in BUILTIN_MODS:
                try:
                    self.set_enabled(mod_name, bool(item.get("enabled", True)))
                except ManagerError:
                    pass

        return {"profile": path.stem, "applied": installed_results, "errors": errors}

    def repair_dependencies(self) -> dict[str, Any]:
        issues = self.dependency_issues()
        repaired = []
        errors = []
        seen = set()

        for issue in issues["missing"] + issues["wrong_version"]:
            requirement = issue.get("requirement", issue.get("dependency", ""))
            dep = parse_dependency(requirement)
            if not dep.name or dep.name in seen or dep.name in BUILTIN_MODS:
                continue
            seen.add(dep.name)
            try:
                release = self._select_release(dep.name, operator=dep.operator, required_version=dep.version)
                result = self.install(dep.name, version=release.version, include_dependencies=True, enable=True)
                repaired.append({"name": dep.name, "version": release.version, "result": result})
            except ManagerError as exc:
                errors.append({"name": dep.name, "error": str(exc)})

        return {
            "repaired": repaired,
            "errors": errors,
            "remaining": self.dependency_issues(),
        }

    def get_installed_mod(self, name: str) -> dict[str, Any]:
        name = parse_mod_name(name)
        mod = self.installed_index().get(name)
        if not mod:
            raise ManagerError(f"{name} belum terpasang.")
        return mod

    @property
    def mod_settings_dat_path(self) -> Path:
        return self.mods_dir / "mod-settings.dat"

    def _factorio_running(self) -> bool:
        system = platform.system().lower()
        try:
            if system == "windows":
                result = subprocess.run(
                    ["tasklist", "/FI", "IMAGENAME eq factorio.exe", "/NH"],
                    text=True,
                    capture_output=True,
                    timeout=5,
                )
                return "factorio.exe" in (result.stdout or "").lower()
            result = subprocess.run(
                ["pgrep", "-x", "factorio"],
                text=True,
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    @staticmethod
    def _setting_display_name(name: str) -> str:
        clean = re.sub(r"[-_.]+", " ", str(name or "")).strip()
        return clean[:1].upper() + clean[1:] if clean else str(name or "")

    def mod_settings_state(self, name: str) -> dict[str, Any]:
        """Return editable Factorio settings for one installed mod.

        Definitions are discovered from settings.lua, settings-updates.lua and
        settings-final-fixes.lua. Current values come from mod-settings.dat.
        A DAT/name heuristic is used as a fallback for settings generated by
        helper functions or Lua loops that a static scanner cannot fully parse.
        """
        name = parse_mod_name(name)
        mod = self.get_installed_mod(name)
        mod_path = Path(mod["path"])
        sources = read_settings_stage_sources(mod_path, str(mod.get("kind") or ""))
        prototypes = scan_setting_prototypes(sources)
        dat_path = self.mod_settings_dat_path
        values = {"startup": {}, "runtime-global": {}, "runtime-per-user": {}}
        dat_version = None
        dat_error = None
        warnings: list[str] = []

        if dat_path.exists():
            try:
                document = read_mod_settings(dat_path)
                values = settings_values(document)
                dat_version = ".".join(str(part) for part in document.version)
            except SettingsCodecError as exc:
                dat_error = str(exc)
                warnings.append(f"mod-settings.dat tidak dapat dibaca: {exc}")
        else:
            warnings.append("mod-settings.dat belum ada. Jalankan Factorio sampai menu utama sekali lalu tutup game.")

        source_blob = "\n".join(sources.values()).lower()
        definitions: dict[str, dict[str, Any]] = {item["name"]: dict(item) for item in prototypes}

        # Dynamic Lua helpers/loops can hide the table from static analysis.
        # Recover settings already serialized by Factorio using literal-name
        # detection and a conservative mod-prefix heuristic.
        for section, section_values in values.items():
            for setting_name, current in section_values.items():
                if setting_name in definitions:
                    continue
                literal_seen = setting_name.lower() in source_blob if source_blob else False
                prefix_match = setting_name_likely_belongs_to_mod(setting_name, name, mod.get("title") or "")
                if not (literal_seen or prefix_match):
                    continue
                definitions[setting_name] = {
                    "name": setting_name,
                    "type": infer_prototype_type(current),
                    "setting_type": section,
                    "default_value": None,
                    "minimum_value": None,
                    "maximum_value": None,
                    "allowed_values": None,
                    "hidden": False,
                    "order": None,
                    "source": "mod-settings.dat",
                    "detected_from_dat": True,
                    "ownership": "literal" if literal_seen else "prefix",
                }

        settings = []
        section_order = {"startup": 0, "runtime-global": 1, "runtime-per-user": 2}
        for setting_name, prototype in definitions.items():
            section = prototype.get("setting_type") or "startup"
            stored = setting_name in values.get(section, {})
            current = values.get(section, {}).get(setting_name, prototype.get("default_value"))
            item = dict(prototype)
            item.update({
                "display_name": self._setting_display_name(setting_name),
                "current_value": current,
                "stored": stored,
                "editable": not bool(prototype.get("hidden", False)),
            })
            settings.append(item)

        settings.sort(key=lambda item: (
            section_order.get(item.get("setting_type"), 9),
            str(item.get("order") or ""),
            str(item.get("name") or "").lower(),
        ))

        if sources and not settings:
            warnings.append(
                "Settings-stage files ditemukan, tetapi tidak ada prototype setting yang dapat dipetakan. "
                "Mod ini mungkin membuat setting secara dinamis atau hanya memodifikasi setting mod lain."
            )
        if not sources and not settings:
            warnings.append("Mod ini tidak mendeklarasikan setting standar Factorio yang terdeteksi.")

        return {
            "mod": mod,
            "dat_path": str(dat_path),
            "dat_exists": dat_path.exists(),
            "dat_version": dat_version,
            "dat_error": dat_error,
            "has_settings_stage": bool(sources),
            "settings_files": list(sources.keys()),
            "settings": settings,
            "editable_count": sum(1 for item in settings if item.get("editable")),
            "warnings": warnings,
            "factorio_running": self._factorio_running(),
        }

    def save_mod_settings(self, name: str, changes: dict[str, Any]) -> dict[str, Any]:
        name = parse_mod_name(name)
        if not isinstance(changes, dict) or not changes:
            raise ManagerError("Tidak ada perubahan setting untuk disimpan.")
        dat_path = self.mod_settings_dat_path
        if not dat_path.exists():
            raise ManagerError("mod-settings.dat belum ada. Jalankan Factorio sampai menu utama sekali lalu tutup game.")
        if self._factorio_running():
            raise ManagerError("Factorio masih berjalan. Tutup Factorio sebelum menyimpan setting agar perubahan tidak ditimpa game.")

        state = self.mod_settings_state(name)
        available = {item["name"]: item for item in state["settings"]}
        unknown = [key for key in changes if key not in available]
        if unknown:
            raise ManagerError(f"Setting tidak dikenal untuk mod {name}: {', '.join(unknown)}")

        try:
            document = read_mod_settings(dat_path)
        except SettingsCodecError as exc:
            raise ManagerError(f"Gagal membaca mod-settings.dat: {exc}") from exc

        normalized: dict[str, Any] = {}
        startup_changed = False
        runtime_global_changed = False
        runtime_user_changed = False
        for setting_name, raw_value in changes.items():
            prototype = available[setting_name]
            if not prototype.get("editable", True):
                raise ManagerError(f"Setting {setting_name} disembunyikan/terkunci oleh mod.")
            try:
                value = coerce_setting_value(prototype, raw_value)
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                raise ManagerError(f"Nilai {setting_name} tidak valid: {exc}") from exc
            try:
                set_document_setting(
                    document,
                    prototype["setting_type"],
                    setting_name,
                    value,
                    prototype.get("type"),
                )
            except SettingsCodecError as exc:
                raise ManagerError(f"Gagal menulis {setting_name}: {exc}") from exc
            normalized[setting_name] = value
            startup_changed = startup_changed or prototype["setting_type"] == "startup"
            runtime_global_changed = runtime_global_changed or prototype["setting_type"] == "runtime-global"
            runtime_user_changed = runtime_user_changed or prototype["setting_type"] == "runtime-per-user"

        backup_dir = self.backups_dir / "mod-settings"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = backup_dir / f"mod-settings-{stamp}.dat"
        shutil.copy2(dat_path, backup_path)
        try:
            write_mod_settings(dat_path, document, backup=False)
            # Re-read immediately. A malformed write must never be reported as success.
            read_mod_settings(dat_path)
        except (OSError, SettingsCodecError) as exc:
            try:
                shutil.copy2(backup_path, dat_path)
            except OSError:
                pass
            raise ManagerError(f"Gagal menyimpan mod-settings.dat; backup dipulihkan: {exc}") from exc

        return {
            "mod": name,
            "changed_count": len(normalized),
            "changes": normalized,
            "backup": str(backup_path),
            "dat_path": str(dat_path),
            "restart_required": startup_changed,
            "runtime_global_changed": runtime_global_changed,
            "runtime_per_user_changed": runtime_user_changed,
            "message": "Startup settings memerlukan restart Factorio." if startup_changed else "Settings saved.",
        }

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

    def launch_factorio(self) -> dict[str, Any]:
        executable = str(self.config.get("factorio_executable", "")).strip()
        if not executable:
            raise ManagerError("Factorio executable belum diatur di Settings.")
        exe = Path(executable).expanduser()
        if not exe.exists() or not exe.is_file():
            raise ManagerError(f"Factorio executable tidak ditemukan: {exe}")

        import shlex
        args = [str(exe)]
        launch_args = str(self.config.get("launch_args", "")).strip()
        if launch_args:
            args.extend(shlex.split(launch_args, posix=(platform.system().lower() != "windows")))

        process = subprocess.Popen(args, cwd=str(exe.parent))
        return {"pid": process.pid, "command": args}

