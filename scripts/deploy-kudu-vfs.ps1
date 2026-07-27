# Sube el paquete a Kudu VFS y lo extrae en wwwroot, evitando el build de Oryx.
param(
    [string]$PublishSettingsPath = (Join-Path $PSScriptRoot "..\..\..\HBI_Historico_Recursos\contexto-despliegue-anterior\app-hbiauto-prod-001.PublishSettings"),
    [string]$ZipPath = (Join-Path $PSScriptRoot "..\..\azure-deploy.zip"),
    [switch]$SkipBuild
)
$ErrorActionPreference = "Stop"

if (-not $SkipBuild) {
    & (Join-Path $PSScriptRoot "build-azure-package.ps1") -ZipPath $ZipPath
}

[xml]$pub = Get-Content -Raw (Resolve-Path $PublishSettingsPath)
$p = $pub.publishData.publishProfile | Where-Object { $_.publishMethod -eq "ZipDeploy" } | Select-Object -First 1
$scm = $p.publishUrl.Split(":")[0]
$destUrl = $p.destinationAppUrl.TrimEnd("/")
$pair = "{0}:{1}" -f $p.userName, $p.userPWD
$basic = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
$h = @{ Authorization = "Basic $basic" }
$jh = @{ Authorization = "Basic $basic"; "Content-Type" = "application/json" }
$base = "https://$scm"
$zip = (Resolve-Path $ZipPath).Path

$remoteZip = "deploy-package-$(Get-Date -Format 'yyyyMMddHHmmss').zip"
Write-Host "==> Subiendo zip a Kudu ($remoteZip)..."
$zipBytes = [System.IO.File]::ReadAllBytes($zip)
Invoke-RestMethod -Uri "$base/api/vfs/site/wwwroot/$remoteZip" -Method PUT -Headers $h `
    -Body $zipBytes -ContentType "application/zip" -TimeoutSec 300

Write-Host "==> Extrayendo en wwwroot (sin Oryx build)..."
$cmds = @(
    "rm -rf app antenv __pycache__ output.tar.zst oryx-manifest.toml oryx.env main.py",
    "unzip -o $remoteZip",
    "chmod +x startup.sh run.sh",
    "ln -sfn .python_packages/lib/site-packages __oryx_packages__",
    "rm -f $remoteZip",
    "ls -la app/main.py application.py .env"
)
foreach ($c in $cmds) {
    $cmdBody = @{ command = $c; dir = "/home/site/wwwroot" } | ConvertTo-Json
    $result = Invoke-RestMethod -Uri "$base/api/command" -Method POST -Headers $jh -Body $cmdBody -TimeoutSec 600
    Write-Host ">> $c"
    if ($result.Output) { Write-Host $result.Output }
    if ($result.Error -and $result.Error -notlike "*backslashes*") {
        Write-Host "ERR: $($result.Error)"
    }
}

Write-Host "==> Zip extraido. Siguiente paso: oryx-pip-and-health.ps1"
Write-Host "URL: $destUrl"
