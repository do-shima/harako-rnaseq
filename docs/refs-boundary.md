# Reference resolution boundary

`app/reference_presets.py` is the source of truth for manifest interpretation.
It provides pure preset/alias/release helpers plus non-destructive cache
selection. The UI adapter in `app/ui/refs.py`, CLI, Snakemake, fetcher, and
checksum pinning tool all delegate to it.

The resolver accepts schema-v2 manifests and legacy manifests. Structural keys
such as `aliases`, `preset_metadata`, and `schema_version` cannot become release
choices. Alias cycles and unknown IDs fail explicitly.

Cache resolution is read-only. It prefers canonical locations and then compatible
legacy alias locations; it never copies, moves, or creates symlinks. Direct paths
in a frozen run config bypass manifest resolution.

Network and file mutation remain in scripts:

- `scripts/fetch_reference_preset.py` downloads atomically and validates files.
- `scripts/pin_reference_checksums.py` inspects or explicitly downloads bundles
  and updates only selected manifest entries when `--write` is supplied.

Neither module touches Streamlit session state.

Schema-v2 built-in manifests require complete lowercase SHA256 values for every
pinned transcript FASTA, genome FASTA, and GTF. Custom references are outside
this manifest requirement and retain explicit custom/verification metadata.
