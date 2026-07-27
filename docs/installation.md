# Installation

Harako-RNAseq runs as a local Docker application. The supported public path
does not require a native Python, R, Snakemake, Salmon, or fastp installation.

## Prerequisites

- Git.
- Docker with a running Linux container engine.
- [just](https://github.com/casey/just).
- A browser that can reach `http://127.0.0.1:8501`.

The current container is `linux/amd64`. Windows with Docker Desktop and
Ubuntu/Linux with Docker are verified. macOS Intel and Apple Silicon have not
yet been verified for this release. See the [support matrix](support-matrix.md).

Harako-RNAseq does not yet publish a prebuilt public image. The first local
build can take substantial time because R and Bioconductor packages are
installed. Later builds normally reuse Docker's build cache.

## Windows PowerShell

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

## Ubuntu and Linux

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

## macOS

The repository provides the same `just app` entry point, but macOS Intel and
Apple Silicon are not yet verified release environments. The downloaded
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
