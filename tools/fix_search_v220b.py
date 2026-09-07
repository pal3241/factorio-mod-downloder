from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"patch target not found: {label}")
    return text.replace(old, new, 1)


# manager.py
path = ROOT / "manager.py"
text = path.read_text(encoding="utf-8")
text = replace_once(text, "from dataclasses import dataclass\n", "from concurrent.futures import ThreadPoolExecutor, as_completed\nfrom dataclasses import dataclass\n", "concurrent import")
text = replace_once(text, "from urllib.parse import urlparse\n", "from urllib.parse import unquote, urlparse\n", "urllib import")

new_search_block = r"""    def _public_mod_details(self, names: list[str]) -> list[dict[str, Any]]:
        \"\"\"Fetch public full metadata for visible portal results without credentials.\"\"\"
        unique: list[str] = []
        for raw_name in names:
            name = unquote(str(raw_name or \"\")).strip()
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
                    continue

        ordered = [by_name[name] for name in unique if name in by_name]
        return self._decorate_search_results(ordered)

    @staticmethod
    def _mod_names_from_portal_html(html: str, limit: int = 20) -> list[str]:
        names: list[str] = []
        for raw_name in re.findall(r'href=[\"\\\']/mod/([^\"\\\'/?#]+)', html, flags=re.IGNORECASE):
            name = unquote(raw_name).strip()
            if MOD_ID_RE.fullmatch(name) and name not in names:
                names.append(name)
            if len(names) >= limit:
                break
        return names

    @staticmethod
    def _portal_html_pagination(html: str, page: int, page_size: int, result_count: int) -> dict[str, int]:
        count = 0
        found = re.search(r\"Found\\s+([0-9][0-9.,\\s]*)\\s+mods?\", html, flags=re.IGNORECASE)
        if found:
            digits = re.sub(r\"\\D\", \"\", found.group(1))
            if digits:
                count = int(digits)

        page_numbers = [int(value) for value in re.findall(r\"[?&]page=(\\d+)\", html)]
        if count:
            page_count = max(1, (count + page_size - 1) // page_size)
        elif page_numbers:
            page_count = max(max(page_numbers), page)
        else:
            page_count = page

        if not count:
            count = result_count if page == 1 else max(result_count, (page - 1) * page_size + result_count)

        return {
            \"count\": count,
            \"page\": page,
            \"page_count\": page_count,
            \"page_size\": page_size,
        }

    def highlighted_mods(self, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 20))
        response = self.session.get(
            f\"{MOD_PORTAL}/highlights\",
            params={\"page\": page},
            headers={\"Accept\": \"text/html,application/xhtml+xml\"},
            timeout=25,
        )
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ManagerError(f\"Gagal mengambil highlighted mods: {exc}\") from exc

        names = self._mod_names_from_portal_html(response.text, page_size)
        results = self._public_mod_details(names)
        pagination = self._portal_html_pagination(response.text, page, page_size, len(results))
        return {\"pagination\": pagination, \"results\": results, \"sort_attribute\": \"highlighted\"}

    def search_mods(
        self,
        query: str = \"\",
        *,
        sort_attribute: str = \"last_updated_at\",
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
        \"\"\"Tokenless search using public Mod Portal HTML plus public mod metadata API.\"\"\"
        allowed_sorts = {item[\"id\"] for item in PORTAL_SORT_MODES}
        if sort_attribute not in allowed_sorts:
            raise ManagerError(\"Sort mode tidak valid.\")

        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 20))
        query = str(query or \"\").strip()

        if sort_attribute == \"highlighted\" and not query:
            return self.highlighted_mods(page=page, page_size=page_size)
        if sort_attribute == \"highlighted\":
            sort_attribute = \"relevancy\"

        category_ids = {item[\"id\"] for item in PORTAL_CATEGORIES}
        tag_ids = {item[\"id\"] for item in PORTAL_TAGS}
        expansion_ids = {\"space-age\"}

        def clean(values, allowed):
            return [value for value in (values or []) if value in allowed]

        if query or sort_attribute == \"relevancy\":
            endpoint = f\"{MOD_PORTAL}/search\"
        else:
            endpoint = {
                \"last_updated_at\": f\"{MOD_PORTAL}/browse/updated\",
                \"most_downloads\": f\"{MOD_PORTAL}/browse/downloaded\",
                \"trending\": f\"{MOD_PORTAL}/browse/trending\",
            }.get(sort_attribute, f\"{MOD_PORTAL}/search\")

        params: list[tuple[str, str]] = [
            (\"factorio_version\", factorio_branch(self.config[\"factorio_version\"])),
            (\"sort_attribute\", sort_attribute),
            (\"page\", str(page)),
        ]
        if query:
            params.append((\"query\", query))
        if show_deprecated:
            params.append((\"show_deprecated\", \"true\"))

        for value in clean(categories, category_ids):
            params.append((\"category\", value))
        for value in clean(exclude_categories, category_ids):
            params.append((\"exclude_category\", value))
        for value in clean(tags, tag_ids):
            params.append((\"tag\", value))
        for value in clean(exclude_tags, tag_ids):
            params.append((\"exclude_tag\", value))
        for value in clean(expansions, expansion_ids):
            params.append((\"expansion\", value))
        for value in clean(exclude_expansions, expansion_ids):
            params.append((\"exclude_expansion\", value))

        response = self.session.get(
            endpoint,
            params=params,
            headers={\"Accept\": \"text/html,application/xhtml+xml\"},
            timeout=30,
        )
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ManagerError(f\"Factorio Mod Portal public search error: {exc}\") from exc

        names = self._mod_names_from_portal_html(response.text, page_size)
        results = self._public_mod_details(names)
        pagination = self._portal_html_pagination(response.text, page, page_size, len(results))
        return {\"pagination\": pagination, \"results\": results, \"sort_attribute\": sort_attribute}

"""

