# ZipDeploy por la API de despliegue de Kudu. A diferencia de subir por VFS, este
# endpoint reinicia el contenedor de la app al terminar, que es lo que hace falta
# cuando el rol Reader bloquea POST /api/app/restart.
#
# Post-deploy: polla GET /health (publico). Opcionalmente paths-probe + bootstrap
# con X-API-Key leida del pack local. Ya NO espera 12 min a /graph/diagnostics
# sin API key (falso negativo habitual con API_HTTP_KEY activa).
param(
    [string]$PublishSettingsPath = (Join-Path $PSScriptRoot "..\..\..\HBI_Historico_Recursos\contexto-despliegue-anterior\app-hbiauto-prod-001.PublishSettings"),
    [string]$ZipPath = (Join-Path $PSScriptRoot "..\..\azure-deploy.zip"),
    # Subcadena esperada en health.build / health.commit (ej. sha corto o marker u4-rc-...).
    [string]$ExpectedBuild = "",
    # Pack local con API_HTTP_KEY (gitignored). Default: deploy pack HBI Capital.
    [string]$EnvFilePath = "D:\CMC\HBI_Capital\api-hbi-powerAutomate.env",
    # Tiempo maximo esperando reinicio + /health ok (segundos).
    [int]$HealthTimeoutSec = 240,
    [int]$HealthPollSec = 10
)
$ErrorActionPreference = "Stop"

function Get-ApiHttpKeyFromEnvFile {
    param([string]$Path)
    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    $line = Select-String -Path $Path -Pattern "^\s*API_HTTP_KEY\s*=" |
        Select-Object -First 1
    if (-not $line) {
        return $null
    }
    $raw = $line.Line
    $idx = $raw.IndexOf("=")
    if ($idx -lt 0) {
        return $null
    }
    $val = $raw.Substring($idx + 1).Trim().Trim('"').Trim("'")
    if (-not $val) {
        return $null
    }
    return $val
}

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
$zipDeployOk = $false
try {
    Invoke-RestMethod -Uri "$base/api/zipdeploy" -Method POST -Headers $h `
        -Body $zipBytes -ContentType "application/zip" -TimeoutSec 900 | Out-Null
    Write-Host "   ZipDeploy aceptado"
    $zipDeployOk = $true
} catch {
    $code = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { "?" }
    Write-Host "   FALLO (HTTP $code): $($_.Exception.Message)"
}

if (-not $zipDeployOk) {
    Write-Host "`nABORT: ZipDeploy no aceptado; no se hace poll de health."
    exit 1
}

# Si no pasaron ExpectedBuild, intentar sha corto del repo (informativo).
if (-not $ExpectedBuild) {
    try {
        Push-Location (Join-Path $PSScriptRoot "..")
        $ExpectedBuild = (git rev-parse --short HEAD 2>$null)
    } catch {
        $ExpectedBuild = ""
    } finally {
        Pop-Location -ErrorAction SilentlyContinue
    }
}

Write-Host "`n==> Esperando GET /health (max ${HealthTimeoutSec}s)..."
if ($ExpectedBuild) {
    Write-Host "    ExpectedBuild substring: $ExpectedBuild"
}
$deadline = (Get-Date).AddSeconds([Math]::Max(30, $HealthTimeoutSec))
$healthOk = $false
$healthPayload = $null
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds ([Math]::Max(3, $HealthPollSec))
    try {
        $healthPayload = Invoke-RestMethod -Uri "$destUrl/health" -TimeoutSec 30
        $status = [string]$healthPayload.status
        $build = [string]$healthPayload.build
        $commit = [string]$healthPayload.commit
        $envName = [string]$healthPayload.environment
        $ui = $healthPayload.ui_enabled
        Write-Host ("... health status={0} build={1} env={2} ui={3}" -f $status, $build, $envName, $ui)
        if ($status -ne "ok") {
            continue
        }
        if ($ExpectedBuild) {
            $blob = "$build $commit"
            if ($blob -notlike "*$ExpectedBuild*") {
                Write-Host "    build/commit aun no coincide con ExpectedBuild; reintentando..."
                continue
            }
        }
        $healthOk = $true
        break
    } catch {
        $code = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { "?" }
        Write-Host "... health HTTP $code (contenedor reiniciando?)"
    }
}

Write-Host ""
if (-not $healthOk) {
    Write-Host "POLL /health NO confirmo status=ok a tiempo."
    Write-Host "ZipDeploy pudo haber quedado bien: revise manualmente /health y DEPLOY_CONTEXT.md §4."
    exit 2
}

Write-Host "CODIGO ACTIVO (/health ok)"
Write-Host ("  build={0} commit={1} environment={2} ui_enabled={3}" -f `
    $healthPayload.build, $healthPayload.commit, $healthPayload.environment, $healthPayload.ui_enabled)

$apiKey = Get-ApiHttpKeyFromEnvFile -Path $EnvFilePath
if (-not $apiKey) {
    Write-Host "`nAVISO: no hay API_HTTP_KEY en $EnvFilePath"
    Write-Host "  Omitiendo paths-probe autenticado. Corra §4 de DEPLOY_CONTEXT.md a mano."
    exit 0
}

Write-Host "`n==> Verificacion autenticada (X-API-Key desde pack local)..."
$probeOk = $false
try {
    $pr = Invoke-RestMethod -Uri "$destUrl/graph/diagnostics/paths-probe" `
        -Headers @{ "X-API-Key" = $apiKey } -TimeoutSec 120
    $probeEnv = [string]$pr.active_environment
    $clients = $pr.checks | Where-Object { $_.name -eq "clients_base" } | Select-Object -First 1
    $clientsPath = if ($clients) { [string]$clients.path } else { "" }
    Write-Host ("  paths-probe env={0} clients_base={1}" -f $probeEnv, $clientsPath)
    $probeOk = $true
} catch {
    $code = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { "?" }
    Write-Host "  paths-probe FALLO (HTTP $code): $($_.Exception.Message)"
}

try {
    $boot = Invoke-RestMethod -Uri "$destUrl/api/ui/v1/bootstrap" -TimeoutSec 45
    Write-Host ("  bootstrap auth={0} env={1} writes={2} notify={3} merge={4} amort={5}" -f `
        $boot.auth_mode, $boot.active_environment, $boot.writes_allowed, `
        $boot.notify_allowed, $boot.merge_allowed, $boot.amortization_allowed)
} catch {
    $code = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { "?" }
    Write-Host "  bootstrap FALLO (HTTP $code): $($_.Exception.Message)"
}

if ($probeOk) {
    Write-Host "`nPOST-DEPLOY CHECKS OK (health + paths-probe)."
    exit 0
}

Write-Host "`nPOST-DEPLOY: health OK; paths-probe no confirmo. Revise DEPLOY_CONTEXT.md §4."
exit 3
