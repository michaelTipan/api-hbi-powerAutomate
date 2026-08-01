# Empaqueta ZIP sandbox UI reproducible (local). No despliega.
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("sandbox-ui-readonly", "sandbox-ui-enabled")]
    [string]$Flavor,
    [string]$AppRoot = "",
    [string]$PythonPackagesSource = "D:\CMC\HBI_Capital\_work\u4_rc_reproducible\linux-site-packages",
    [string]$OutDir = "D:\CMC\HBI_Capital",
    [switch]$SkipFrontendBuild
)

$ErrorActionPreference = "Stop"
if (-not $AppRoot) {
    $AppRoot = Join-Path $PSScriptRoot ".."
}
$AppRoot = (Resolve-Path $AppRoot).Path
$overlay = Join-Path $AppRoot "config\environments\$Flavor.env"
if (-not (Test-Path $overlay)) { throw "Falta overlay $overlay" }
if (-not (Test-Path $PythonPackagesSource)) {
    throw "Falta PythonPackagesSource=$PythonPackagesSource (ejecuta build-linux-python-packages.ps1)"
}

# Materializar .env de empaquetado sin tocar el pack live de Azure.
$packEnv = Join-Path $env:TEMP ("u4-rc-r1-" + $Flavor + ".env")
$baseEnv = Join-Path (Resolve-Path (Join-Path $AppRoot "..")).Path "api-hbi-powerAutomate.env"
if (-not (Test-Path $baseEnv)) { throw "Falta pack env $baseEnv (secretos base)" }
Copy-Item $baseEnv $packEnv -Force

# Aplicar overlay sobre copia temporal
& (Join-Path $PSScriptRoot "switch-env.ps1") -Target $Flavor -WhatIf 2>$null | Out-Null
# Aplicación manual del overlay sobre $packEnv
$overlayMap = @{}
foreach ($raw in Get-Content $overlay -Encoding UTF8) {
    if ($raw -match '^\s*#' -or [string]::IsNullOrWhiteSpace($raw)) { continue }
    $eq = $raw.IndexOf('=')
    if ($eq -lt 1) { continue }
    $overlayMap[$raw.Substring(0, $eq).Trim()] = $raw.Substring($eq + 1)
}
$lines = Get-Content $packEnv -Encoding UTF8
$remaining = New-Object 'System.Collections.Generic.HashSet[string]'
foreach ($k in $overlayMap.Keys) { [void]$remaining.Add([string]$k) }
$out = New-Object System.Collections.Generic.List[string]
foreach ($raw in $lines) {
    $trim = $raw.TrimStart()
    if ($trim.StartsWith('#') -or [string]::IsNullOrWhiteSpace($raw)) { $out.Add($raw) | Out-Null; continue }
    $eq = $raw.IndexOf('=')
    if ($eq -lt 1) { $out.Add($raw) | Out-Null; continue }
    $key = $raw.Substring(0, $eq).Trim()
    if ($overlayMap.ContainsKey($key)) {
        $out.Add("$key=$($overlayMap[$key])") | Out-Null
        [void]$remaining.Remove($key)
    } else { $out.Add($raw) | Out-Null }
}
if ($remaining.Count -gt 0) {
    $out.Add("") | Out-Null
    $out.Add("# --- overlay $Flavor ---") | Out-Null
    foreach ($k in $overlayMap.Keys) {
        if ($remaining.Contains($k)) { $out.Add("$k=$($overlayMap[$k])") | Out-Null }
    }
}
[System.IO.File]::WriteAllText($packEnv, (($out -join "`r`n") + "`r`n"), (New-Object System.Text.UTF8Encoding $false))

$zipName = "azure-deploy-u4-rc-$Flavor.zip"
$zipPath = Join-Path $OutDir $zipName
$build = & (Join-Path $PSScriptRoot "build-azure-package.ps1") `
    -AppRoot $AppRoot `
    -EnvSource $packEnv `
    -ZipPath $zipPath `
    -PythonPackagesSource $PythonPackagesSource `
    -EnforceSandboxUi `
    -SkipFrontendBuild:$SkipFrontendBuild `
    -BuildId ("u4-rc-" + $Flavor + "-" + (git -C $AppRoot rev-parse --short HEAD))

$sha = (Get-FileHash -Algorithm SHA256 -LiteralPath $zipPath).Hash
Write-Host "ZIP=$zipPath"
Write-Host "SHA256=$sha"
Remove-Item $packEnv -Force -ErrorAction SilentlyContinue
