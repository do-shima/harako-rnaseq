# Container image

The published `linux/amd64` image is the recommended installation method for
most users:

```bash
docker pull ghcr.io/do-shima/harako-rnaseq:v0.3.0-beta.1
```

Use the direct `docker run` commands in [Installation](installation.md). They
mount input read-only at `/input`, mount output read-write at `/output`, and
bind the Streamlit UI only to `127.0.0.1:8501` without mounting a source
checkout over `/app`.

## Published beta references

The published references are:

- `ghcr.io/do-shima/harako-rnaseq:v0.3.0-beta.1`
- `ghcr.io/do-shima/harako-rnaseq:beta`

The exact tag is preferred for reproducibility. `beta` is a moving prerelease
channel. A prerelease never receives `latest`.

For development or source modification, build and launch from a checkout:

```bash
git clone https://github.com/do-shima/harako-rnaseq.git
cd harako-rnaseq
git checkout v0.3.0-beta.1
just app
```

`just app` and `just app-ps` build locally and mount the checkout over `/app`;
they are source/local-build launchers rather than published-image launchers.

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
  ghcr.io/do-shima/harako-rnaseq:v0.3.0-beta.1
docker inspect ghcr.io/do-shima/harako-rnaseq:v0.3.0-beta.1
```

GitHub artifact attestation and BuildKit provenance are separate records.
Verify the attestation against the digest and inspect the attached SBOM with
an OCI-capable tool. Automated SBOM license detection is an inventory aid,
not a legal conclusion.
