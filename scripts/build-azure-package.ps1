# Empaqueta la API para Zip Deploy en Azure App Service (sin build de Oryx).
param(
    [string]$AppRoot = (Join-Path $PSScriptRoot ".."),
    [string]$EnvSource = (Join-Path $PSScriptRoot "..\..\api-hbi-powerAutomate.env"),
    [string]$ZipPath = (Join-Path $PSScriptRoot "..\..\azure-deploy.zip"),
    [switch]$SkipZipValidation
)

$ErrorActionPreference = "Stop"

function Assert-RobocopySuccess {
    # Robocopy: 0-7 = exito; >=8 = error.
    param([string]$Context)
    $code = $LASTEXITCODE
    if ($code -ge 8) {
        throw "robocopy fallo ($Context) con codigo $code"
    }
}

$AppRoot = (Resolve-Path $AppRoot).Path
$ZipPath = [System.IO.Path]::GetFullPath($ZipPath)

if (-not (Test-Path $EnvSource)) {
    throw "No se encontro archivo de entorno: $EnvSource"
}

$activeEnv = $null
foreach ($raw in Get-Content -LiteralPath $EnvSource -Encoding UTF8) {
    if ($raw -match '^\s*ACTIVE_ENVIRONMENT\s*=\s*(.+)\s*$') {
        $activeEnv = $Matches[1].Trim()
        break
    }
}
if ($activeEnv) {
    Write-Host "==> Empaquetando con ACTIVE_ENVIRONMENT=$activeEnv"
} else {
    Write-Host "==> AVISO: ACTIVE_ENVIRONMENT no esta definido en $EnvSource"
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
    robocopy $appSrc $appDest /E /XD __pycache__ .pytest_cache static /XF *.pyc /NFL /NDL /NJH /NJS /NC /NS | Out-Null
    Assert-RobocopySuccess -Context "app/"
    if (-not (Test-Path (Join-Path $appDest "main.py"))) {
        throw "Paquete app/ invalido: falta app/main.py en staging"
    }

    # SPA operador: build en staging (no escribe frontend/dist en el arbol versionado).
    $frontendSrc = Join-Path $AppRoot "frontend"
    if (Test-Path (Join-Path $frontendSrc "package.json")) {
        Write-Host "==> Building Operator SPA (npm ci + npm run build)"
        $frontendBuild = Join-Path $staging "_frontend-build"
        New-Item -ItemType Directory -Path $frontendBuild | Out-Null
        robocopy $frontendSrc $frontendBuild /E /XD node_modules dist /NFL /NDL /NJH /NJS /NC /NS | Out-Null
        Assert-RobocopySuccess -Context "frontend staging"
        Push-Location $frontendBuild
        try {
            npm ci
            if ($LASTEXITCODE -ne 0) { throw "npm ci failed with exit $LASTEXITCODE" }
            npm run build
            if ($LASTEXITCODE -ne 0) { throw "npm run build failed with exit $LASTEXITCODE" }
        }
        finally {
            Pop-Location
        }
        $builtDist = Join-Path $frontendBuild "dist"
        if (-not (Test-Path (Join-Path $builtDist "index.html"))) {
            throw "SPA build sin index.html en $builtDist"
        }
        $uiStaticDest = Join-Path $appDest "static\operator-ui"
        New-Item -ItemType Directory -Path $uiStaticDest -Force | Out-Null
        robocopy $builtDist $uiStaticDest /E /NFL /NDL /NJH /NJS /NC /NS | Out-Null
        Assert-RobocopySuccess -Context "SPA static"
        Write-Host "==> SPA copiada a staging app/static/operator-ui"
        Remove-Item -Recurse -Force $frontendBuild
    }
    else {
        Write-Host "==> AVISO: no hay frontend/; el zip no incluira SPA bajo /app"
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

    if (-not $SkipZipValidation) {
        $verify = Join-Path $PSScriptRoot "verify-azure-package.ps1"
        & $verify -ZipPath $ZipPath -RequireSpa
        if ($LASTEXITCODE -ne 0) {
            throw "verify-azure-package.ps1 fallo con codigo $LASTEXITCODE"
        }
    }
}
finally {
    if (Test-Path $staging) {
        Remove-Item -Recurse -Force $staging
    }
}

# Evitar que un codigo residual de robocopy (1-7) marque fallo al caller.
exit 0
