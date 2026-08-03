# Deploy produccion con UI ON (overlay production-ui-enabled).
# Solo lectura en SharePoint post-deploy: GET paths-probe (cero crear/mover/borrar).
#
# Uso:
#   .\scripts\deploy-production-readonly.ps1
#   .\scripts\deploy-production-readonly.ps1 -SkipDeploy   # solo gates live
#   .\scripts\deploy-production-readonly.ps1 -BuildId u4-rc-production-ui-20260803-1554
param(
    [ValidateSet("production-ui-enabled", "production")]
    [string]$Target = "production-ui-enabled",
    [string]$PublishSettingsPath = "D:\CMC\HBI_Capital\app-hbiauto-prod-001.PublishSettings",
    [string]$ZipPath = "",
    [string]$BuildId = "",
    [string]$PythonPackagesSource = "D:\CMC\HBI_Capital\_work\u4_rc_reproducible\linux-site-packages",
    [string]$EvidenceRoot = "D:\CMC\HBI_Capital\_work",
    [switch]$SkipSwitch,
    [switch]$SkipBuild,
    [switch]$SkipDeploy,
    [switch]$SkipFrontendBuild
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$AppRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$WorkspaceRoot = (Resolve-Path (Join-Path $AppRoot "..")).Path
$PrimaryEnv = Join-Path $WorkspaceRoot "api-hbi-powerAutomate.env"

function Get-EnvMap {
    param([string]$Path)
    $map = [ordered]@{}
    if (-not (Test-Path $Path)) { return $map }
    foreach ($raw in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $line = $raw.TrimEnd()
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        if ($line.TrimStart().StartsWith("#")) { continue }
        $eq = $line.IndexOf("=")
        if ($eq -lt 1) { continue }
        $map[$line.Substring(0, $eq).Trim()] = $line.Substring($eq + 1)
    }
    return $map
}

function Assert-ProductionUiEnv {
    param([System.Collections.IDictionary]$Map, [string]$Label)
    $active = [string]$Map["ACTIVE_ENVIRONMENT"]
    if ($active -ne "production") {
        throw ("{0}: ACTIVE_ENVIRONMENT debe ser production (got '{1}')" -f $Label, $active)
    }
    $clients = [string]$Map["GRAPH_CLIENTS_BASE_PATH"]
    if ($clients -match "PRUEBAS") {
        throw ("{0}: GRAPH_CLIENTS_BASE_PATH no debe contener PRUEBAS: {1}" -f $Label, $clients)
    }
    if ([string]::IsNullOrWhiteSpace($clients)) {
        throw ("{0}: falta GRAPH_CLIENTS_BASE_PATH" -f $Label)
    }
    $smoke = ([string]$Map["ACCOUNTING_FOLDER_SMOKE_ENABLED"]).Trim().ToLowerInvariant()
    if ($smoke -in @("1", "true", "yes", "on", "si", "sí")) {
        throw ("{0}: ACCOUNTING_FOLDER_SMOKE_ENABLED debe ser false" -f $Label)
    }
    if ($Target -eq "production-ui-enabled") {
        foreach ($k in @(
                "UI_ENABLED", "UI_WRITE_ENABLED", "UI_FINALIZE_ENABLED",
                "UI_NOTIFY_ENABLED", "UI_MERGE_ENABLED", "UI_AMORTIZATION_ENABLED",
                "UI_REVIEW_EDIT_ENABLED", "UI_ASIENTOS_UPLOAD_ENABLED"
            )) {
            if (([string]$Map[$k]).Trim().ToLowerInvariant() -ne "true") {
                throw ("{0}: {1} debe ser true en production-ui-enabled" -f $Label, $k)
            }
        }
        if (([string]$Map["UI_AUTH_MODE"]).Trim().ToLowerInvariant() -ne "local_session") {
            throw ("{0}: UI_AUTH_MODE debe ser local_session" -f $Label)
        }
        if (([string]$Map["UI_COOKIE_SECURE"]).Trim().ToLowerInvariant() -ne "true") {
            throw ("{0}: UI_COOKIE_SECURE debe ser true" -f $Label)
        }
    }
}

if (-not (Test-Path -LiteralPath $PublishSettingsPath)) {
    throw "PublishSettings no encontrado: $PublishSettingsPath"
}
if (-not (Test-Path -LiteralPath $PrimaryEnv)) {
    throw "Falta pack env: $PrimaryEnv"
}

$stamp = Get-Date -Format "yyyyMMdd-HHmm"
if (-not $BuildId) {
    $BuildId = "u4-rc-production-ui-$stamp"
}
$evidenceDir = Join-Path $EvidenceRoot ("u4_rc_production_ui_" + $stamp)
New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null
Write-Host "==> Evidence dir: $evidenceDir"
Write-Host "==> Target overlay: $Target  BuildId: $BuildId"

# --- 1) Switch overlay (no apaga UI flags) ---
if (-not $SkipSwitch) {
    Write-Host "`n==> switch-env -Target $Target"
    & (Join-Path $PSScriptRoot "switch-env.ps1") -Target $Target
    if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        throw "switch-env fallo con codigo $LASTEXITCODE"
    }
}