pattern = re.compile(r"    def highlighted_mods\(.*?\n    def recent_mods\(", re.DOTALL)
match = pattern.search(text)
if not match:
    raise RuntimeError("manager search block not found")
text = text[:match.start()] + new_search_block + "    def recent_mods(" + text[match.end():]
path.write_text(text, encoding="utf-8")

# flet_app.py
path = ROOT / "flet_app.py"
text = path.read_text(encoding="utf-8")
text = replace_once(text, '            "exclude_categories": set(),\n', '            "exclude_categories": {"internal"},\n', "Flet default internal")
text = replace_once(
    text,
    '            bgcolor="#f1d7a4",\n            color="#34291d",\n            border_color="#8c6e46",\n',
    '            bgcolor="#171512",\n            color="#eee7df",\n            border_color="#49423a",\n            focused_border_color="#a56d32",\n            hint_style=ft.TextStyle(color="#77716b"),\n',
    "Flet search field",
)
text = text.replace('                    bgcolor="#e6a13d" if active else "#3b3834",\n                    color="#201509" if active else "#e8e0d6",\n', '                    bgcolor="#875a2e" if active else "#302d29",\n                    color="#f5e5d3" if active else "#d8d0c7",\n')
text = replace_once(
    text,
    '                include = ft.Checkbox(label=item["label"], value=False, expand=True)\n                exclude = ft.IconButton(icon=ft.Icons.BLOCK, tooltip=f\'Exclude {item["label"]}\', icon_color="#8f8a84")\n',
    '                inc_state, exc_state = state_sets(group)\n                include = ft.Checkbox(label=item["label"], value=item["id"] in inc_state, expand=True)\n                exclude = ft.IconButton(icon=ft.Icons.BLOCK, tooltip=f\'Exclude {item["label"]}\', icon_color="#d28b2f" if item["id"] in exc_state else "#77716b")\n',
    "Flet filter state",
)
text = text.replace('ban.icon_color = "#8f8a84"', 'ban.icon_color = "#77716b"')
text = text.replace('ban.icon_color = "#f0aa00"', 'ban.icon_color = "#d28b2f"')
text = text.replace('                        bgcolor="#e6a13d" if page_no == current_page else "#3b3834",\n                        color="#201509" if page_no == current_page else "#e8e0d6",\n', '                        bgcolor="#875a2e" if page_no == current_page else "#302d29",\n                        color="#f5e5d3" if page_no == current_page else "#d8d0c7",\n')
text = replace_once(
    text,
    '        search_bar = ft.Row(controls=[query, ft.Button("Exact Lookup", on_click=exact_lookup), ft.Button("Search", icon=ft.Icons.SEARCH, on_click=submit_search)])\n',
    '        search_bar = ft.Row(controls=[query, ft.Button("Exact Lookup", on_click=exact_lookup, bgcolor="#24211e", color="#d8d0c7"), ft.Button("Search", icon=ft.Icons.SEARCH, on_click=submit_search, bgcolor="#2b2824", color="#e6ded5")])\n',
    "Flet search buttons",
)
path.write_text(text, encoding="utf-8")

# web JS default exclusion
path = ROOT / "static" / "app.js"
text = path.read_text(encoding="utf-8")
text = replace_once(text, '        excludeCategories: new Set(),\n', '        excludeCategories: new Set(["internal"]),\n', "web internal exclusion")
path.write_text(text, encoding="utf-8")

# web CSS contrast
path = ROOT / "static" / "style.css"
text = path.read_text(encoding="utf-8")
text = replace_once(text, '.portal-tab.active {\n    background: linear-gradient(#f3c06a, #d68d31);\n    color: #24190c;\n    box-shadow: inset 0 1px #ffe0a4;\n}\n', '.portal-tab.active {\n    background: linear-gradient(#936331, #76502c);\n    color: #f5e5d3;\n    box-shadow: inset 0 1px #a97945;\n}\n', "web tab contrast")
text = replace_once(text, '.portal-searchbar input {\n    background: #f1d7a4;\n    color: #34291d;\n    border-color: #8c6e46;\n    font-size: 17px;\n}\n.portal-searchbar input::placeholder { color: #74634d; }\n', '.portal-searchbar input {\n    background: #171512;\n    color: #eee7df;\n    border-color: #49423a;\n    font-size: 17px;\n}\n.portal-searchbar input:focus { border-color: #a56d32; }\n.portal-searchbar input::placeholder { color: #77716b; }\n', "web search contrast")
path.write_text(text, encoding="utf-8")

# version
path = ROOT / "pyproject.toml"
text = path.read_text(encoding="utf-8")
text = replace_once(text, 'version = "2.1.0"', 'version = "2.2.0"', "version")
path.write_text(text, encoding="utf-8")

# changelog
path = ROOT / "CHANGELOG.md"
text = path.read_text(encoding="utf-8")
entry = """# Changelog

## 2.2.0

- Fixed Search Mods HTTP 403 in no-login mode.
- Replaced authenticated `POST /api/search` usage with public Mod Portal browse/search pages plus public per-mod metadata.
- Preserved query, sort, filters, exclusions, and pagination without username/token.
- Added bounded concurrent metadata enrichment for the visible page.
- Excluded `Internal` by default and reduced Search UI contrast in Flet and Web modes.
- Added an offline regression test that rejects any `POST /api/search` call.

"""
if text.startswith("# Changelog\n\n"):
    text = entry + text[len("# Changelog\n\n"):]
else:
    text = entry + text
path.write_text(text, encoding="utf-8")

print("Search v2.2 patch applied")
