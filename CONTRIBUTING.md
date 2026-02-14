# Contributing

## Local Commands (PowerShell)

- Build image if missing:
```powershell
just build-if-needed-ps
```
- UI launch (copy/paste):
```powershell
just app-ps
```
- UI launch with explicit mounts:
```powershell
$env:INPUT="D:\path\to\input"; $env:OUT="D:\path\to\out"; just app-ps
```
- Manual tests without host Python (Docker temporary pytest):
```powershell
just test-docker
```

## Local Commands (Linux/Mac)

- UI launch in one command:
```bash
just app
```
- `INPUT`/`OUT` are optional for `just app`.
- If omitted, defaults are repo-local `./input` and `./output` (auto-created).

## app-ps Policy

- `app-ps` supports both modes:
- explicit `INPUT`/`OUT` when you need fixed host paths.
- implicit defaults (`<repo>/input`, `<repo>/output`) when unset.
- The wrapper script is `scripts/run_app.ps1` to avoid inline quoting issues in `justfile`.