$envMap = Get-EnvMap $PrimaryEnv
Assert-ProductionUiEnv -Map $envMap -Label "pack .env post-switch"
Write-Host "   ACTIVE_ENVIRONMENT=production OK"
Write-Host "   GRAPH_CLIENTS_BASE=$($envMap['GRAPH_CLIENTS_BASE_PATH'])"
Write-Host "   ACCOUNTING_FOLDER_SMOKE_ENABLED=$($envMap['ACCOUNTING_FOLDER_SMOKE_ENABLED'])"
Write-Host "   UI_ENABLED=$($envMap['UI_ENABLED']) UI_WRITE_ENABLED=$($envMap['UI_WRITE_ENABLED'])"

# --- 2) Build package ---
if (-not $ZipPath) {
    $ZipPath = Join-Path $WorkspaceRoot ("azure-deploy-" + $BuildId + ".zip")
}
if (-not $SkipBuild) {
    if (-not (Test-Path -LiteralPath $PythonPackagesSource)) {
        throw "Falta PythonPackagesSource=$PythonPackagesSource"
    }
    Write-Host "`n==> build-azure-package BuildId=$BuildId"
    $buildArgs = @{
        AppRoot              = $AppRoot
        EnvSource            = $PrimaryEnv
        ZipPath              = $ZipPath
        PythonPackagesSource = $PythonPackagesSource
        BuildId              = $BuildId
    }
    if ($SkipFrontendBuild) { $buildArgs.SkipFrontendBuild = $true }
    & (Join-Path $PSScriptRoot "build-azure-package.ps1") @buildArgs
    if (-not (Test-Path -LiteralPath $ZipPath)) {
        throw "ZIP no generado: $ZipPath"
    }
}

$zipSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $ZipPath).Hash
Write-Host "ZIP=$ZipPath"
Write-Host "SHA256=$zipSha"
@{
    build_id = $BuildId
    zip      = $ZipPath
    sha256   = $zipSha
    target   = $Target
    at       = (Get-Date).ToString("o")
} | ConvertTo-Json | Set-Content -Path (Join-Path $evidenceDir "package.json") -Encoding UTF8

# --- 3) OneDeploy (clean=false restart=true) ---
[xml]$pub = Get-Content -Raw (Resolve-Path $PublishSettingsPath)
$p = $pub.publishData.publishProfile | Where-Object { $_.publishMethod -eq "ZipDeploy" } | Select-Object -First 1
if (-not $p) { throw "Perfil ZipDeploy no encontrado en PublishSettings" }
$scm = $p.publishUrl.Split(":")[0]
$destUrl = $p.destinationAppUrl.TrimEnd("/")
$pair = "{0}:{1}" -f $p.userName, $p.userPWD
$basic = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
$h = @{ Authorization = "Basic $basic" }
$scmBase = "https://$scm"

if (-not $SkipDeploy) {
    Write-Host "`n==> OneDeploy type=zip clean=false restart=true -> $scmBase"
    $uri = "$scmBase/api/publish?type=zip&clean=false&restart=true"
    $zipResolved = (Resolve-Path $ZipPath).Path
    # curl.exe evita prompts de Invoke-WebRequest en modo no interactivo.
    $curlArgs = @(
        "-sS", "-w", "%{http_code}",
        "-X", "POST",
        "-u", ("{0}:{1}" -f $p.userName, $p.userPWD),
        "-H", "Content-Type: application/zip",
        "--data-binary", ("@{0}" -f $zipResolved),
        "--max-time", "900",
        "-o", (Join-Path $evidenceDir "onedeploy-body.txt"),
        $uri
    )
    $httpCodeRaw = & curl.exe @curlArgs
    $httpCode = 0
    if ($httpCodeRaw -match "(\d{3})\s*$") {
        $httpCode = [int]$Matches[1]
    }
    Write-Host "   OneDeploy HTTP $httpCode"
    @{
        status_code = $httpCode
        uri         = $uri
        at          = (Get-Date).ToString("o")
        body_file   = "onedeploy-body.txt"
    } | ConvertTo-Json | Set-Content -Path (Join-Path $evidenceDir "onedeploy.json") -Encoding UTF8
    if ($httpCode -lt 200 -or $httpCode -ge 300) {
        $bodyPreview = ""
        $bodyPath = Join-Path $evidenceDir "onedeploy-body.txt"
        if (Test-Path $bodyPath) {
            $bodyPreview = (Get-Content -LiteralPath $bodyPath -Raw -ErrorAction SilentlyContinue)
            if ($bodyPreview.Length -gt 400) { $bodyPreview = $bodyPreview.Substring(0, 400) }
        }
        throw "OneDeploy fallo (HTTP $httpCode): $bodyPreview"
    }
}

