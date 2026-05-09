param(
    [int]$Port = 3000,
    [switch]$Check,
    [switch]$Install,
    [switch]$StopForeign
)

$ErrorActionPreference = "Stop"

$ScriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptPath
$DesktopUi = Join-Path $Root "desktop-ui"

function Resolve-NormalizedPath {
    param([string]$Path)
    return [System.IO.Path]::GetFullPath($Path).TrimEnd("\").ToLowerInvariant()
}

function Get-DesktopUiListener {
    param([int]$ListenPort)

    $connections = @(Get-NetTCPConnection -LocalPort $ListenPort -State Listen -ErrorAction SilentlyContinue)
    foreach ($connection in $connections) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($connection.OwningProcess)" -ErrorAction SilentlyContinue
        if ($null -ne $process) {
            [pscustomobject]@{
                ProcessId = $connection.OwningProcess
                CommandLine = [string]$process.CommandLine
                ExecutablePath = [string]$process.ExecutablePath
            }
        }
    }
}

if (-not (Test-Path (Join-Path $DesktopUi "package.json"))) {
    throw "desktop-ui/package.json was not found. Run this script from the Metis repo checkout."
}

$expected = Resolve-NormalizedPath $DesktopUi
$listeners = @(Get-DesktopUiListener -ListenPort $Port)

foreach ($listener in $listeners) {
    $command = $listener.CommandLine.ToLowerInvariant()
    $isExpected = $command.Contains($expected)

    if (-not $isExpected) {
        $message = "Port $Port is already owned by PID $($listener.ProcessId), but it is not serving from $DesktopUi.`nCommand: $($listener.CommandLine)"
        if ($StopForeign) {
            Write-Warning $message
            Stop-Process -Id $listener.ProcessId -Force
            Write-Host "Stopped foreign desktop UI server on port $Port."
        } else {
            throw "$message`nStop it first, or rerun with -StopForeign if you intentionally want this script to stop that process."
        }
    } elseif ($Check) {
        Write-Host "OK: port $Port is already serving from $DesktopUi."
        exit 0
    } else {
        Write-Host "Desktop UI dev server is already running from $DesktopUi on http://127.0.0.1:$Port/."
        exit 0
    }
}

if ($Check) {
    Write-Host "OK: port $Port is free. Canonical desktop UI path: $DesktopUi"
    exit 0
}

Push-Location $DesktopUi
try {
    if ($Install -or -not (Test-Path "node_modules")) {
        npm ci --no-audit --no-fund
    }

    Write-Host "Starting Metis desktop UI from $DesktopUi"
    Write-Host "URL: http://127.0.0.1:$Port/"
    npm run dev -- --hostname 127.0.0.1 --port $Port
} finally {
    Pop-Location
}
