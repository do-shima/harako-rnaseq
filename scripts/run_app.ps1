param(
    [Parameter(Mandatory = $true)][string]$Repo,
    [Parameter(Mandatory = $true)][string]$Image,
    [ValidateSet("release", "source", "source_overlay")][string]$Mode = "source",
    [ValidateRange(1, 65535)][int]$Port = 8501,
    [string]$ContainerName = "",
    [string]$ReleaseTag = "",
    [string]$DependencyFiles = ""
)

$ErrorActionPreference = "Stop"

$ctx = (docker context show).Trim()
if ($ctx -ne "default") {
    Write-Warning ("docker context is " + $ctx + " (expected default). Use: docker context use default")
}

$repoAbs = [System.IO.Path]::GetFullPath($Repo)

if ($Mode -eq "source_overlay") {
    if ([string]::IsNullOrWhiteSpace($ReleaseTag) -or [string]::IsNullOrWhiteSpace($DependencyFiles)) {
        throw "source_overlay requires ReleaseTag and DependencyFiles from the launcher."
    }
    & git -C $repoAbs rev-parse --verify ($ReleaseTag + "^{commit}") *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Release tag $ReleaseTag is unavailable. Run: git fetch --tags origin"
    }
    $dependencyPaths = $DependencyFiles.Split(
        [char[]]@(" ", "`t", "`r", "`n"),
        [System.StringSplitOptions]::RemoveEmptyEntries
    )
    & git -C $repoAbs diff --quiet $ReleaseTag -- @dependencyPaths
    if ($LASTEXITCODE -ne 0) {
        throw "Runtime dependency files differ from $ReleaseTag. Use just app-build."
    }
}

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
Write-Host ("launch_mode=" + $Mode + " image=" + $Image)
Write-Host ("Starting UI... open http://127.0.0.1:" + $Port)

$runArgs = @(
    "run", "--rm"
)
if (![string]::IsNullOrWhiteSpace($ContainerName)) {
    $runArgs += @("--name", $ContainerName)
}
$runArgs += @(
    "-p", ("127.0.0.1:" + $Port + ":8501"),
    "-e", ("HOST_INPUT=" + $input),
    "-e", ("HOST_OUT=" + $out),
    "-e", "PYTHONPATH=/app",
    "-w", "/app",
    "--mount", ("type=bind,src=" + $input + ",target=/input,readonly"),
    "--mount", ("type=bind,src=" + $out + ",target=/output")
)
if ($Mode -ne "release") {
    $runArgs += @("--mount", ("type=bind,src=" + $repoAbs + ",target=/app"))
}
$runArgs += @(
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