# --- 4) Poll health: build + production + ui_enabled ---
Write-Host "`n==> Poll /health hasta build=$BuildId env=production ui_enabled=true"
$healthDeadline = (Get-Date).AddMinutes(12)
$health = $null
while ((Get-Date) -lt $healthDeadline) {
    try {
        $health = Invoke-RestMethod -Uri "$destUrl/health" -TimeoutSec 45
        $buildOk = [string]$health.build -eq $BuildId -or [string]$health.build_id -eq $BuildId
        if (-not $buildOk -and $health.PSObject.Properties.Name -contains "build") {
            $buildOk = [string]$health.build -eq $BuildId
        }
        $envOk = [string]$health.environment -eq "production" -or `
            [string]$health.active_environment -eq "production"
        $uiOk = $health.ui_enabled -eq $true -or [string]$health.ui_enabled -eq "true"
        Write-Host ("   health build={0} env={1} ui_enabled={2}" -f `
                $health.build, $health.environment, $health.ui_enabled)
        if ($buildOk -and $envOk -and $uiOk) { break }
        $health = $null
    }
    catch {
        Write-Host "   ... health aun no responde"
    }
    Start-Sleep -Seconds 15
}
if (-not $health) {
    throw "Timeout esperando /health con build=$BuildId production ui_enabled=true"
}
($health | ConvertTo-Json -Depth 8) | Set-Content -Path (Join-Path $evidenceDir "health.json") -Encoding UTF8

# --- 5) Bootstrap UI (no 404) ---
Write-Host "`n==> GET /api/ui/v1/bootstrap"
try {
    $boot = Invoke-RestMethod -Uri "$destUrl/api/ui/v1/bootstrap" -TimeoutSec 60
}
catch {
    throw "bootstrap UI fallo (UI apagada / 404?): $($_.Exception.Message)"
}
if ($boot.ui_enabled -ne $true) {
    throw "bootstrap.ui_enabled != true"
}
if ([string]$boot.active_environment -ne "production") {
    throw "bootstrap.active_environment != production (got $($boot.active_environment))"
}
if ($Target -eq "production-ui-enabled" -and $boot.writes_allowed -ne $true) {
    throw "bootstrap.writes_allowed != true (esperado con production-ui-enabled)"
}
($boot | ConvertTo-Json -Depth 8) | Set-Content -Path (Join-Path $evidenceDir "bootstrap.json") -Encoding UTF8
Write-Host "   bootstrap OK ui_enabled=$($boot.ui_enabled) writes=$($boot.writes_allowed) env=$($boot.active_environment)"

# --- 6) paths-probe GET RO (X-API-Key) ---
$apiKey = [string]$envMap["API_HTTP_KEY"]
if ([string]::IsNullOrWhiteSpace($apiKey)) {
    throw "Falta API_HTTP_KEY en $PrimaryEnv (necesaria para paths-probe)"
}
Write-Host "`n==> GET /graph/diagnostics/paths-probe (solo lectura)"
$probe = Invoke-RestMethod -Uri "$destUrl/graph/diagnostics/paths-probe" `
    -Headers @{ "X-API-Key" = $apiKey } -TimeoutSec 180
($probe | ConvertTo-Json -Depth 12) | Set-Content -Path (Join-Path $evidenceDir "paths-probe.json") -Encoding UTF8

$probeEnv = [string]$probe.active_environment
if (-not $probeEnv) { $probeEnv = [string]$probe.environment }
if ($probeEnv -ne "production") {
    throw "paths-probe env != production (got '$probeEnv')"
}
# Solo la base de clientes operativa: no debe apuntar a PRUEBAS.
# (excluded_folders si menciona PRUEBAS a proposito — no fallar por eso.)
$clientsProbe = ""
if ($probe.PSObject.Properties.Name -contains "clients_base_path") {
    $clientsProbe = [string]$probe.clients_base_path
}
elseif ($probe.PSObject.Properties.Name -contains "graph_clients_base_path") {
    $clientsProbe = [string]$probe.graph_clients_base_path
}
if (-not $clientsProbe -and $probe.checks) {
    foreach ($c in @($probe.checks)) {
        if ([string]$c.name -eq "clients_base") {
            $clientsProbe = [string]$c.path
            break
        }
    }
}
if ($clientsProbe -match "PRUEBAS") {
    throw "paths-probe clients_base contiene PRUEBAS: $clientsProbe"
}
if ($probe.read_only -ne $true -and [string]$probe.read_only -ne "true") {
    Write-Host "   AVISO: paths-probe.read_only no es true (got $($probe.read_only))"
}
Write-Host "   paths-probe OK env=$probeEnv clients_base=$clientsProbe"
Write-Host "`n==> GO parcial UI prod opt-in listo"
Write-Host "URL=$destUrl/app/"
Write-Host "BuildId=$BuildId"
Write-Host "SHA256=$zipSha"
Write-Host "Evidence=$evidenceDir"
