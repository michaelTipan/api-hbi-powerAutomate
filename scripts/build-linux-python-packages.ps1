# Construye site-packages Linux (cpython-314) para empaquetado reproducible U4-RC-R1.
# No toca Azure. Requiere Docker Desktop.
param(
    [string]$AppRoot = (Join-Path $PSScriptRoot ".."),
    [string]$OutDir = "D:\CMC\HBI_Capital\_work\u4_rc_reproducible\linux-site-packages",
    [string]$DockerImage = "python:3.14-slim",
    [string]$ManifestPath = "D:\CMC\HBI_Capital\_work\u4_rc_reproducible\linux_dependencies_manifest.json"
)

$ErrorActionPreference = "Stop"
$AppRoot = (Resolve-Path $AppRoot).Path
$OutDir = [System.IO.Path]::GetFullPath($OutDir)
$ManifestPath = [System.IO.Path]::GetFullPath($ManifestPath)
$req = Join-Path $AppRoot "requirements.txt"
if (-not (Test-Path $req)) { throw "Falta requirements.txt" }

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $ManifestPath) | Out-Null
# Limpiar en host (rm -rf sobre volumen Docker/Windows es frágil)
Get-ChildItem -LiteralPath $OutDir -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force

$reqSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $req).Hash
$probePy = Join-Path $env:TEMP ("u4_rc_deps_probe_" + [guid]::NewGuid().ToString("N") + ".py")

@'
import importlib
import json
import os
import platform
import sys
import time
from pathlib import Path

root = Path("/out")
sys.path.insert(0, str(root))

mods = [
    "fastapi",
    "pydantic",
    "gunicorn",
    "uvicorn",
    "uvicorn_worker",
    "openpyxl",
    "pypdf",
    "reportlab",
    "pandas",
    "httpx",
    "dotenv",
    "jwt",
    "azure.identity",
    "azure.keyvault.secrets",
]
imported = {}
for m in mods:
    try:
        mod = importlib.import_module(m)
        imported[m] = {
            "ok": True,
            "version": getattr(mod, "__version__", None),
            "file": getattr(mod, "__file__", None),
        }
    except Exception as e:
        imported[m] = {"ok": False, "error": f"{type(e).__name__}: {e}"}

so = pyd = 0
so_tags: set[str] = set()
for p in root.rglob("*"):
    if not p.is_file():
        continue
    if p.suffix == ".so":
        so += 1
        name = p.name
        if "cpython-314" in name:
            so_tags.add("cpython-314")
        if "x86_64" in name:
            so_tags.add("x86_64")
        if "linux" in name:
            so_tags.add("linux")
    if p.suffix == ".pyd":
        pyd += 1

manifest = {
    "docker_image": os.environ.get("U4_DOCKER_IMAGE", "python:3.14-slim"),
    "python_version": sys.version,
    "platform": platform.platform(),
    "machine": platform.machine(),
    "pip_target": "/out",
    "requirements_sha256": os.environ.get("U4_REQ_SHA", ""),
    "so_count": so,
    "pyd_count": pyd,
    "so_tags": sorted(so_tags),
    "imports": imported,
    "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
}
critical = [
    "fastapi",
    "pydantic",
    "gunicorn",
    "uvicorn",
    "uvicorn_worker",
    "openpyxl",
    "pypdf",
    "reportlab",
    "pandas",
    "httpx",
    "dotenv",
]
bad = [k for k in critical if not imported.get(k, {}).get("ok")]
manifest["ok"] = pyd == 0 and not bad and (so == 0 or "cpython-314" in so_tags)
Path("/manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print(json.dumps({"ok": manifest["ok"], "so": so, "pyd": pyd, "bad": bad, "tags": sorted(so_tags)}))
if not manifest["ok"]:
    raise SystemExit(2)
'@ | Set-Content -Path $probePy -Encoding UTF8

Write-Host "==> Docker $DockerImage -> $OutDir"
$probeDir = Split-Path $probePy
$probeName = Split-Path $probePy -Leaf
$manifestDir = Split-Path $ManifestPath

docker run --rm `
  -e "U4_DOCKER_IMAGE=$DockerImage" `
  -e "U4_REQ_SHA=$reqSha" `
  -v "${AppRoot}:/src:ro" `
  -v "${OutDir}:/out" `
  -v "${probeDir}:/probe:ro" `
  -v "${manifestDir}:/manifest_dir" `
  $DockerImage `
  bash -lc "set -euo pipefail; python -V; pip -V; pip install --no-cache-dir -r /src/requirements.txt -t /out; python /probe/$probeName; cp /manifest.json /manifest_dir/linux_dependencies_manifest.json"

if ($LASTEXITCODE -ne 0) {
    throw "Fallo build Linux packages (docker exit $LASTEXITCODE)"
}

Write-Host "==> OK packages + manifest"
if (Test-Path $ManifestPath) {
    Get-Content $ManifestPath -TotalCount 35
}
