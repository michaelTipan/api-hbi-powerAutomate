# Smoke Docker Oryx-like contra el ZIP readonly (local). No Azure.
param(
    [string]$ZipPath = "D:\CMC\HBI_Capital\azure-deploy-u4-rc-sandbox-ui-readonly.zip",
    [string]$WorkDir = "D:\CMC\HBI_Capital\_work\u4_rc_reproducible\docker_smoke"
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path $ZipPath)) { throw "Falta $ZipPath" }
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
$www = Join-Path $WorkDir "wwwroot"
if (Test-Path $www) { Remove-Item -Recurse -Force $www }
New-Item -ItemType Directory -Path $www | Out-Null
Expand-Archive -Path $ZipPath -DestinationPath $www -Force

# Asegurar flags cookie no-azure para smoke local en contenedor
$envPath = Join-Path $www ".env"
$raw = Get-Content $envPath -Raw -Encoding UTF8
if ($raw -notmatch 'UI_COOKIE_SECURE=false') {
    $raw = $raw -replace 'UI_COOKIE_SECURE=true', 'UI_COOKIE_SECURE=false'
    Set-Content $envPath $raw -Encoding UTF8
}

$script = @'
set -euo pipefail
cd /home/site/wwwroot
export PYTHONPATH="/home/site/wwwroot/.python_packages/lib/site-packages:${PYTHONPATH:-}"
export PATH="/home/site/wwwroot/.python_packages/lib/site-packages/bin:${PATH}"
# Arranque equivalente Oryx
python -m gunicorn -k uvicorn_worker.UvicornWorker application:app -b 0.0.0.0:8000 --workers 1 --timeout 120 &
pid=$!
for i in $(seq 1 90); do
  if curl -sf http://127.0.0.1:8000/health >/tmp/health.json; then break; fi
  sleep 1
done
if [ ! -s /tmp/health.json ]; then
  echo "HEALTH_FAIL"
  exit 1
fi
echo HEALTH=$(cat /tmp/health.json)
curl -sf http://127.0.0.1:8000/api/ui/v1/bootstrap >/tmp/boot.json
echo BOOT_OK
code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/app/)
echo APP=$code
codejs=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/app/assets/index-DyDwMASQ.js)
echo JS=$codejs
kill $pid || true
test "$code" = "200"
python - <<'PY'
import json
h=json.load(open("/tmp/health.json"))
b=json.load(open("/tmp/boot.json"))
assert h["status"]=="ok"
assert h["environment"]=="sandbox"
assert h["ui_enabled"] is True
assert str(h["build"]).startswith("u4-rc-")
assert b["active_environment"]=="sandbox"
assert b["writes_allowed"] is False
print("DOCKER_SMOKE_OK")
PY
'@
$scriptPath = Join-Path $WorkDir "smoke.sh"
[IO.File]::WriteAllText($scriptPath, ($script -replace "`r`n","`n"), (New-Object Text.UTF8Encoding $false))

docker run --rm `
  -v "${www}:/home/site/wwwroot" `
  -v "${scriptPath}:/smoke.sh:ro" `
  python:3.14-slim `
  bash -lc "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq curl >/dev/null && bash /smoke.sh"

if ($LASTEXITCODE -ne 0) { throw "docker smoke failed" }
Write-Output "DOCKER_SMOKE_OK"
