# Empaqueta la API para Zip Deploy en Azure App Service (sin build de Oryx).
param(
    [string]$AppRoot = (Join-Path $PSScriptRoot ".."),
    [string]$EnvSource = (Join-Path $PSScriptRoot "..\..\api-hbi-powerAutomate.env"),
    [string]$ZipPath = (Join-Path $PSScriptRoot "..\..\azure-deploy.zip"),
    [string]$PythonPackagesSource = "",
    [string]$BuildId = "",
    [switch]$SkipZipValidation,
    [switch]$SkipFrontendBuild,
    [switch]$EnforceSandboxUi,
    # Solo para emergencias documentadas. Por defecto el ZIP debe llevar deps Linux.
    [switch]$AllowNoPythonPackages
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

function ConvertTo-UnixZipEntryName {
    <#
    .SYNOPSIS
      Normaliza una ruta relativa a entrada ZIP compatible con App Service Linux.
    .DESCRIPTION
      OneDeploy/rsync falla si las entradas usan "\". Siempre devolver "/".
      Rechaza absolutas, ".." y vacias.
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$RelativePath
    )
    if ([string]::IsNullOrWhiteSpace($RelativePath)) {
        throw "Nombre de entrada ZIP vacio"
    }
    $n = $RelativePath.Trim() -replace '\\', '/'
    while ($n.StartsWith('./')) { $n = $n.Substring(2) }
    $n = $n.TrimStart('/')
    if ($n.StartsWith('/') -or $n -match '^[A-Za-z]:/') {
        throw "Entrada ZIP absoluta no permitida: $RelativePath"
    }
    if ($n -match '(^|/)\.\.(/|$)') {
        throw "Entrada ZIP con '..' no permitida: $RelativePath"
    }
    if ($n.Contains('\')) {
        throw "Entrada ZIP con backslash residual: $n"
    }
    return $n
}

function New-UnixPathZipFromDirectory {
    <#
    .SYNOPSIS
      Crea un ZIP cuyas entradas usan siempre separador "/".
    #>
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceDirectory,
        [Parameter(Mandatory = $true)]
        [string]$DestinationZip
    )
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem

    $sourceRoot = (Resolve-Path -LiteralPath $SourceDirectory).Path
    $destDir = Split-Path -Parent $DestinationZip
    if ($destDir -and -not (Test-Path -LiteralPath $destDir)) {
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    }
    if (Test-Path -LiteralPath $DestinationZip) {
        Remove-Item -Force -LiteralPath $DestinationZip
    }

    $zipArchive = [System.IO.Compression.ZipFile]::Open(
        $DestinationZip,
        [System.IO.Compression.ZipArchiveMode]::Create
    )
    try {
        Get-ChildItem -LiteralPath $sourceRoot -Recurse -File | ForEach-Object {
            $relative = $_.FullName.Substring($sourceRoot.Length).TrimStart('\', '/')
            $entryName = ConvertTo-UnixZipEntryName -RelativePath $relative
            [void][System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $zipArchive,
                $_.FullName,
                $entryName,
                [System.IO.Compression.CompressionLevel]::Optimal
            )
        }
    }
    finally {
        $zipArchive.Dispose()
    }
}

function Assert-SandboxUiEnvFile {
    param([Parameter(Mandatory = $true)][string]$EnvPath)
    $map = @{}
    foreach ($raw in Get-Content -LiteralPath $EnvPath -Encoding UTF8) {
        if ($raw -match '^\s*#' -or [string]::IsNullOrWhiteSpace($raw)) { continue }
        $eq = $raw.IndexOf('=')
        if ($eq -lt 1) { continue }
        $map[$raw.Substring(0, $eq).Trim()] = $raw.Substring($eq + 1)
    }
    $active = [string]$map['ACTIVE_ENVIRONMENT']
    if ($active -ne 'sandbox') {
        throw "Paquete sandbox UI requiere ACTIVE_ENVIRONMENT=sandbox (got '$active')"
    }
    $clients = [string]$map['GRAPH_CLIENTS_BASE_PATH']
    if ($clients -notmatch 'PRUEBAS') {
        throw "GRAPH_CLIENTS_BASE_PATH sandbox debe contener PRUEBAS: $clients"
    }
    if ($clients.Trim() -eq 'INFORMACION CREDITOS-CLIENTES') {
        throw "GRAPH_CLIENTS_BASE_PATH no puede ser la raiz productiva"
    }
    $acctHost = [string]$map['GRAPH_ACCOUNTING_SITE_HOSTNAME']
    $acctPath = [string]$map['GRAPH_ACCOUNTING_SITE_PATH']
    if (-not [string]::IsNullOrWhiteSpace($acctHost) -or -not [string]::IsNullOrWhiteSpace($acctPath)) {
        throw "Contabilidad productiva debe estar deshabilitada en paquete sandbox UI"
    }
    if ([string]$map['UI_ENABLED'] -ne 'true') {
        throw "Paquete sandbox UI requiere UI_ENABLED=true"
    }
}

$AppRoot = (Resolve-Path $AppRoot).Path
$ZipPath = [System.IO.Path]::GetFullPath($ZipPath)

if (-not (Test-Path $EnvSource)) {
    throw "No se encontro archivo de entorno: $EnvSource"
}

if ($EnforceSandboxUi) {
    Assert-SandboxUiEnvFile -EnvPath $EnvSource
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

    # Marcador de build determinista para /health (app/build_info.py).
    if (-not $BuildId) {
        Push-Location $AppRoot
        try {
            $short = (git rev-parse --short HEAD 2>$null)
            if (-not $short) { $short = "unknown" }
        }
        finally { Pop-Location }
        $BuildId = "u4-rc-sandbox-ui-$short"
    }
    $commitFull = "unknown"
    Push-Location $AppRoot
    try {
        $got = (git rev-parse HEAD 2>$null)
        if ($got) { $commitFull = [string]$got.Trim() }
    }
    finally { Pop-Location }
    $buildInfo = @(
        '# Generado por build-azure-package.ps1 — no editar a mano en el zip.',
        "BUILD_ID = `"$BuildId`"",
        "COMMIT = `"$commitFull`"",
        'FLAVOR = "sandbox-ui"',
        ''
    ) -join "`n"
    $buildInfoPath = Join-Path $appDest "build_info.py"
    [System.IO.File]::WriteAllText($buildInfoPath, $buildInfo, (New-Object System.Text.UTF8Encoding $false))
    Write-Host "==> build_info.py BUILD_ID=$BuildId"

    # SPA operador: build en staging (no escribe frontend/dist en el arbol versionado).
    $frontendSrc = Join-Path $AppRoot "frontend"
    if (-not $SkipFrontendBuild -and (Test-Path (Join-Path $frontendSrc "package.json"))) {
        Write-Host "==> Building Operator SPA (npm ci + npm run build)"
        $frontendBuild = Join-Path $staging "_frontend-build"
        New-Item -ItemType Directory -Path $frontendBuild | Out-Null
        robocopy $frontendSrc $frontendBuild /E /XD node_modules dist /NFL /NDL /NJH /NJS /NC /NS | Out-Null
        Assert-RobocopySuccess -Context "frontend staging"
        Push-Location $frontendBuild
        try {
            npm ci
            if ($LASTEXITCODE -ne 0) { throw "npm ci failed with exit $LASTEXITCODE" }
            # Fail-closed: la SPA de Azure debe hablar con la API real (login local_session).
            $env:VITE_UI_USE_MOCKS = "false"
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
    elseif ($SkipFrontendBuild -and (Test-Path (Join-Path $AppRoot "frontend\dist\index.html"))) {
        $uiStaticDest = Join-Path $appDest "static\operator-ui"
        New-Item -ItemType Directory -Path $uiStaticDest -Force | Out-Null
        robocopy (Join-Path $AppRoot "frontend\dist") $uiStaticDest /E /NFL /NDL /NJH /NJS /NC /NS | Out-Null
        Assert-RobocopySuccess -Context "SPA static from existing dist"
        Write-Host "==> SPA copiada desde frontend/dist (SkipFrontendBuild)"
    }
    else {
        Write-Host "==> AVISO: no hay frontend/; el zip no incluira SPA bajo /app"
    }

    # Dependencias Linux preconstruidas (obligatorias salvo -AllowNoPythonPackages).
    # Sin ellas App Service (Oryx build OFF) cae en ModuleNotFoundError: fastapi.
    # Ver DEPLOY_CONTEXT.md.
    $defaultPkgs = "D:\CMC\HBI_Capital\_work\u4_rc_reproducible\linux-site-packages"
    if (-not $PythonPackagesSource) {
        if (Test-Path $defaultPkgs) {
            $PythonPackagesSource = $defaultPkgs
            Write-Host "==> PythonPackagesSource por defecto: $PythonPackagesSource"
        }
        elseif (-not $AllowNoPythonPackages) {
            throw @"
Falta -PythonPackagesSource y no existe $defaultPkgs.
Ejecuta .\scripts\build-linux-python-packages.ps1 (Docker) o usa
.\scripts\build-u4-rc-sandbox-ui-package.ps1. Ver DEPLOY_CONTEXT.md.
Para omitir a proposito (no recomendado): -AllowNoPythonPackages
"@
        }
        else {
            Write-Host "==> AVISO: ZIP sin .python_packages (-AllowNoPythonPackages); el worker Linux probablemente no arrancara"
        }
    }
    if ($PythonPackagesSource) {
        if (-not (Test-Path $PythonPackagesSource)) {
            throw "PythonPackagesSource no existe: $PythonPackagesSource"
        }
        $pkgDest = Join-Path $staging ".python_packages\lib\site-packages"
        New-Item -ItemType Directory -Path $pkgDest -Force | Out-Null
        robocopy $PythonPackagesSource $pkgDest /E /XD __pycache__ /XF *.pyc *.pyd /NFL /NDL /NJH /NJS /NC /NS | Out-Null
        Assert-RobocopySuccess -Context "python packages"
        $pyd = @(Get-ChildItem -LiteralPath $pkgDest -Recurse -Filter *.pyd -ErrorAction SilentlyContinue)
        if ($pyd.Count -gt 0) {
            throw "Se detectaron $($pyd.Count) archivos .pyd (Windows) en site-packages; use wheels Linux"
        }
        Write-Host "==> .python_packages incluido desde $PythonPackagesSource"
    }

    # Azure ejecuta los scripts en Linux: los finales de linea CRLF rompen el shebang.
    foreach ($sh in @("run.sh", "startup.sh")) {
        $shPath = Join-Path $staging $sh
        $shText = (Get-Content -Raw $shPath) -replace "`r`n", "`n"
        [System.IO.File]::WriteAllText($shPath, $shText, (New-Object System.Text.UTF8Encoding $false))
    }

    New-UnixPathZipFromDirectory -SourceDirectory $staging -DestinationZip $ZipPath

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
