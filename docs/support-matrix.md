# Support matrix

Statuses describe testing performed for the v0.3.0-beta.2 release candidate. They are
not promises for every host configuration or dataset size.

| Environment or capability | Status | Notes |
| --- | --- | --- |
| Windows with Docker Desktop | Verified | PowerShell launch, Docker tests, smoke, and bind-mount paths were validated. |
| Ubuntu/Linux with Docker | Verified | Linux container workflow and launcher path are validated. |
| Intel-based macOS | Not yet verified | A Docker entry point exists, but release validation has not been recorded. |
| Apple Silicon | Not supported | Current image assets are Linux x86_64; no arm64 image is published. |
| `linux/amd64` container | Verified | Current Docker build and tool binaries target amd64. |
| v0.3.0-beta.2 GHCR publication | Manual gate | The exact `v0.3.0-beta.2` and moving `beta` tags, digest, SBOM, provenance, and attestation must be verified after publication. The previously published v0.3.0-beta.1 image remains historical evidence. No `latest` image is produced for a prerelease. |
| Human Ensembl preset | Verified | GRCh38, Ensembl 113, checksum-pinned. |
| Mouse Ensembl presets | Verified | GRCm39/113 and GRCm38/102, checksum-pinned. |
| Rat Ensembl preset | Verified | mRatBN7.2, Ensembl 113, checksum-pinned. |
| Custom references | Limited | Supported, but biological compatibility and public-manifest identity are user responsibilities. |
| Local single-user use | Verified | Intended deployment and tested security boundary. |
| Hosted multi-user use | Not supported | No authentication, tenant isolation, or service hardening. |
| Native non-Docker execution | Not supported | Public workflows assume the pinned Docker environment. |
| SRA/ENA acquisition | Verified | Run tables, accession lists, retries, and local-file paths are covered by regression tests. |

The exact `linux/amd64` release image is the recommended installation method
for most users and for reproducible research. Platform verification does not
establish that a particular experimental design or dataset is scientifically
suitable.
