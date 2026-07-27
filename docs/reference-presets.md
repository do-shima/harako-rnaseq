# Reference presets

Harako-RNAseq reference presets are Ensembl bundles described by
`workflow/ref_manifest.yaml`. The manifest records provider, species, assembly,
annotation release, URLs, and SHA256 values. Reference identity is never inferred
from an old preset name.

| Canonical preset | Legacy alias | Provider | Species | Assembly | Annotation | Manifest release |
| --- | --- | --- | --- | --- | --- | --- |
| `human_ensembl_grch38` | `human_gencode` | Ensembl | human | GRCh38 | 113 | `release-113` |
| `mouse_ensembl_grcm39` | `mouse_gencode` | Ensembl | mouse | GRCm39 | 113 | `release-113` |
| `mouse_ensembl_grcm38` | `mouse_gencode_mm10` | Ensembl | mouse | GRCm38/mm10 | 102 | `release-102` |
| `rat_ensembl_mratbn7_2` | `rat_ensembl` | Ensembl | rat | mRatBN7.2 | 113 | `release-113` |

`pinned` resolves to the release recorded by each preset's `pinned_release`.
The historical selection `mouse_gencode_mm10/release-113` migrates explicitly to
`mouse_ensembl_grcm38/release-102`; it is not relabeled as Ensembl 113.

## Cache migration

Cache lookup prefers the canonical preset and canonical release, then checks
legacy alias directories for the same release. For the historical GRCm38
selection, `mouse_gencode_mm10/release-113` is considered only when all files
match the pinned GRCm38/release-102 hashes. Legacy files are used in place:
Harako does not copy, move, or symlink large reference bundles. New downloads
always target the canonical directory.

Frozen runs with explicit reference paths remain authoritative and are not
re-resolved. New configs save canonical IDs and record the actual resolved paths
in `reference_provenance`.

## Checksum policy

All four public-beta bundles have complete SHA256 values. Cached and downloaded
built-in files must pass size, complete gzip-stream, FASTA/GTF format, and SHA256
validation. A missing built-in hash is a manifest error.

Custom references remain supported. They are recorded as `provider: custom` and
unverified unless checksums are calculated locally.

Maintainers can verify every cached bundle without network access:

```text
python scripts/pin_reference_checksums.py --manifest workflow/ref_manifest.yaml --cache-dir output/refs_cache --release pinned --dry-run
```

To refresh references, use `--download-missing` with an empty, separate cache,
review the JSON proposal, and use `--write` only after all files validate.
The tool never overwrites an existing valid bundle implicitly.

SHA256 values identify the downloaded content. They do not establish that an
assembly or annotation is biologically appropriate for a study; users must
select the assembly that matches their samples and experimental design.

The deprecated `scripts/fetch_refs_ensembl.sh --experimental-grcr8` helper uses
a separate GRCr8/release-115 directory. GRCr8 is not a public beta preset. A
future `rat_ensembl_grcr8` preset requires a jointly validated transcript FASTA,
genome FASTA, GTF, release, and complete SHA256 set.
