from pathlib import Path

from flask import Flask, jsonify, render_template, request

from manager import FactorioModManager, ManagerError
from storage import app_data_dir


APP_DIR = Path(__file__).resolve().parent
manager = FactorioModManager(app_data_dir() / "manager-config.json")

app = Flask(__name__)


def ok(**data):
    return jsonify({"ok": True, **data})


def fail(error: Exception, status: int = 400):
    return jsonify({"ok": False, "error": str(error)}), status


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/config")
def get_config():
    return ok(config=manager.get_config())


@app.post("/api/config")
def save_config():
    try:
        payload = request.get_json(silent=True) or {}
        config = manager.save_config({
            key: payload[key]
            for key in ("mods_dir", "factorio_version", "install_dependencies", "factorio_executable", "launch_args")
            if key in payload
        })
        return ok(config=config)
    except ManagerError as exc:
        return fail(exc)


@app.get("/api/installed")
def installed():
    try:
        return ok(
            mods=manager.list_installed(),
            issues=manager.dependency_issues(),
        )
    except ManagerError as exc:
        return fail(exc)


@app.get("/api/search-meta")
def search_meta():
    return ok(meta=manager.portal_search_meta())


@app.post("/api/search-mods")
def search_mods():
    try:
        payload = request.get_json(silent=True) or {}
        return ok(search=manager.search_mods(
            payload.get("query", ""),
            sort_attribute=payload.get("sort_attribute", "last_updated_at"),
            page=payload.get("page", 1),
            page_size=payload.get("page_size", 20),
            categories=payload.get("categories") or [],
            exclude_categories=payload.get("exclude_categories") or [],
            tags=payload.get("tags") or [],
            exclude_tags=payload.get("exclude_tags") or [],
            expansions=payload.get("expansions") or [],
            exclude_expansions=payload.get("exclude_expansions") or [],
            show_deprecated=bool(payload.get("show_deprecated", False)),
        ))
    except (ManagerError, ValueError, TypeError) as exc:
        return fail(exc)


@app.get("/api/recent")
def recent():
    try:
        limit = int(request.args.get("limit", "24"))
        return ok(mods=manager.recent_mods(limit))
    except (ValueError, ManagerError) as exc:
        return fail(exc)


@app.get("/api/mod")
def mod_info():
    try:
        return ok(mod=manager.portal_view(request.args.get("q", "")))
    except ManagerError as exc:
        return fail(exc, 404 if "tidak ditemukan" in str(exc).lower() else 400)


@app.post("/api/install")
def install():
    try:
        payload = request.get_json(silent=True) or {}
        result = manager.install(
            payload.get("mod", ""),
            version=payload.get("version") or None,
            include_dependencies=payload.get("include_dependencies"),
            enable=bool(payload.get("enable", True)),
        )
        return ok(result=result)
    except ManagerError as exc:
        return fail(exc)


@app.post("/api/enable")
def enable():
    try:
        payload = request.get_json(silent=True) or {}
        manager.set_enabled(
            payload.get("mod", ""),
            bool(payload.get("enabled", True)),
        )
        return ok()
    except ManagerError as exc:
        return fail(exc)


@app.post("/api/remove")
def remove():
    try:
        payload = request.get_json(silent=True) or {}
        result = manager.remove(
            payload.get("mod", ""),
            force=bool(payload.get("force", False)),
        )
        return ok(result=result)
    except ManagerError as exc:
        return fail(exc)


@app.get("/api/updates")
def updates():
    try:
        return ok(updates=manager.check_updates())
    except ManagerError as exc:
        return fail(exc)


@app.post("/api/update")
def update():
    try:
        payload = request.get_json(silent=True) or {}
        return ok(result=manager.update_one(payload.get("mod", "")))
    except ManagerError as exc:
        return fail(exc)


@app.post("/api/update-all")
def update_all():
    try:
        return ok(result=manager.update_all())
    except ManagerError as exc:
        return fail(exc)


@app.get("/api/diagnostics")
def diagnostics():
    try:
        return ok(diagnostics=manager.diagnostics())
    except ManagerError as exc:
        return fail(exc)


@app.post("/api/repair")
def repair():
    try:
        return ok(result=manager.repair_dependencies())
    except ManagerError as exc:
        return fail(exc)


@app.post("/api/clean-duplicates")
def clean_duplicates():
    try:
        return ok(result=manager.clean_duplicates())
    except ManagerError as exc:
        return fail(exc)


@app.post("/api/backup")
def backup():
    try:
        payload = request.get_json(silent=True) or {}
        return ok(result=manager.backup_state(payload.get("label", "manual")))
    except ManagerError as exc:
        return fail(exc)


@app.get("/api/profiles")
def profiles():
    try:
        return ok(profiles=manager.list_profiles())
    except ManagerError as exc:
        return fail(exc)


@app.post("/api/profile/save")
def profile_save():
    try:
        payload = request.get_json(silent=True) or {}
        return ok(result=manager.save_profile(payload.get("name", "")))
    except ManagerError as exc:
        return fail(exc)


@app.post("/api/profile/apply")
def profile_apply():
    try:
        payload = request.get_json(silent=True) or {}
        return ok(result=manager.apply_profile(payload.get("name", "")))
    except (ManagerError, OSError, ValueError) as exc:
        return fail(exc)


@app.post("/api/profile/delete")
def profile_delete():
    try:
        payload = request.get_json(silent=True) or {}
        manager.delete_profile(payload.get("name", ""))
        return ok()
    except ManagerError as exc:
        return fail(exc)


@app.get("/api/mod/settings")
def get_mod_settings():
    try:
        return ok(settings=manager.mod_settings_state(request.args.get("mod", "")))
    except ManagerError as exc:
        return fail(exc)


@app.post("/api/mod/settings")
def save_mod_settings():
    try:
        payload = request.get_json(silent=True) or {}
        return ok(result=manager.save_mod_settings(payload.get("mod", ""), payload.get("changes") or {}))
    except ManagerError as exc:
        return fail(exc)


@app.post("/api/mod/open-location")
def open_mod_location():
    try:
        payload = request.get_json(silent=True) or {}
        return ok(result=manager.open_mod_location(payload.get("mod", "")))
    except ManagerError as exc:
        return fail(exc)


@app.get("/api/app-update")
def app_update_status():
    try:
        return ok(status=manager.app_update_status(fetch=True))
    except ManagerError as exc:
        return fail(exc)


@app.post("/api/app-update/pull")
def app_update_pull():
    try:
        return ok(result=manager.pull_app_update())
    except ManagerError as exc:
        return fail(exc)


@app.post("/api/launch")
def launch_factorio():
    try:
        return ok(result=manager.launch_factorio())
    except ManagerError as exc:
        return fail(exc)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
