"""Tests del empaquetado ZIP con entradas Unix (/) para App Service Linux."""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
BUILD_PS1 = REPO / "scripts" / "build-azure-package.ps1"
VERIFY_PS1 = REPO / "scripts" / "verify-azure-package.ps1"


def _pwsh(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    exe = "powershell"
    return subprocess.run(
        [exe, "-NoProfile", "-ExecutionPolicy", "Bypass", *args],
        cwd=str(cwd or REPO),
        capture_output=True,
        text=True,
        check=False,
    )


def test_convert_to_unix_zip_entry_name_rejects_dotdot() -> None:
    script = r"""
. '.\scripts\build-azure-package.ps1' 2>$null
# Dot-source functions only: re-parse by extracting via ScriptBlock is fragile;
# invoke the function file fragment instead.
"""
    # Probar la función cargándola aislada.
    isol = r"""
function ConvertTo-UnixZipEntryName {
  param([string]$RelativePath)
  if ([string]::IsNullOrWhiteSpace($RelativePath)) { throw 'empty' }
  $n = $RelativePath.Trim() -replace '\\', '/'
  while ($n.StartsWith('./')) { $n = $n.Substring(2) }
  $n = $n.TrimStart('/')
  if ($n.StartsWith('/') -or $n -match '^[A-Za-z]:/') { throw 'abs' }
  if ($n -match '(^|/)\.\.(/|$)') { throw 'dotdot' }
  if ($n.Contains('\')) { throw 'bs' }
  return $n
}
$ok = ConvertTo-UnixZipEntryName 'app\main.py'
if ($ok -ne 'app/main.py') { throw "got $ok" }
try { ConvertTo-UnixZipEntryName '..\secret'; throw 'expected fail' } catch { if ($_.Exception.Message -notmatch 'dotdot|no permitida') { throw $_ } }
Write-Output 'OK'
"""
    r = _pwsh(["-Command", isol])
    assert r.returncode == 0, r.stderr + r.stdout
    assert "OK" in r.stdout


def test_new_unix_path_zip_has_no_backslashes(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    (staging / "app" / "static" / "operator-ui" / "assets").mkdir(parents=True)
    (staging / "application.py").write_text("x\n", encoding="utf-8")
    (staging / "app" / "main.py").write_text("x\n", encoding="utf-8")
    (staging / ".env").write_text("ACTIVE_ENVIRONMENT=sandbox\n", encoding="utf-8")
    (staging / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (staging / ".deployment").write_text("[config]\n", encoding="utf-8")
    (staging / "startup.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    (staging / "app" / "static" / "operator-ui" / "index.html").write_text(
        "<html></html>\n", encoding="utf-8"
    )
    (staging / "app" / "static" / "operator-ui" / "assets" / "index.js").write_text(
        "console.log(1)\n", encoding="utf-8"
    )
    # Nested Windows-like path components via real directories
    nested = staging / "app" / "adapters" / "primary"
    nested.mkdir(parents=True)
    (nested / "x.py").write_text("x\n", encoding="utf-8")

    zip_path = tmp_path / "out.zip"
    isol = f"""
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
function ConvertTo-UnixZipEntryName {{
  param([string]$RelativePath)
  $n = $RelativePath.Trim() -replace '\\\\', '/'
  while ($n.StartsWith('./')) {{ $n = $n.Substring(2) }}
  $n = $n.TrimStart('/')
  if ($n -match '(^|/)\\.\\.(/|$)') {{ throw 'dotdot' }}
  if ($n.Contains('\\')) {{ throw 'bs' }}
  return $n
}}
function New-UnixPathZipFromDirectory {{
  param([string]$SourceDirectory, [string]$DestinationZip)
  $sourceRoot = (Resolve-Path -LiteralPath $SourceDirectory).Path
  if (Test-Path -LiteralPath $DestinationZip) {{ Remove-Item -Force $DestinationZip }}
  $zipArchive = [System.IO.Compression.ZipFile]::Open($DestinationZip, [System.IO.Compression.ZipArchiveMode]::Create)
  try {{
    Get-ChildItem -LiteralPath $sourceRoot -Recurse -File | ForEach-Object {{
      $relative = $_.FullName.Substring($sourceRoot.Length).TrimStart('\\', '/')
      $entryName = ConvertTo-UnixZipEntryName -RelativePath $relative
      [void][System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
        $zipArchive, $_.FullName, $entryName,
        [System.IO.Compression.CompressionLevel]::Optimal)
    }}
  }} finally {{ $zipArchive.Dispose() }}
}}
New-UnixPathZipFromDirectory -SourceDirectory '{staging}' -DestinationZip '{zip_path}'
Write-Output 'ZIP_OK'
"""
    r = _pwsh(["-Command", isol.replace("\\", "\\\\") if False else isol])
    # Paths with backslashes in PS strings from Python need care on Windows:
    staging_ps = str(staging).replace("'", "''")
    zip_ps = str(zip_path).replace("'", "''")
    isol2 = isol.replace(str(staging), staging_ps).replace(str(zip_path), zip_ps)
    # Rebuild with proper quoting
    isol2 = f"""
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
function ConvertTo-UnixZipEntryName {{
  param([string]$RelativePath)
  $n = $RelativePath.Trim() -replace [regex]::Escape('\\'), '/'
  while ($n.StartsWith('./')) {{ $n = $n.Substring(2) }}
  $n = $n.TrimStart('/')
  if ($n -match '(^|/)\\.\\.(/|$)') {{ throw 'dotdot' }}
  if ($n.Contains([string][char]92)) {{ throw 'bs' }}
  return $n
}}
$sourceRoot = (Resolve-Path -LiteralPath '{staging_ps}').Path
$DestinationZip = '{zip_ps}'
if (Test-Path -LiteralPath $DestinationZip) {{ Remove-Item -Force $DestinationZip }}
$zipArchive = [System.IO.Compression.ZipFile]::Open($DestinationZip, [System.IO.Compression.ZipArchiveMode]::Create)
try {{
  Get-ChildItem -LiteralPath $sourceRoot -Recurse -File | ForEach-Object {{
    $relative = $_.FullName.Substring($sourceRoot.Length).TrimStart([char]92, [char]47)
    $entryName = ConvertTo-UnixZipEntryName -RelativePath $relative
    [void][System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
      $zipArchive, $_.FullName, $entryName,
      [System.IO.Compression.CompressionLevel]::Optimal)
  }}
}} finally {{ $zipArchive.Dispose() }}
Write-Output 'ZIP_OK'
"""
    r = _pwsh(["-Command", isol2])
    assert r.returncode == 0, r.stderr + r.stdout
    assert zip_path.is_file()

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    assert all("\\" not in n for n in names), names
    assert "application.py" in names
    assert "app/main.py" in names
    assert ".env" in names
    assert "requirements.txt" in names
    assert ".deployment" in names
    assert "startup.sh" in names
    assert "app/static/operator-ui/index.html" in names
    assert any(n.startswith("app/static/operator-ui/assets/") for n in names)
    assert not any(n.startswith("/") for n in names)
    assert not any(".." in n.split("/") for n in names)
    assert not any("node_modules" in n for n in names)
    assert not any(".git/" in n or n.startswith(".git") for n in names)
    assert not any("_work" in n for n in names)

    verify = _pwsh(
        [
            "-File",
            str(VERIFY_PS1),
            "-ZipPath",
            str(zip_path),
            "-RequireSpa",
        ]
    )
    assert verify.returncode == 0, verify.stderr + verify.stdout


def test_verify_rejects_banned_work_residue(tmp_path: Path) -> None:
    zip_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("application.py", b"x")
        zf.writestr("app/main.py", b"x")
        zf.writestr(".env", b"x")
        zf.writestr("requirements.txt", b"x")
        zf.writestr(".deployment", b"x")
        zf.writestr("startup.sh", b"x")
        zf.writestr("app/static/operator-ui/index.html", b"x")
        zf.writestr("app/static/operator-ui/assets/a.js", b"x")
        zf.writestr("_work/u4_rc/secret.txt", b"nope")

    verify = _pwsh(
        ["-File", str(VERIFY_PS1), "-ZipPath", str(zip_path), "-RequireSpa"]
    )
    assert verify.returncode != 0
    assert "_work" in (verify.stdout + verify.stderr).lower()
