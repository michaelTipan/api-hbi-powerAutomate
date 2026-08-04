# Valida el zip de Azure Deploy. Normaliza siempre paths a "/" (Windows/Linux).
param(
    [Parameter(Mandatory = $true)]
    [string]$ZipPath,
    [switch]$RequireSpa = $true,
    # App Service Linux con Oryx build OFF: sin site-packages el worker no arranca.
    [switch]$RequirePythonPackages = $true
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
    $rawNames = @($zip.Entries | ForEach-Object { $_.FullName })
    $names = @($rawNames | ForEach-Object { Normalize-ZipEntryPath -Name $_ })
}
finally {
    $zip.Dispose()
}

$ok = $true

$backslashRaw = @($rawNames | Where-Object { $_ -like '*\*' })
if ($backslashRaw.Count -gt 0) {
    $sample = ($backslashRaw | Select-Object -First 5) -join ', '
    Write-Host ("ERROR: entradas con backslash: {0}" -f $sample)
    $ok = $false
}

$absolute = @($names | Where-Object { $_ -match '^[A-Za-z]:/' -or $_.StartsWith('/') })
if ($absolute.Count -gt 0) {
    Write-Host "ERROR: entradas absolutas detectadas"
    $ok = $false
}

$dotdot = @($names | Where-Object { $_ -match '(^|/)\.\.(/|$)' })
if ($dotdot.Count -gt 0) {
    Write-Host "ERROR: entradas con '..' detectadas"
    $ok = $false
}

$bannedPrefixes = @(
    'node_modules/',
    '.git/',
    '_work/',
    'linux-site-packages.zip',
    'site-packages-unix.zip'
)
foreach ($b in $bannedPrefixes) {
    $seg = $b.TrimEnd('/')
    $hit = @($names | Where-Object {
            $_ -eq $seg -or
            $_.StartsWith("$seg/") -or
            ($_ -like ("*/{0}" -f $seg)) -or
            ($_ -like ("*/{0}/*" -f $seg))
        })
    if ($hit.Count -gt 0) {
        Write-Host ("ERROR: entrada prohibida relacionada con {0} ejemplo={1}" -f $b, $hit[0])
        $ok = $false
    }
}
$secretHits = @($names | Where-Object {
        $_ -like '*.PublishSettings' -or
        $_ -eq 'credentials.json' -or
        $_ -like '*/credentials.json' -or
        ($_ -like '*.pfx') -or
        ($_ -eq 'id_rsa' -or $_ -like '*/id_rsa')
    })
if ($secretHits.Count -gt 0) {
    Write-Host ("ERROR: credenciales/PublishSettings en zip: {0}" -f $secretHits[0])
    $ok = $false
}

$required = @(
    'application.py',
    'app/main.py',
    '.env',
    'requirements.txt',
    '.deployment',
    'startup.sh'
)
foreach ($req in $required) {
    if ($names -notcontains $req) {
        Write-Host ("ERROR: falta {0} en el zip" -f $req)
        $ok = $false
    }
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

if ($RequirePythonPackages) {
    # application.py añade esta ruta a sys.path; sin ella → ModuleNotFoundError: fastapi.
    $fastapiMarkers = @(
        "fastapi/__init__.py",
        ".python_packages/lib/site-packages/fastapi/__init__.py"
    )
    $hasFastapi = $false
    foreach ($m in $fastapiMarkers) {
        if ($names -contains $m) { $hasFastapi = $true; break }
    }
    if (-not $hasFastapi) {
        # Algunas layouts empaquetan el módulo como directorio con solo .dist-info + py.
        $hasFastapi = @($names | Where-Object {
                $_ -like ".python_packages/lib/site-packages/fastapi/*"
            }).Count -gt 0
    }
    $pkgRoot = @($names | Where-Object {
            $_ -like ".python_packages/lib/site-packages/*"
        }).Count
    Write-Host ("PYTHON_PACKAGES_ENTRIES={0}" -f $pkgRoot)
    Write-Host ("FASTAPI_IN_ZIP={0}" -f $hasFastapi.ToString().ToLowerInvariant())
    if ($pkgRoot -lt 50 -or -not $hasFastapi) {
        Write-Host "ERROR: faltan deps Linux en .python_packages (fastapi). Ver DEPLOY_CONTEXT.md"
        Write-Host "  Usa: build-u4-rc-sandbox-ui-package.ps1 o -PythonPackagesSource linux-site-packages"
        $ok = $false
    }
}

if (-not $ok) {
    exit 1
}

Write-Host "==> Validacion ZIP OK (paths normalizados a /)"
exit 0
