# Empaqueta la API para Zip Deploy en Azure App Service (sin build de Oryx).
param(
    [string]$AppRoot = (Join-Path $PSScriptRoot ".."),
    [string]$EnvSource = (Join-Path $PSScriptRoot "..\..\api-hbi-powerAutomate.env"),
    [string]$ZipPath = (Join-Path $PSScriptRoot "..\..\azure-deploy.zip")
)

$ErrorActionPreference = "Stop"

$AppRoot = (Resolve-Path $AppRoot).Path
$ZipPath = [System.IO.Path]::GetFullPath($ZipPath)

if (-not (Test-Path $EnvSource)) {
    throw "No se encontro archivo de entorno: $EnvSource"
}

$staging = Join-Path $env:TEMP ("hbiauto-deploy-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $staging | Out-Null

try {
    $rootFiles = @(
        "application.py", "requirements.txt", "run.sh", "startup.sh", "startup.txt",
        ".deployment", "Procfile", "gunicorn.conf.py", "runtime.txt"
    )
    foreach ($name in $rootFiles) {
        $src = Join-Path $AppRoot $name
        if (-not (Test-Path $src)) {
            throw "Falta archivo requerido: $src"
        }
        Copy-Item -Path $src -Destination (Join-Path $staging $name)
    }

    Copy-Item -Path $EnvSource -Destination (Join-Path $staging ".env")

    $appSrc = Join-Path $AppRoot "app"
    if (-not (Test-Path $appSrc)) {
        throw "Falta paquete Python: $appSrc"
    }
    $appDest = Join-Path $staging "app"
    robocopy $appSrc $appDest /E /XD __pycache__ .pytest_cache /XF *.pyc /NFL /NDL /NJH /NJS /NC /NS | Out-Null
    if (-not (Test-Path (Join-Path $appDest "main.py"))) {
        throw "Paquete app/ invalido: falta app/main.py en staging"
    }

    # Azure ejecuta los scripts en Linux: los finales de linea CRLF rompen el shebang.
    foreach ($sh in @("run.sh", "startup.sh")) {
        $shPath = Join-Path $staging $sh
        $shText = (Get-Content -Raw $shPath) -replace "`r`n", "`n"
        [System.IO.File]::WriteAllText($shPath, $shText, (New-Object System.Text.UTF8Encoding $false))
    }

    if (Test-Path $ZipPath) {
        Remove-Item -Force $ZipPath
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory($staging, $ZipPath)

    Write-Host "==> Paquete creado: $ZipPath"
    Write-Host "==> Incluye .env (runtime). No commitear el zip ni secretos."
}
finally {
    if (Test-Path $staging) {
        Remove-Item -Recurse -Force $staging
    }
}
