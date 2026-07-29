# Cambia el overlay de rutas SharePoint (sandbox <-> production) sin tocar secretos.
# Uso:
#   .\scripts\switch-env.ps1 -Target sandbox
#   .\scripts\switch-env.ps1 -Target production
#   .\scripts\switch-env.ps1 -Status
param(
    [ValidateSet("sandbox", "production")]
    [string]$Target,
    [switch]$Status,
    [switch]$Force,
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"

$AppRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$WorkspaceRoot = (Resolve-Path (Join-Path $AppRoot "..")).Path
$PrimaryEnv = Join-Path $WorkspaceRoot "api-hbi-powerAutomate.env"
$LocalEnv = Join-Path $AppRoot ".env"
$ActiveMarker = Join-Path $AppRoot ".env.active"
$OverlayDir = Join-Path $AppRoot "config\environments"

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
        $key = $line.Substring(0, $eq).Trim()
        $val = $line.Substring($eq + 1)
        $map[$key] = $val
    }
    return $map
}

function Find-OverlayValue {
    param(
        [System.Collections.IDictionary]$Overlay,
        [string]$Key
    )
    foreach ($ok in $Overlay.Keys) {
        if ([string]::Equals([string]$ok, $Key, [StringComparison]::OrdinalIgnoreCase)) {
            return @{ Found = $true; Key = [string]$ok; Value = [string]$Overlay[$ok] }
        }
    }
    return @{ Found = $false; Key = $null; Value = $null }
}

function Set-EnvKeysInFile {
    param(
        [string]$Path,
        [System.Collections.IDictionary]$Overlay,
        [string[]]$UnsetKeys,
        [string]$Label
    )
    if (-not (Test-Path $Path)) {
        throw "No existe archivo de entorno: $Path"
    }

    $toUnset = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    foreach ($uk in @($UnsetKeys)) {
        if ($uk) { [void]$toUnset.Add($uk.Trim()) }
    }

    $lines = Get-Content -LiteralPath $Path -Encoding UTF8
    $remaining = New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($ok in $Overlay.Keys) {
        [void]$remaining.Add([string]$ok)
    }
    $out = New-Object System.Collections.Generic.List[string]

    foreach ($raw in $lines) {
        $trim = $raw.TrimStart()
        if ($trim.StartsWith("#") -or [string]::IsNullOrWhiteSpace($raw)) {
            $out.Add($raw) | Out-Null
            continue
        }
        $eq = $raw.IndexOf("=")
        if ($eq -lt 1) {
            $out.Add($raw) | Out-Null
            continue
        }
        $key = $raw.Substring(0, $eq).Trim()
        if ($toUnset.Contains($key)) {
            $out.Add("# desactivada por overlay ${Label}: $raw") | Out-Null
            continue
        }
        $hit = Find-OverlayValue -Overlay $Overlay -Key $key
        if ($hit.Found) {
            $out.Add("$key=$($hit.Value)") | Out-Null
            [void]$remaining.Remove($hit.Key)
        }
        else {
            $out.Add($raw) | Out-Null
        }
    }

    if ($remaining.Count -gt 0) {
        $out.Add("") | Out-Null
        $out.Add("# --- overlay ($Label) keys anadidas ---") | Out-Null
        foreach ($key in @($Overlay.Keys)) {
            if ($remaining.Contains([string]$key)) {
                $out.Add("$key=$($Overlay[$key])") | Out-Null
            }
        }
    }

    $text = ($out -join "`r`n") + "`r`n"
    if ($WhatIf) {
        Write-Host "[WhatIf] Escribiria $($out.Count) lineas en $Path"
        return
    }
    [System.IO.File]::WriteAllText($Path, $text, (New-Object System.Text.UTF8Encoding $false))
}

function Show-Status {
    $active = $null
    if (Test-Path $ActiveMarker) {
        $active = (Get-Content -LiteralPath $ActiveMarker -Raw).Trim()
    }
    $primary = Get-EnvMap $PrimaryEnv
    $fromEnv = $null
    if ($primary.Contains("ACTIVE_ENVIRONMENT")) {
        $fromEnv = [string]$primary["ACTIVE_ENVIRONMENT"]
    }
    Write-Host "Marcador .env.active : $(if ($active) { $active } else { '(ausente)' })"
    Write-Host "ACTIVE_ENVIRONMENT   : $(if ($fromEnv) { $fromEnv } else { '(no definido)' })"
    Write-Host "Archivo deploy       : $PrimaryEnv"
    if ($primary.Contains("GRAPH_CLIENTS_BASE_PATH")) {
        Write-Host "GRAPH_CLIENTS_BASE   : $($primary['GRAPH_CLIENTS_BASE_PATH'])"
    }
    if ($primary.Contains("PAYMENT_VALIDATION_BASE_FOLDER")) {
        Write-Host "VALIDATION_BASE      : $($primary['PAYMENT_VALIDATION_BASE_FOLDER'])"
    }
}

if ($Status -or -not $Target) {
    if (-not $Target -and -not $Status) {
        Write-Host "Indica -Target sandbox|production o -Status"
    }
    Show-Status
    if (-not $Target) { exit 0 }
}

$overlayPath = Join-Path $OverlayDir "$Target.env"
if (-not (Test-Path $overlayPath)) {
    throw "No existe overlay: $overlayPath"
}

$overlay = Get-EnvMap $overlayPath
if ($overlay.Count -eq 0) {
    throw "Overlay vacio: $overlayPath"
}

if ($Target -eq "production") {
    $ready = $false
    if ($overlay.Contains("ENV_READY")) {
        $ready = ([string]$overlay["ENV_READY"]).Trim().ToLowerInvariant() -eq "true"
    }
    $hasTodo = @($overlay.Values | Where-Object { $_ -match "TODO_SET_" }).Count -gt 0
    if ((-not $ready -or $hasTodo) -and -not $Force) {
        Write-Error @"
Produccion aun no esta lista.
Rellena config/environments/production.env (quita TODO_SET_* y pon ENV_READY=true).
Cuando tengas capturas/rutas, actualiza ese archivo y vuelve a ejecutar.
Usa -Force solo para depuracion (peligroso).
"@
        exit 1
    }
}

# Claves de control del overlay: no viajan al .env de runtime
$unsetKeys = @()
if ($overlay.Contains("UNSET_KEYS")) {
    $unsetKeys = ([string]$overlay["UNSET_KEYS"]).Split(",") |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ }
    $overlay.Remove("UNSET_KEYS")
}
if ($overlay.Contains("ENV_READY")) {
    $overlay.Remove("ENV_READY")
}

Write-Host "==> Aplicando overlay '$Target'..."
Write-Host "    Fuente: $overlayPath"
if ($unsetKeys.Count -gt 0) {
    Write-Host "    Desactiva: $($unsetKeys -join ', ')"
}

Set-EnvKeysInFile -Path $PrimaryEnv -Overlay $overlay -UnsetKeys $unsetKeys -Label $Target

if (Test-Path $LocalEnv) {
    Set-EnvKeysInFile -Path $LocalEnv -Overlay $overlay -UnsetKeys $unsetKeys -Label $Target
    Write-Host "    Tambien actualizado: $LocalEnv"
}

if (-not $WhatIf) {
    [System.IO.File]::WriteAllText($ActiveMarker, "$Target`n", (New-Object System.Text.UTF8Encoding $false))
}

Write-Host "==> Listo. Entorno activo: $Target"
Show-Status
Write-Host ""
Write-Host "Siguiente paso deploy Azure:"
Write-Host "  .\scripts\build-azure-package.ps1"
Write-Host "  .\scripts\deploy-zipdeploy.ps1"
