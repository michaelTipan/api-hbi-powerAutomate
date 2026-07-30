# Valida el zip de Azure Deploy. Normaliza siempre paths a "/" (Windows/Linux).
param(
    [Parameter(Mandatory = $true)]
    [string]$ZipPath,
    [switch]$RequireSpa = $true
)

$ErrorActionPreference = "Stop"

function Normalize-ZipEntryPath {
    param([Parameter(Mandatory = $true)][string]$Name)
    # Independiente del SO que creo el zip: unificar a slash POSIX.
    $n = ($Name -replace '\\', '/')
    while ($n.StartsWith('./')) { $n = $n.Substring(2) }
    return $n.TrimStart('/')
}

if (-not (Test-Path -LiteralPath $ZipPath)) {
    throw "No existe el zip: $ZipPath"
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead((Resolve-Path -LiteralPath $ZipPath).Path)
try {
    $names = @(
        $zip.Entries | ForEach-Object { Normalize-ZipEntryPath -Name $_.FullName }
    )
}
finally {
    $zip.Dispose()
}

$spaIndex = $names -contains "app/static/operator-ui/index.html"
$appMain = $names -contains "app/main.py"
$spaAssets = @(
    $names | Where-Object {
        $_ -like "app/static/operator-ui/assets/*" -and -not $_.EndsWith("/")
    }
).Count

Write-Host ("SPA_INDEX={0}" -f $spaIndex.ToString().ToLowerInvariant())
Write-Host ("APP_MAIN={0}" -f $appMain.ToString().ToLowerInvariant())
Write-Host ("SPA_ASSETS={0}" -f $spaAssets)
Write-Host ("ENTRY_COUNT={0}" -f $names.Count)

$ok = $true
if (-not $appMain) {
    Write-Host "ERROR: falta app/main.py en el zip"
    $ok = $false
}
if ($RequireSpa) {
    if (-not $spaIndex) {
        Write-Host "ERROR: falta app/static/operator-ui/index.html en el zip"
        $ok = $false
    }
    if ($spaAssets -le 0) {
        Write-Host "ERROR: SPA_ASSETS debe ser > 0"
        $ok = $false
    }
}

if (-not $ok) {
    exit 1
}

Write-Host "==> Validacion ZIP OK (paths normalizados a /)"
exit 0
