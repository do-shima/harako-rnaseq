# Advanced usage

The Streamlit GUI is the supported primary interface. These commands are for
automation, diagnostics, and maintainers.

## Direct validation

Validate an explicit configuration:

```bash
just validate config/path/config.yaml
```

Validate the configured input/output mounts:

```bash
INPUT=/data/input OUT=/data/output just validate-out
```

On PowerShell, set environment variables before invoking recipes:

```powershell
$env:INPUT="D:\rna\input"
$env:OUT="D:\rna\output"
just validate-out
```

Structurally valid QC-only configurations validate successfully and print the
analysis mode, reason, condition counts, and total samples.

## Direct run helpers

Common helpers include:

```bash
INPUT=/data/input OUT=/data/output just run-real
just run-out
just report-out
just logs
just verify-real
```

Use a run's frozen configuration for Resume or Recover. Do not substitute a
current UI draft for an existing run.

## Direct Snakemake

The application assembles the supported Snakemake command and work directory.
For diagnostics, list rules with:

```bash
just list-rules
```

Targets in direct Snakemake commands belong after `--`. Keep one
`--configfile` and one coherent set of `--config` overrides. Prefer a dry-run
before executing a manually constructed command.

Direct commands must use the run-local frozen configuration for an existing
run. Historical `/output/config.yaml` examples are not the current UI
contract.

## Self-contained report validation

```bash
just check-report-selfcontained path/to/report.html
```

Exit code 0 means the report passed. Missing reports and external resource
references return nonzero:

- 0: report passed;
- 2: invalid invocation or missing report;
- 49: external HTTP resources were detected.

`just debug-report-externals` lists remaining external references for
maintainers.

## Custom references

Custom mode accepts transcript FASTA, genome FASTA, and GTF paths. Custom
references are labeled custom and are not claimed to match a public manifest.
Harako may calculate local content hashes, but selection and biological
compatibility remain the user's responsibility.

Do not mix assemblies or annotation releases. See
[Reference presets](reference-presets.md) and
[Reference boundary](refs-boundary.md).

## Reference checksum maintenance

Inspect existing caches without network access or manifest changes:

```bash
python scripts/pin_reference_checksums.py \
  --manifest workflow/ref_manifest.yaml \
  --cache-dir output/refs_cache \
  --preset human_ensembl_grch38 \
  --release pinned \
  --dry-run
```

`--download-missing` is an explicit network opt-in. `--write` reads validated
cache files and updates selected canonical entries atomically. Maintainers
must review provider, assembly, annotation release, URLs, formats, and all
proposed hashes together before writing.

Content hashes identify exact files; they do not establish biological
suitability.

## Salmon and tximport compatibility

Some Salmon versions place `meta_info.json` under `aux_info/`. Harako preserves
the stable sample-root metadata path for downstream consumers when necessary.

Ensembl transcript headers and quantification identifiers may include version
suffixes or `|`-delimited metadata. tximport mapping normalizes both sides
explicitly when versions differ; it does not use TPM as DESeq2 input. When
diagnosing a mapping mismatch, compare the first-column transcript identifiers
in `quant.sf` with the transcript-to-gene mapping before changing configuration.

## Development diagnostics

Set `HARAKO_DEV_UI=1` only in a trusted development environment to expose
additional diagnostics. Public error messages intentionally omit tracebacks,
host paths, and session internals.

Maintainer regression recipes include:

```bash
just test-docker
just test-tximport
just test-tximport-rat-header
just test-enrichment
just smoke
just verify-smoke
```

See [CONTRIBUTING.md](../CONTRIBUTING.md) before changing behavior or output
contracts.
