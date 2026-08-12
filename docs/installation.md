# Installation

Harako-RNAseq runs as a local Docker application. The supported public path
does not require a native Python, R, Snakemake, Salmon, or fastp installation.

## System requirements

### Using the published image

- Docker with a running Linux container engine.
- A browser that can reach `http://127.0.0.1:8501`.
- An amd64-capable environment for the current image.
- Sufficient memory and disk for the image, inputs, references, intermediate
  files, and run outputs.

### Building from source

- Git.
- Docker with a running Linux container engine.
- [just](https://github.com/casey/just).
- The same browser, architecture, memory, and disk requirements as the
  published-image path.

The current container is `linux/amd64`. Windows with Docker Desktop and
Ubuntu/Linux with Docker are verified. Intel-based macOS and Apple Silicon have
not yet been verified for this release. See the
[support matrix](support-matrix.md).

## Published image quickstart

The exact release image is the recommended installation method for most users
and for reproducible research. Input is mounted read-only at `/input`; output
is mounted read-write at `/output`; the UI listens only on
`127.0.0.1:8501`.

Ubuntu/Linux:

```bash
mkdir -p input output
docker pull ghcr.io/do-shima/harako-rnaseq:v0.3.0-beta.1
docker run --rm -p 127.0.0.1:8501:8501 \
  -e PYTHONPATH=/app -e "HOST_INPUT=$(pwd)/input" -e "HOST_OUT=$(pwd)/output" \
  --mount "type=bind,src=$(pwd)/input,dst=/input,readonly" \
  --mount "type=bind,src=$(pwd)/output,dst=/output" \
  ghcr.io/do-shima/harako-rnaseq:v0.3.0-beta.1 \
  streamlit run app/ui/app_ui.py --server.address 0.0.0.0 \
  --server.port 8501 --server.headless true --browser.gatherUsageStats false
```

Windows PowerShell:

```powershell
$InputDir = "D:\rna\input"
$OutputDir = "D:\rna\output"
New-Item -ItemType Directory -Force $InputDir, $OutputDir | Out-Null
docker pull ghcr.io/do-shima/harako-rnaseq:v0.3.0-beta.1
docker run --rm -p 127.0.0.1:8501:8501 `
  -e PYTHONPATH=/app -e "HOST_INPUT=$InputDir" -e "HOST_OUT=$OutputDir" `
  --mount "type=bind,src=$InputDir,dst=/input,readonly" `
  --mount "type=bind,src=$OutputDir,dst=/output" `
  ghcr.io/do-shima/harako-rnaseq:v0.3.0-beta.1 `
  streamlit run app/ui/app_ui.py --server.address 0.0.0.0 `
  --server.port 8501 --server.headless true --browser.gatherUsageStats false
```

Use `ghcr.io/do-shima/harako-rnaseq:beta` only when you intentionally want the
moving beta channel rather than the reproducible version-specific image.

## Source checkout and local build

Use the source path for development or source modification. The first local
build can take substantial time because it installs R and Bioconductor
dependencies; later builds normally reuse Docker's build cache. The launchers
mount the repository over `/app`, so overriding their image variable with a
GHCR reference is not the published-image execution path.

### Windows PowerShell

1. Install and start Docker Desktop using Linux containers.
2. Clone and enter the repository:

   ```powershell
   git clone https://github.com/do-shima/harako-rnaseq.git
   Set-Location harako-rnaseq
   ```

3. Start the application:

   ```powershell
   just app-ps
   ```

PowerShell launcher arguments are environment variables:

```powershell
$env:INPUT="D:\rna\input"
$env:OUT="D:\rna\output"
just app-ps
```

Use PowerShell rather than Git Bash when diagnosing Windows bind-mount path
conversion.

### Ubuntu and Linux

1. Install Docker Engine, ensure the current user can run Docker, and start it.
2. Clone and enter the repository:

   ```bash
   git clone https://github.com/do-shima/harako-rnaseq.git
   cd harako-rnaseq
   ```

3. Start the application:

   ```bash
   just app
   ```

Explicit mounts are optional:

```bash
INPUT=/data/rna/input OUT=/data/rna/output just app
```

### macOS

The repository provides the same `just app` entry point, but Intel-based macOS
and Apple Silicon are not yet verified release environments. The downloaded
Salmon and fastp assets target Linux x86_64, so the image is currently
`linux/amd64`; do not assume native arm64 support.

## Default directories

When `INPUT` and `OUT` are omitted, both launchers use repository-local
`input/` and `output/` directories and create them when necessary. Input is
mounted read-only at `/input`; output is mounted read-write at `/output`.

Use explicit directories for real studies so inputs, reference caches, and
run outputs have predictable storage locations.

## Resources and storage

- Four or more CPU cores are useful for real datasets.
- Allow roughly 8-16 GB RAM for small-to-medium analyses; requirements depend
  on sample count, transcriptome size, and count-matrix dimensions.
- Reserve storage for source FASTQ, uncompressed fastp intermediates, Salmon
  indexes and quantification, reference bundles, and run artifacts.
- Built-in references are large and are cached outside the image.
- Docker itself needs additional space for the approximately 1.2 GB image and
  build layers.

Harako does not automatically remove intermediates. Review run outputs before
manual cleanup.

## Browser and port access

Open `http://127.0.0.1:8501` or `http://localhost:8501`. If port 8501 is in
use, stop the conflicting container or process before relaunching.

For a remote Docker host or VS Code remote session, forward port 8501 to the
local machine and keep access restricted to trusted users. Harako is not a
hosted multi-user service.

## Privacy

The application is intended for local use. Never attach FASTQ files, patient
information, identifiable sample names, credentials, or confidential paths to
public GitHub issues. Follow [SUPPORT.md](../SUPPORT.md) when preparing
sanitized logs or a support bundle.
