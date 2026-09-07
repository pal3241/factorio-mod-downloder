# Factorio Mod Manager Pro

Python Factorio mod manager with one shared core and three UI modes.

## Modes

### 1. Flet desktop app

```powershell
python launcher.py app
```

or double-click `run_app.bat`.

### 2. Flet web UI

```powershell
python launcher.py flet-web
```

Default: http://127.0.0.1:8550

### 3. Classic Flask web UI

```powershell
python launcher.py web
```

Default: http://127.0.0.1:5000

## Install

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python launcher.py app
```

## Core features

- automatic Factorio `mods` directory detection
- install mods from Mod Portal URL or internal ID
- no Factorio username/token required
- public re146 community storage for mod ZIPs
- official Mod Portal API for metadata
- SHA-1 validation before a downloaded ZIP reaches the live mods directory
- recursive required-dependency resolver
- select exact compatible mod version
- enable/disable through `mod-list.json`
- dependency diagnostics and one-click dependency repair
- update one / check updates / update all
- duplicate mod detection + cleanup
- invalid ZIP/info.json diagnostics
- remove protection when other mods depend on a mod
- mod profiles: save/apply/delete installed versions + enabled state
- state backups with manifest
- launch Factorio from the manager
- custom Factorio executable and launch arguments
- custom mods directory

## Safety model

Downloads are staged in a temporary directory first. The file is SHA-1 checked against
Factorio Mod Portal release metadata and its `info.json` is inspected before the verified
ZIP replaces an installed version.

`mod-list.json` is backed up to `mod-list.json.bak` before writes.

## Default Factorio mod paths

Windows:

```text
%APPDATA%\Factorio\mods
```

Linux:

```text
~/.factorio/mods
```

macOS:

```text
~/Library/Application Support/factorio/mods
```

## Project layout

```text
FactorioModManager-Pro/
├── manager.py       # shared core / resolver / install / profiles / repair
├── launcher.py      # app | flet-web | web selector
├── flet_app.py      # desktop + Flet web interface
├── app.py           # Flask API + classic web interface
├── templates/
├── static/
├── profiles/        # created automatically
├── backups/         # created automatically
├── requirements.txt
└── pyproject.toml
```

## Notes

Close Factorio before changing installed mod files. Built-in mods such as `base`,
`quality`, `space-age` and `elevated-rails` are never downloaded as community dependencies.
A newly released mod version may briefly be unavailable on the community mirror; in that
case the existing installed mod is left untouched.

## Application data

Manager config, profiles and backups are stored in a writable OS application-data directory. Flet packaged app bundles are read-only in Flet 0.86+, so runtime data is intentionally kept outside the application bundle.


## Factorio-style Search tab

Both Flask Web and Flet Desktop/Web now include a Mod Portal-inspired browser:

- Highlighted / Recently updated / Most downloaded / Trending / Search tabs
- Search by title, internal ID, summary, or author
- Include/exclude Space Age, category, and tag filters
- Factorio-version aware results
- Deprecated-mod toggle
- Pagination
- Thumbnail, author, summary, category, update time, Factorio compatibility, downloads and tags
- One-click Download / Update into the configured Factorio `mods` folder
- Exact Lookup remains available for pasting a Mod Portal URL or internal mod ID

The search data comes from the public Mod Portal browse/search interfaces. Downloads still use the configured community mirror flow and are SHA-1 verified before installation.


## Real per-mod settings editor (2.4)

The Settings button for an installed mod now scans all three Factorio settings-stage files
(`settings.lua`, `settings-updates.lua`, and `settings-final-fixes.lua`), decodes the local
`mod-settings.dat` PropertyTree, and exposes Startup / Map / Per-player values in both Flet
and Flask UIs. Saves are validated, backed up, written atomically, and re-read before success
is reported. Close Factorio before writing settings.
