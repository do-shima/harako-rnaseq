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

This human-readable inventory covers direct runtime components. Installed
versions and license metadata are also collected by
`scripts/collect_runtime_license_inventory.py`. Transitive operating-system,
Python, R, and binary-library dependencies remain subject to their own license
files and are represented in the container SBOM. Automated license collection
is an engineering inventory, not a legal opinion.

### Base and runtime

| Component | License | Verification source |
| --- | --- | --- |
| Python official image / Python | Python Software Foundation License | Image `/usr/local/lib/python3.11/LICENSE.txt` and [Python license](https://docs.python.org/3/license.html) |
| Debian and apt-installed packages | Component-specific Debian licenses | Installed package metadata and `/usr/share/doc/*/copyright` |
| R | GPL-2.0-or-later | Installed R `COPYING` and [R licensing](https://www.r-project.org/Licenses/) |

### Workflow and application packages

| Component | License | Verification source |
| --- | --- | --- |
| Snakemake | MIT | Installed Python distribution license file |
| Streamlit | Apache-2.0 | Installed Python distribution metadata |
| pandas | BSD-3-Clause | Installed Python distribution license file |
| PyYAML | MIT | Installed Python distribution license file |
| Typer | MIT | Installed Python distribution metadata |

### Bioinformatics binaries

| Component | Version | License | Distribution notice |
| --- | --- | --- | --- |
| fastp | 0.23.4 | MIT | Exact upstream notice is installed at `/usr/share/licenses/harako-rnaseq/third-party/fastp-LICENSE` |
| Salmon | 1.10.0 | GPL-3.0 | GPL text and the exact corresponding source archive are installed in the image; see `third-party/Salmon-SOURCE.md` |

### Direct R, CRAN, and Bioconductor packages

| Component | License reported by installed package |
| --- | --- |
| data.table | MPL-2.0 |
| readr | MIT |
| dplyr | MIT |
| ggplot2 | MIT |
| rmarkdown | GPL-3 |
| jsonlite | MIT |
| yaml | BSD-3-Clause |
| BiocManager | Artistic-2.0 |
| tximport | LGPL-2.0-or-later |
| DESeq2 | LGPL-3.0-or-later |
| apeglm | GPL-2.0 |
| EnhancedVolcano | GPL-3.0 |
| clusterProfiler | Artistic-2.0 |
| fgsea | MIT |
| AnnotationDbi | Artistic-2.0 |
| GO.db | Artistic-2.0 |
| org.Hs.eg.db | Artistic-2.0 |
| org.Mm.eg.db | Artistic-2.0 |
| org.Rn.eg.db | Artistic-2.0 |

The installed package `DESCRIPTION` files and referenced license files are the
verification source for the R package table. Annotation data packages may also
contain data-source notices in their installed package metadata.
