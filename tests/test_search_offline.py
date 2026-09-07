from pathlib import Path
from tempfile import TemporaryDirectory
import json
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
        self.search_payload = None
    def post(self, url, json=None, timeout=None):
        self.search_payload = json
        return FakeResponse({
            "pagination": {"count": 1, "page": 1, "page_count": 1, "page_size": 20},
            "results": [{
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
            }],
        })
    def get(self, url, params=None, timeout=None, **kwargs):
        if url.endswith("/api/mods"):
            return FakeResponse({
                "results": [{
                    "name": "demo",
                    "releases": [{"version": "1.2.3", "info_json": {"factorio_version": "2.0"}}],
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
        assert manager.session.search_payload["category"] == ["utilities"]
        assert manager.session.search_payload["exclude_tag"] == ["combat"]
        assert manager.session.search_payload["expansion"] == ["space-age"]
    print("Search offline tests: PASS")


if __name__ == "__main__":
    main()
