# Third-Party Notices

## ikra

- Project: ikra
- Source: https://github.com/yyoshiaki/ikra
- Audited revisions:
  - `master`: `c242855e88bfc4fc781c82ee4c6c20249cd18bf1`
  - `v2.0.1`: `557f0bfd2c699ebe886525d4a394e04e5f106248`
- License: CC BY-NC 4.0
- Citation: Hiraoka Yu et al. yyoshiaki/ikra: ikra v2.0.1. Zenodo.
  https://doi.org/10.5281/zenodo.5541399
- Relationship: Harako-RNAseq was conceptually inspired by ikra. The
  provenance audit found no copied or adapted ikra source code, documentation,
  test data, or assets.

Harako-RNAseq is not an official successor to, or endorsed by, ikra or its
authors.

This notice records inspiration and provenance. It does not change ikra's
CC BY-NC 4.0 license or imply that ikra is available under the license applied
to Harako-RNAseq.

## Bundled and Runtime Components

Harako-RNAseq uses and may distribute third-party components under their own
licenses. The PolyForm Noncommercial License 1.0.0 applies to Harako-RNAseq
source code and does not relicense the entire Docker image or its third-party
contents.

The following inventory entries require verification before public image
distribution:

- Docker base image and operating-system packages: **verification required**
- Salmon and fastp binaries: **verification required**
- Python packages in `requirements.lock.txt`: **verification required**
- R, CRAN, and Bioconductor packages installed by `Dockerfile`:
  **verification required**
