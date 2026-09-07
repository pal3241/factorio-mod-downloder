from pathlib import Path
from tempfile import TemporaryDirectory
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from manager import FactorioModManager


class FakeResponse:
    def __init__(self, data=None, text="", status_code=200):
        self._data = data
        self.text = text
        self.status_code = status_code

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self):
        self.search_params = None

    def post(self, *args, **kwargs):
        raise AssertionError("Tokenless search must never call POST /api/search")

    def get(self, url, params=None, timeout=None, headers=None, **kwargs):
        if url.endswith("/search"):
            self.search_params = list(params or [])
            return FakeResponse(text=(
                '<div>Found 1 mods</div>'
                '<a href="/mod/demo">Demo Mod</a>'
                '<a href="/mod/demo">Demo Mod duplicate link</a>'
            ))

        if url.endswith("/api/mods/demo/full"):
            return FakeResponse({
                "name": "demo",
                "title": "Demo Mod",
                "owner": "tester",
                "summary": "demo",
                "category": "utilities",
                "downloads_count": 1234,
                "thumbnail": "/demo.png",
                "tags": ["logistics"],
                "updated_at": "2026-09-07T10:00:00Z",
                "requires_space_age": False,
                "releases": [
                    {"version": "1.2.3", "info_json": {"factorio_version": "2.0"}}
                ],
            })

        if url.endswith("/api/mods"):
            return FakeResponse({
                "results": [{
                    "name": "demo",
                    "releases": [
                        {"version": "1.2.3", "info_json": {"factorio_version": "2.0"}}
                    ],
                }]
            })

        raise AssertionError(url)


def main():
    with TemporaryDirectory() as td:
        td = Path(td)
        manager = FactorioModManager(td / "cfg.json")
        manager.save_config({"mods_dir": str(td / "mods"), "factorio_version": "2.0"})
        manager.session = FakeSession()

        result = manager.search_mods(
            "demo",
            sort_attribute="relevancy",
            categories=["utilities", "NOT_VALID"],
            exclude_tags=["combat"],
            expansions=["space-age"],
        )

        assert result["pagination"]["count"] == 1
        item = result["results"][0]
        assert item["name"] == "demo"
        assert item["latest_version"] == "1.2.3"
        assert item["factorio_version_display"] == "2.0"
        assert item["thumbnail"].startswith("https://assets-mod.factorio.com/")

        params = manager.session.search_params
        assert ("factorio_version", "2.0") in params
        assert ("query", "demo") in params
        assert ("category", "utilities") in params
        assert not any(x == ("category", "NOT_VALID") for x in params)
        assert ("exclude_tag", "combat") in params
        assert ("expansion", "space-age") in params

    print("Search offline tests: PASS")


if __name__ == "__main__":
    main()
