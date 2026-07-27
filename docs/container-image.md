# Container image

Harako-RNAseq currently supports a local source build:

```bash
just build
```

The release workflow is prepared to publish a `linux/amd64` image after the
repository is public and a release tag passes every gate. No public prebuilt
image is claimed until that workflow succeeds and GHCR package visibility is
confirmed as public.

## Planned beta references

For v0.2.0-beta.1 the planned references are:

- `ghcr.io/do-shima/harako-rnaseq:v0.2.0-beta.1`
- `ghcr.io/do-shima/harako-rnaseq:beta`

The exact tag is preferred for reproducibility. `beta` is a moving prerelease
channel. A prerelease never receives `latest`.

After publication:

```bash
docker pull ghcr.io/do-shima/harako-rnaseq:v0.2.0-beta.1
IMAGE=ghcr.io/do-shima/harako-rnaseq:v0.2.0-beta.1 just app
```

PowerShell:

```powershell
docker pull ghcr.io/do-shima/harako-rnaseq:v0.2.0-beta.1
$env:IMAGE = "ghcr.io/do-shima/harako-rnaseq:v0.2.0-beta.1"
just app-ps
```

## Architecture

The image and downloaded fastp and Salmon binaries target `linux/amd64`.
There is no arm64 manifest and native Apple Silicon support is not claimed.

## Metadata and notices

OCI labels record source, revision, version, creation time, documentation,
title, and description. The image intentionally has no single license label
for all contents. PolyForm Noncommercial covers Harako source; bundled
components retain their own licenses.

Notices are installed under `/usr/share/licenses/harako-rnaseq/`. The exact
Salmon 1.10.0 corresponding source archive is installed at
`/usr/src/salmon-1.10.0.tar.gz`.

## Verification after publication

```bash
docker buildx imagetools inspect \
  ghcr.io/do-shima/harako-rnaseq:v0.2.0-beta.1
docker inspect ghcr.io/do-shima/harako-rnaseq:v0.2.0-beta.1
```

GitHub artifact attestation and BuildKit provenance are separate records.
Verify the attestation against the digest and inspect the attached SBOM with
an OCI-capable tool. Automated SBOM license detection is an inventory aid,
not a legal conclusion.

