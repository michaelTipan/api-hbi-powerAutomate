# ZipDeploy por la API de despliegue de Kudu. A diferencia de subir por VFS, este
# endpoint reinicia el contenedor de la app al terminar, que es lo que hace falta
# cuando el rol Reader bloquea POST /api/app/restart.
param(
    [string]$PublishSettingsPath = (Join-Path $PSScriptRoot "..\..\..\HBI_Historico_Recursos\contexto-despliegue-anterior\app-hbiauto-prod-001.PublishSettings"),
    [string]$ZipPath = (Join-Path $PSScriptRoot "..\..\azure-deploy.zip")
)
$ErrorActionPreference = "Stop"

[xml]$pub = Get-Content -Raw (Resolve-Path $PublishSettingsPath)
$p = $pub.publishData.publishProfile | Where-Object { $_.publishMethod -eq "ZipDeploy" } | Select-Object -First 1
$scm = $p.publishUrl.Split(":")[0]
$destUrl = $p.destinationAppUrl.TrimEnd("/")
$pair = "{0}:{1}" -f $p.userName, $p.userPWD
$basic = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
$h = @{ Authorization = "Basic $basic" }
$base = "https://$scm"
$zip = (Resolve-Path $ZipPath).Path

Write-Host "==> ZipDeploy a $base/api/zipdeploy ..."
$zipBytes = [System.IO.File]::ReadAllBytes($zip)
try {
    Invoke-RestMethod -Uri "$base/api/zipdeploy" -Method POST -Headers $h `
        -Body $zipBytes -ContentType "application/zip" -TimeoutSec 900 | Out-Null
    Write-Host "   ZipDeploy aceptado"
} catch {
    $code = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { "?" }
    Write-Host "   FALLO (HTTP $code): $($_.Exception.Message)"
}

Write-Host "`n==> Esperando /graph/diagnostics (12 min)..."
$deadline = (Get-Date).AddSeconds(720)
$ok = $false
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 20
    try {
        $r = Invoke-WebRequest -Uri "$destUrl/graph/diagnostics" -UseBasicParsing -TimeoutSec 45
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch {
        $code = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { "?" }
        Write-Host "... HTTP $code"
    }
}

Write-Host ""
if ($ok) { Write-Host "CODIGO NUEVO ACTIVO" } else { Write-Host "SIGUE EL CODIGO VIEJO" }
