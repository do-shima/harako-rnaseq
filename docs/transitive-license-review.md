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

Four Debian copyleft entries have Debian snapshot source references. Ten R
packages (`bbmle`, `codetools`, `emdbook`, `formatR`, `highr`, `knitr`, `mime`,
`qvalue`, `snow`, and `tximport`) have version and upstream metadata recorded,
but the maintainer must confirm that source availability is sufficient for the
planned GHCR distribution method. `tximport` is a direct dependency; the other
entries are transitive.

Salmon is handled separately: the image contains its GPL-3.0 text and the exact
1.10.0 corresponding-source archive. Direct component notices remain in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

## Release decision

There are no genuinely unresolved `NOASSERTION` payloads and no unresolved
direct license identity. Public image publication remains blocked until the
copyleft source-availability evidence and distribution approach are approved.
An SBOM license field alone is not treated as a legal conclusion.
