# Instala dependencias con el Python de Oryx (el del sandbox de Kudu no trae pip),
# reinicia el sitio y espera a que /health responda.
param(
    [string]$PublishSettingsPath = (Join-Path $PSScriptRoot "..\..\..\HBI_Historico_Recursos\contexto-despliegue-anterior\app-hbiauto-prod-001.PublishSettings")
)
$ErrorActionPreference = "Stop"

[xml]$pub = Get-Content -Raw (Resolve-Path $PublishSettingsPath)
$p = $pub.publishData.publishProfile | Where-Object { $_.publishMethod -eq "ZipDeploy" } | Select-Object -First 1
$scm = $p.publishUrl.Split(":")[0]
$destUrl = $p.destinationAppUrl.TrimEnd("/")
$pair = "{0}:{1}" -f $p.userName, $p.userPWD
$basic = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
$h = @{ Authorization = "Basic $basic" }
$jh = @{ Authorization = "Basic $basic"; "Content-Type" = "application/json" }
$base = "https://$scm"
$py = "/tmp/oryx/platforms/python/3.14.4/bin/python3"
$ld = "export LD_LIBRARY_PATH=/tmp/oryx/platforms/python/3.14.4/lib"

function Kudu([string]$cmd, [int]$t = 900) {
    $b = @{ command = $cmd; dir = "/home/site/wwwroot" } | ConvertTo-Json
    $r = Invoke-RestMethod -Uri "$base/api/command" -Method POST -Headers $jh -Body $b -TimeoutSec $t
    Write-Host ">> $cmd"
    if ($r.Output) { Write-Host $r.Output }
    if ($r.Error -and $r.Error -notlike "*backslashes*") { Write-Host "ERR: $($r.Error)" }
    return $r
}
function Bash([string]$inner, [int]$t = 900) {
    $esc = $inner -replace '"', '\"'
    Kudu "bash -c `"$esc`"" $t
}

Write-Host "==> pip install (Oryx python -m pip)..."
Bash "$ld; $py -m pip --version"
Bash "$ld; $py -m pip install -r requirements.txt -t .python_packages/lib/site-packages" 1800

foreach ($pkg in @("fastapi", "dotenv", "uvicorn", "gunicorn", "azure/identity", "azure/keyvault")) {
    $r = Kudu "test -d .python_packages/lib/site-packages/$pkg"
    if ($r.ExitCode -ne 0) { Write-Host "FALTA: $pkg" } else { Write-Host "OK: $pkg" }
}

Write-Host "==> Prueba de import..."
$importPy = "import fastapi, dotenv, gunicorn, uvicorn`nfrom app.main import app`nprint('IMPORT_OK')"
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($importPy))
Bash "echo $b64 | base64 -d > /tmp/import_test.py"
$imp = Bash "$ld; PYTHONPATH=/home/site/wwwroot:/home/site/wwwroot/.python_packages/lib/site-packages $py /tmp/import_test.py"
if ($imp.Output -notmatch "IMPORT_OK") { Write-Host "IMPORT FALLO"; exit 1 }

Kudu "rm -f main.py hostingstart.html output.tar.zst"

Write-Host "==> Intentando fijar startup command via Kudu..."
try {
    $body = '{"WEBSITE_STARTUP_COMMAND":"bash /home/site/wwwroot/run.sh"}'
    Invoke-RestMethod -Uri "$base/api/settings" -Method PUT -Headers $jh -Body $body -TimeoutSec 30 | Out-Null
    Write-Host "WEBSITE_STARTUP_COMMAND fijado"
} catch {
    Write-Host "Settings PUT fallo (rol Reader): $($_.Exception.Message)"
}

Write-Host "==> Reiniciando..."
try {
    Invoke-RestMethod -Uri "$base/api/app/restart" -Method POST -Headers $h -TimeoutSec 120 | Out-Null
    Write-Host "restart OK"
} catch {
    Write-Host "restart bloqueado, usando touch .ostype"
    Kudu "touch .ostype"
}
Start-Sleep -Seconds 60

Write-Host "==> Poll /health (8 min)..."
$deadline = (Get-Date).AddSeconds(480)
$healthOk = $false
$healthBody = ""
while ((Get-Date) -lt $deadline) {
    try {
        $health = Invoke-RestMethod -Uri "$destUrl/health" -Method GET -TimeoutSec 45
        if ($health.status -eq "ok") {
            $healthOk = $true
            $healthBody = ($health | ConvertTo-Json -Compress)
            break
        }
    } catch {
        $code = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { "?" }
        Write-Host "... /health HTTP $code"
    }
    Start-Sleep -Seconds 20
}

if (-not $healthOk) {
    Write-Host "==> StartupLogs..."
    try {
        $logDir = Invoke-RestMethod -Uri "$base/api/vfs/LogFiles/StartupLogs/" -Headers $h
        $latest = ($logDir | Sort-Object mtime -Descending | Select-Object -First 1).name
        Write-Host "Log: $latest"
        $log = Invoke-WebRequest -Uri "$base/api/vfs/LogFiles/StartupLogs/$latest" -Headers $h -UseBasicParsing -TimeoutSec 90
        ($log.Content -split "`n") | Select-Object -Last 80 | ForEach-Object { Write-Host $_ }
    } catch { Write-Host $_.Exception.Message }
}

Write-Host ""
Write-Host "URL:    $destUrl"
Write-Host "Health: $(if ($healthOk) { $healthBody } else { 'FAIL' })"
if (-not $healthOk) { exit 1 }
