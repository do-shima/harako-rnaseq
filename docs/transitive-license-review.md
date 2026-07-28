# Transitive container license review

Audit date: 2026-07-27

This is an engineering inventory, not legal advice. It reviews the 170 SPDX
packages for which Docker Scout reported `licenseDeclared=NOASSERTION` in the
Phase 4 `linux/amd64` image.

## Classification

| Category | Count |
| --- | ---: |
| Aggregate or virtual scanner entry | 2 |
| Duplicate representation | 66 |
| License resolved from installed package metadata | 39 |
| License evidence in Debian copyright data | 49 |
| Copyleft/source-availability obligation | 14 |
| Genuinely unresolved | 0 |

The machine-readable evidence is generated in the ignored
`output/release-audit/sbom-license-review.json` and `.tsv` files. It records
installed Python metadata and license files, R `DESCRIPTION` metadata, Debian
copyright paths, bundled JavaScript metadata, and source references.

Four Debian copyleft entries have Debian snapshot source references. Exact
source archives for ten R packages (`bbmle`, `codetools`, `emdbook`, `formatR`,
`highr`, `knitr`, `mime`, `qvalue`, `snow`, and `tximport`) are pinned by URL
and SHA256, matched to installed `DESCRIPTION` Package/Version fields, and
included under `/usr/share/licenses/harako-rnaseq/sources/r/`. The bundle
contains deterministic `SOURCE_MANIFEST.json`, `SOURCE_MANIFEST.tsv`, and
`README.txt` records. `tximport` is direct; the other entries are transitive.

Salmon is handled separately: the image contains its GPL-3.0 text and the exact
1.10.0 corresponding-source archive. Direct component notices remain in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

## Release decision

There are no genuinely unresolved `NOASSERTION` payloads, direct license
identities, or listed R source entries. The ten R archives total 4,383,290
bytes and exactly match installed versions. This evidence closes the recorded
engineering source-availability gate; it is not a legal conclusion. An SBOM
license field alone is not treated as one.
