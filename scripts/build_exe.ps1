$ErrorActionPreference = "Stop"
python -m pip install -r requirements.txt
python -m pip install pyinstaller pillow
python tools/generate_icon.py
flet pack flet_app.py `
  --name FactorioModManager `
  --icon assets/icon.ico `
  --product-name "Factorio Mod Manager" `
  --product-version "3.0.0" `
  --file-version "3.0.0.0" `
  --file-description "Factorio Mod Manager" `
  --company-name "Community" `
  --bundle-id "dev.factorio.modmanager" `
  --yes
Write-Host "Built: dist\\FactorioModManager.exe"
