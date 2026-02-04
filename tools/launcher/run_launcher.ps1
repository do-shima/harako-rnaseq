$ErrorActionPreference = "Stop"

function Resolve-PythonCommand {
    if ($env:CONDA_PREFIX) {
        $condaPython = Join-Path $env:CONDA_PREFIX "python.exe"
        if (Test-Path -LiteralPath $condaPython) {
            return @{ Exe = $condaPython; Args = @() }
        }
    }

    $homeAnaconda = Join-Path $HOME "anaconda3\python.exe"
    if (Test-Path -LiteralPath $homeAnaconda) {
        return @{ Exe = $homeAnaconda; Args = @() }
    }

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        return @{ Exe = "py"; Args = @("-3") }
    }

    $pythonCandidates = @()
    try {
        $pythonCandidates = @(where.exe python 2>$null) | Where-Object {
            $_ -and ($_ -notmatch "WindowsApps[\\/]+python(\.exe)?$")
        }
    } catch {
        $pythonCandidates = @()
    }
    if ($pythonCandidates.Count -gt 0) {
        return @{ Exe = $pythonCandidates[0]; Args = @() }
    }

    return $null
}

$launcherScript = Join-Path $PSScriptRoot "rnaseq_launcher.py"
if (-not (Test-Path -LiteralPath $launcherScript)) {
    Write-Error "Launcher script not found: $launcherScript"
    exit 2
}

$pythonCmd = Resolve-PythonCommand
if (-not $pythonCmd) {
    Write-Host ""
    Write-Host "Python could not be found (or only WindowsApps alias was found)." -ForegroundColor Yellow
    Write-Host "Fallback options:" -ForegroundColor Yellow
    Write-Host "  1) just launcher-web   # Streamlit launcher at http://127.0.0.1:8601"
    Write-Host "  2) Set INPUT/OUT and run just ui"
    Write-Host ""
    exit 2
}

& $pythonCmd.Exe @($pythonCmd.Args + @($launcherScript))
exit $LASTEXITCODE
