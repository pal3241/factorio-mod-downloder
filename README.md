# Factorio Mod Manager

Factorio Mod Manager 3 is a Windows-first mod manager with a Flet desktop UI, optional Flet/Flask web modes, tokenless Mod Portal browsing, dependency management, profiles, updates, and a real per-mod settings editor.

## Windows — recommended

Download `FactorioModManager.exe` from the latest GitHub Release and run it directly.

- no Python installation required
- no `.bat` launcher required
- single-file Windows executable
- custom app/taskbar icon
- settings, profiles, and backups remain in the writable OS application-data directory

## Source mode

Development/source users can still run the project with Python:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python launcher.py app
```

Optional UIs:

```powershell
python launcher.py flet-web
python launcher.py web
```

## 3.0 highlights

### Full Mod Portal-style detail page

Clicking a mod in **Search** now opens a dedicated detail view instead of a small lookup card. It includes:

- large thumbnail, title, owner, summary, category, Factorio versions and download count
- compatible version selector and install/download action
- **Information** tab with owner, created date, source, homepage, license, latest version and description
- **Downloads** tab with release history
- **Dependencies** tab for the selected release
- **Changelog** tab
- **Metrics** tab with local/portal metadata
- Back to Search navigation

### Appearance customization

Settings → Appearance supports editable HEX colors for:

- menu / sidebar
- main background
- accent color

Built-in presets:

- Midnight Blue
- Pure Black
- Blue Slate
- Factorio Dark
- Custom

Changes apply immediately after **Save & Apply** and persist between launches.

### New Windows app icon

The Windows EXE uses an original midnight-blue gear + orange download-arrow icon. Multi-resolution `.ico` and a 1024×1024 PNG source are generated under `assets/`.

## Application updater

### Packaged EXE

The packaged Windows app checks **GitHub Releases**. When a newer `FactorioModManager.exe` release is available, the manager downloads it, exits safely, replaces the old EXE, and launches the new version.

### Source clone

Source mode keeps the safe updater based on:

```text
git fetch
git pull --ff-only
```

Local uncommitted changes or diverged branches block automatic pull.

## Mod-management features

- automatic Factorio `mods` directory detection
- custom mods directory
- install from Mod Portal URL or internal ID
- no Factorio username/token required
- community mirror ZIP downloads
- official Mod Portal metadata and SHA-1 validation
- staged verification before replacing an installed mod
- recursive required-dependency resolver
- select an exact compatible version
- enable/disable via `mod-list.json`
- dependency diagnostics and one-click repair
- update one / check updates / update all
- duplicate detection and cleanup
- invalid ZIP/info.json diagnostics
- dependency-aware remove protection
- profiles: save/apply/delete installed versions + enabled state
- state backups
- launch Factorio from the manager
- custom Factorio executable and launch arguments

## Search browser

Search includes:

- Highlighted
- Recently updated
- Most downloaded
- Trending
- Search mods
- title / ID / summary / author searching
- include/exclude Space Age, category, and tag filters
- Factorio-version-aware results
- deprecated-mod toggle
- pagination
- thumbnails, author, summary, category, compatibility, downloads and tags
- one-click Download / Update

Search ordering is obtained from public Factorio Mod Portal browse/search pages; metadata is enriched with public Mod Portal API data. Downloaded ZIPs are SHA-1 verified before installation.

## Real per-mod settings editor

The ⚙ button for an installed mod scans:

```text
settings.lua
settings-updates.lua
settings-final-fixes.lua
```

and decodes local `mod-settings.dat` values. It exposes:

- Startup settings
- Map / runtime-global settings
- Per-player settings
- bool / int / double / string / color values
- allowed-values and numeric validation when discoverable

Writes are backed up, atomic, and verified by reading the file again. Close Factorio before saving mod settings.

## Performance

The manager caches installed-mod scans using a filesystem fingerprint, so unchanged ZIPs are not reopened on every refresh. Mod Portal full metadata also uses a short-lived cache to reduce repeated network requests.

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

## Application data

Runtime state is intentionally stored outside the executable/bundle. Depending on platform/Flet runtime it uses the app-private data directory, with Windows falling back to Local AppData.

Typical Windows location:

```text
%LOCALAPPDATA%\FactorioModManagerPro\
```

## Build Windows EXE from source

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1
```

Output:

```text
dist\FactorioModManager.exe
```

The build uses Flet Pack / PyInstaller and embeds `assets/icon.ico`.

## Project layout

```text
factorio-mod-downloder/
├── app_version.py
├── manager.py
├── factorio_settings.py
├── process_restart.py
├── flet_app.py
├── launcher.py
├── app.py
├── assets/
│   ├── icon.png
│   └── icon.ico
├── scripts/
│   └── build_exe.ps1
├── tools/
│   └── generate_icon.py
├── templates/
├── static/
├── tests/
├── requirements.txt
└── pyproject.toml
```

## Notes

Close Factorio before changing installed mod files or `mod-settings.dat`. Built-in mods such as `base`, `quality`, `space-age`, and `elevated-rails` are not downloaded as community dependencies. A newly released version can briefly be absent from the configured community mirror; the existing installed copy is left untouched if installation fails.

## v3.0.1 — Visual color picker + Desktop portable install

The Appearance page now shows a circular live preview beside every editable theme color,
a visible `#RRGGBB` field, and a **Pilih warna** dialog with a palette of circular swatches.
Preset colors continue to work and update every preview immediately.

On Windows, a packaged `FactorioModManager.exe` launched from Downloads or another folder
installs/relaunches itself from the user's real Windows Desktop folder. The app stores the
Desktop build version in its application-data directory so an older portable copy cannot
overwrite a newer Desktop build.

