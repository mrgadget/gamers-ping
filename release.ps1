# Usage: .\release.ps1 0.3.0
# Bumps the version, builds the exe, tags, pushes and publishes a GitHub Release.
# Installed copies pick it up automatically (see gamers_ping/updater.py).
param([Parameter(Mandatory = $true)][string]$Version)
$ErrorActionPreference = "Stop"
if (git status --porcelain) { throw "Working tree not clean - commit first." }
Set-Content -Encoding ascii gamers_ping\__init__.py "__version__ = `"$Version`""
python -m unittest discover -s tests
if ($LASTEXITCODE) { throw "Tests failed" }
.\build.ps1
git commit -am "Release v$Version"
git tag "v$Version"
git push origin main "v$Version"
gh release create "v$Version" dist\GamersPing.exe --title "Gamers Ping v$Version" --generate-notes
