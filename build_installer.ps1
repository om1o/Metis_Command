<#
.SYNOPSIS
    Builds the Metis Command executable and installer.

.DESCRIPTION
    This script runs PyInstaller to build dist\Metis.exe from metis.spec.
    It then attempts to locate the Inno Setup Compiler (iscc.exe) to build the Windows installer.
#>

$ErrorActionPreference = "Stop"

Write-Host "Building Metis.exe with PyInstaller..." -ForegroundColor Cyan
if (Get-Command "pyinstaller" -ErrorAction SilentlyContinue) {
    pyinstaller metis.spec --clean
} elseif (Get-Command "py" -ErrorAction SilentlyContinue) {
    py -m PyInstaller metis.spec --clean
} else {
    python -m PyInstaller metis.spec --clean
}

if (-Not (Test-Path "dist\Metis.exe")) {
    Write-Error "Failed to build dist\Metis.exe"
    exit 1
}

Write-Host "Metis.exe successfully built." -ForegroundColor Green

Write-Host "Looking for Inno Setup Compiler (iscc)..." -ForegroundColor Cyan
$isccPaths = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
    "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 5\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 5\ISCC.exe"
)

$iscc = $null
foreach ($path in $isccPaths) {
    if (Test-Path $path) {
        $iscc = $path
        break
    }
}

if ($iscc) {
    $ver = "0.16.4"
    if (Test-Path "metis_version.py") {
        $raw = Get-Content "metis_version.py" -Raw
        if ($raw -match 'METIS_VERSION\s*=\s*["'']([0-9.]+)["'']') {
            $ver = $Matches[1]
        }
    }
    Write-Host "Found Inno Setup at $iscc" -ForegroundColor Green
    Write-Host "Inno app version: $ver (from metis_version.py)" -ForegroundColor DarkGray
    Write-Host "Building Installer (dist\Metis_Command_Setup.exe)..." -ForegroundColor Cyan
    & $iscc "/DMyAppVersion=$ver" "metis_installer.iss"
    Write-Host "Installer built successfully! Check the 'dist' directory." -ForegroundColor Green
} else {
    Write-Host "Inno Setup Compiler not found." -ForegroundColor Yellow
    Write-Host "To generate the Metis_Command_Setup.exe installer, please install Inno Setup 6 from https://jrsoftware.org/isinfo.php"
    Write-Host "Once installed, you can run this script again or double-click metis_installer.iss to compile it manually."
}
