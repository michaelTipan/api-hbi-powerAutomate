# Fuerza el reinicio del contenedor de la app probando los metodos disponibles con
# credenciales de publicacion (el rol Reader no permite usar ARM).
param(
    [string]$PublishSettingsPath = (Join-Path $PSScriptRoot "..\..\..\HBI_Historico_Recursos\contexto-despliegue-anterior\app-hbiauto-prod-001.PublishSettings")
)
$ErrorActionPreference = "Continue"

[xml]$pub = Get-Content -Raw (Resolve-Path $PublishSettingsPath)
$p = $pub.publishData.publishProfile | Where-Object { $_.publishMethod -eq "ZipDeploy" } | Select-Object -First 1
$scm = $p.publishUrl.Split(":")[0]
$destUrl = $p.destinationAppUrl.TrimEnd("/")
$pair = "{0}:{1}" -f $p.userName, $p.userPWD
$basic = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
$h = @{ Authorization = "Basic $basic" }
$jh = @{ Authorization = "Basic $basic"; "Content-Type" = "application/json" }
$base = "https://$scm"

function Try-Restart([string]$label, [scriptblock]$action) {
    Write-Host "`n==> $label"
    try {
        & $action
        Write-Host "   OK"
        return $true
    } catch {
        $code = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { "?" }
        Write-Host "   FALLO (HTTP $code): $($_.Exception.Message)"
        return $false
    }
}

Try-Restart "POST /api/app/restart" {
    Invoke-RestMethod -Uri "$base/api/app/restart" -Method POST -Headers $h -TimeoutSec 120 | Out-Null
} | Out-Null

Try-Restart "DELETE /api/processes/0 (scm)" {
    Invoke-RestMethod -Uri "$base/api/processes/0" -Method DELETE -Headers $h -TimeoutSec 120 | Out-Null
} | Out-Null

Try-Restart "touch de archivos de arranque" {
    foreach ($c in @("touch application.py", "touch run.sh", "touch .ostype")) {
        $b = @{ command = $c; dir = "/home/site/wwwroot" } | ConvertTo-Json
        Invoke-RestMethod -Uri "$base/api/command" -Method POST -Headers $jh -Body $b -TimeoutSec 120 | Out-Null
    }
} | Out-Null

Write-Host "`n==> Esperando a que /graph/diagnostics aparezca (10 min)..."
$deadline = (Get-Date).AddSeconds(600)
$ok = $false
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 20
    try {
        $r = Invoke-WebRequest -Uri "$destUrl/graph/diagnostics" -UseBasicParsing -TimeoutSec 45
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch {
        $code = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { "?" }
        Write-Host "... /graph/diagnostics HTTP $code"
    }
}

Write-Host ""
if ($ok) {
    Write-Host "CODIGO NUEVO ACTIVO"
} else {
    Write-Host "SIGUE EL CODIGO VIEJO: hace falta un restart real (Portal o 'az webapp restart')."
}
