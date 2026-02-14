param(
    [Parameter(Mandatory = $true)][string]$Repo,
    [Parameter(Mandatory = $true)][string]$Image
)

$ErrorActionPreference = "Stop"

$ctx = (docker context show).Trim()
if ($ctx -ne "default") {
    Write-Warning ("docker context is " + $ctx + " (expected default). Use: docker context use default")
}

$repoAbs = [System.IO.Path]::GetFullPath($Repo)
$input = $env:INPUT
$out = $env:OUT

if ([string]::IsNullOrWhiteSpace($input)) {
    $input = Join-Path $repoAbs "input"
}
if ([string]::IsNullOrWhiteSpace($out)) {
    $out = Join-Path $repoAbs "output"
}

if (!(Test-Path $input)) {
    New-Item -ItemType Directory -Force -Path $input | Out-Null
}
if (!(Test-Path $out)) {
    New-Item -ItemType Directory -Force -Path $out | Out-Null
}

Write-Host ("HOST_INPUT=" + $input)
Write-Host ("HOST_OUT=" + $out)
Write-Host "Starting UI... open http://127.0.0.1:8501"

$runArgs = @(
    "run", "--rm",
    "-p", "127.0.0.1:8501:8501",
    "-e", ("HOST_INPUT=" + $input),
    "-e", ("HOST_OUT=" + $out),
    "-e", "PYTHONPATH=/app",
    "-w", "/app",
    "--mount", ("type=bind,src=" + $repoAbs + ",target=/app"),
    "--mount", ("type=bind,src=" + $input + ",target=/input,readonly"),
    "--mount", ("type=bind,src=" + $out + ",target=/output"),
    $Image,
    "streamlit",
    "run",
    "app/ui/app_ui.py",
    "--server.address", "0.0.0.0",
    "--server.port", "8501",
    "--server.headless", "true",
    "--browser.gatherUsageStats", "false",
    "--logger.level=warning"
)

& docker @runArgs 2>&1 | ForEach-Object {
    $line = $_.ToString()
    if (
        $line -notmatch "You can now view your Streamlit app in your browser\." -and
        $line -notmatch "^\s*(URL:|Local URL:|Network URL:|External URL:)"
    ) {
        $line
    }
}
exit $LASTEXITCODE
