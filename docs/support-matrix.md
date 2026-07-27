# Support matrix

Statuses describe the v0.2.0-beta.1 public-beta evidence. They are not promises
for every host configuration or dataset size.

| Environment or capability | Status | Notes |
| --- | --- | --- |
| Windows with Docker Desktop | Verified | PowerShell launch, Docker tests, smoke, and bind-mount paths were validated. |
| Ubuntu/Linux with Docker | Verified | Linux container workflow and launcher path are validated. |
| macOS Intel | Not yet verified | Docker entry point exists, but release validation has not been recorded. |
| Apple Silicon | Not supported | Current image assets are Linux x86_64; no arm64 image is published. |
| `linux/amd64` container | Verified | Current Docker build and tool binaries target amd64. |
| Human Ensembl preset | Verified | GRCh38, Ensembl 113, checksum-pinned. |
| Mouse Ensembl presets | Verified | GRCm39/113 and GRCm38/102, checksum-pinned. |
| Rat Ensembl preset | Verified | mRatBN7.2, Ensembl 113, checksum-pinned. |
| Custom references | Limited | Supported, but biological compatibility and public-manifest identity are user responsibilities. |
| Local single-user use | Verified | Intended deployment and tested security boundary. |
| Hosted multi-user use | Not supported | No authentication, tenant isolation, or service hardening. |
| Native non-Docker execution | Not supported | Public workflows assume the pinned Docker environment. |
| SRA/ENA acquisition | Verified | Run tables, accession lists, retries, and local-file paths are covered by regression tests. |

The current release has no public prebuilt image. Users build the single
`linux/amd64` image locally. Platform verification does not establish that a
particular experimental design or dataset is scientifically suitable.
