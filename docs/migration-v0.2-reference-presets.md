# v0.2 reference preset migration

| Old selection | New canonical selection |
| --- | --- |
| `human_gencode/pinned` or `release-113` | `human_ensembl_grch38/release-113` |
| `mouse_gencode/pinned` or `release-113` | `mouse_ensembl_grcm39/release-113` |
| `mouse_gencode_mm10/pinned` | `mouse_ensembl_grcm38/release-102` |
| `mouse_gencode_mm10/release-113` | `mouse_ensembl_grcm38/release-102` |
| `rat_ensembl/pinned` or `release-113` | `rat_ensembl_mratbn7_2/release-113` |

New configs store canonical IDs. Old configs remain readable and produce one
migration notice in the GUI. The GRCm38 release change is explicit because the
old release-113 URLs did not identify a valid Ensembl GRCm38 bundle.

Cache directories are checked in this order:

1. canonical preset and canonical release;
2. legacy alias and canonical release;
3. a mapped historical alias/release only when every file matches the canonical
   bundle's pinned SHA256.

Legacy cache files are used in place. No large file is copied, moved, or linked.
New downloads use the canonical location.

Existing frozen run configs with direct reference paths continue to use those
paths and are not rewritten. Canonicalization does not rename existing run
directories or run IDs. New frozen configs record resolved paths and biological
metadata in `reference_provenance`.

Checksum enforcement applies to all new built-in acquisition and compatible
legacy-cache reuse. All public-beta bundles are pinned; a missing hash is now a
manifest validation error. Custom references remain available and are labeled
custom and unverified unless checked separately.
