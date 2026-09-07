from pathlib import Path
from tempfile import TemporaryDirectory
import json
import zipfile

from factorio_settings import (
    ModSettingsDocument,
    PTNode,
    PT_DICTIONARY,
    PT_BOOL,
    PT_SIGNED_INTEGER,
    read_mod_settings,
    write_mod_settings,
    settings_values,
    set_document_setting,
    scan_setting_prototypes,
)
from manager import FactorioModManager


def make_doc():
    return ModSettingsDocument(
        version=(2, 0, 72, 0),
        quality_flag=False,
        root=PTNode(PT_DICTIONARY, {
            "startup": PTNode(PT_DICTIONARY, {
                "demo-enabled": PTNode(PT_DICTIONARY, {"value": PTNode(PT_BOOL, True)}),
                "demo-count": PTNode(PT_DICTIONARY, {"value": PTNode(PT_SIGNED_INTEGER, 5)}),
            }),
            "runtime-global": PTNode(PT_DICTIONARY, {}),
            "runtime-per-user": PTNode(PT_DICTIONARY, {}),
        }),
    )


def main():
    source = {
        "settings.lua": '''
            data:extend({
              { type = "bool-setting", name = "demo-enabled", setting_type = "startup", default_value = true },
              { type = "int-setting", name = "demo-count", setting_type = "startup", default_value = 5, minimum_value = 1, maximum_value = 20, allowed_values = {1, 5, 10, 20} },
              { type = "string-setting", name = "demo-mode", setting_type = "runtime-per-user", default_value = "normal", allowed_values = {"normal", "fast"} }
            })
        ''',
        "settings-updates.lua": '''data:extend({{type="double-setting", name="demo-scale", setting_type="runtime-global", default_value=1.5}})''',
    }
    prototypes = scan_setting_prototypes(source)
    by_name = {item["name"]: item for item in prototypes}
    assert set(by_name) == {"demo-enabled", "demo-count", "demo-mode", "demo-scale"}
    assert by_name["demo-count"]["allowed_values"] == [1, 5, 10, 20]
    assert by_name["demo-count"]["minimum_value"] == 1

    with TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        dat_path = tmp / "mod-settings.dat"
        document = make_doc()
        write_mod_settings(dat_path, document, backup=False)
        roundtrip = read_mod_settings(dat_path)
        assert roundtrip.version == (2, 0, 72, 0)
        assert settings_values(roundtrip)["startup"]["demo-enabled"] is True
        set_document_setting(roundtrip, "startup", "demo-count", 10, "int-setting")
        write_mod_settings(dat_path, roundtrip, backup=False)
        assert settings_values(read_mod_settings(dat_path))["startup"]["demo-count"] == 10

        mods = tmp / "mods"
        mods.mkdir()
        mod_zip = mods / "demo_1.0.0.zip"
        with zipfile.ZipFile(mod_zip, "w") as z:
            z.writestr("demo_1.0.0/info.json", json.dumps({
                "name": "demo",
                "title": "Demo Mod",
                "version": "1.0.0",
                "factorio_version": "2.0",
                "dependencies": ["base >= 2.0.0"],
            }))
            z.writestr("demo_1.0.0/settings.lua", source["settings.lua"])
            z.writestr("demo_1.0.0/settings-updates.lua", source["settings-updates.lua"])
        (mods / "mod-list.json").write_text(json.dumps({"mods": [{"name": "base", "enabled": True}, {"name": "demo", "enabled": True}]}), encoding="utf-8")
        write_mod_settings(mods / "mod-settings.dat", make_doc(), backup=False)

        manager = FactorioModManager(tmp / "config.json", project_root=tmp)
        manager.save_config({"mods_dir": str(mods), "factorio_version": "2.0"})
        state = manager.mod_settings_state("demo")
        assert state["dat_exists"] is True
        assert state["has_settings_stage"] is True
        names = {item["name"] for item in state["settings"]}
        assert {"demo-enabled", "demo-count", "demo-mode", "demo-scale"}.issubset(names)
        current = {item["name"]: item["current_value"] for item in state["settings"]}
        assert current["demo-count"] == 5

        manager._factorio_running = lambda: False
        saved = manager.save_mod_settings("demo", {"demo-enabled": False, "demo-count": "20", "demo-mode": "fast"})
        assert saved["changed_count"] == 3
        values = settings_values(read_mod_settings(mods / "mod-settings.dat"))
        assert values["startup"]["demo-enabled"] is False
        assert values["startup"]["demo-count"] == 20
        assert values["runtime-per-user"]["demo-mode"] == "fast"
        assert Path(saved["backup"]).exists()

    print("Settings editor offline tests: PASS")


if __name__ == "__main__":
    main()
