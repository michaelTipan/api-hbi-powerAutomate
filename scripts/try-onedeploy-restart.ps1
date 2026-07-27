# Ultimo intento automatizado de reinicio: OneDeploy y variantes del endpoint de deploy.
param(
    [string]$PublishSettingsPath = (Join-Path $PSScriptRoot "..\..\..\HBI_Historico_Recursos\contexto-despliegue-anterior\app-hbiauto-prod-001.PublishSettings"),
    [string]$ZipPath = (Join-Path $PSScriptRoot "..\..\azure-deploy.zip")
)
$ErrorActionPreference = "Continue"

[xml]$pub = Get-Content -Raw (Resolve-Path $PublishSettingsPath)
$p = $pub.publishData.publishProfile | Where-Object { $_.publishMethod -eq "ZipDeploy" } | Select-Object -First 1
$scm = $p.publishUrl.Split(":")[0]
$destUrl = $p.destinationAppUrl.TrimEnd("/")
$pair = "{0}:{1}" -f $p.userName, $p.userPWD
$basic = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
$h = @{ Authorization = "Basic $basic" }
$base = "https://$scm"
$zipBytes = [System.IO.File]::ReadAllBytes((Resolve-Path $ZipPath).Path)

$attempts = @(
    @{ label = "OneDeploy (publish?type=zip&restart=true)"; uri = "$base/api/publish?type=zip&restart=true&clean=false"; body = $zipBytes; ctype = "application/zip"; method = "POST" },
    @{ label = "OneDeploy (publish?type=static, solo restart)"; uri = "$base/api/publish?type=static&path=/home/site/wwwroot/.restarttrigger&restart=true"; body = [Text.Encoding]::UTF8.GetBytes("1"); ctype = "application/octet-stream"; method = "POST" },
    @{ label = "restart via /api/app/restart?soft=false"; uri = "$base/api/app/restart?soft=false"; body = $null; ctype = $null; method = "POST" }
)

foreach ($a in $attempts) {
    Write-Host "`n==> $($a.label)"
    try {
        if ($a.body) {
            Invoke-RestMethod -Uri $a.uri -Method $a.method -Headers $h -Body $a.body -ContentType $a.ctype -TimeoutSec 600 | Out-Null
        } else {
            Invoke-RestMethod -Uri $a.uri -Method $a.method -Headers $h -TimeoutSec 300 | Out-Null
        }
        Write-Host "   ACEPTADO"
    } catch {
        $code = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { "?" }
        Write-Host "   FALLO (HTTP $code)"
    }
}

Write-Host "`n==> Comprobando /graph/diagnostics (4 min)..."
$deadline = (Get-Date).AddSeconds(240)
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
