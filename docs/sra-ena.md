# SRA and ENA input

Harako can prepare local FASTQ inputs and a sample table from Run Selector
tables or SRA/ENA/DRR accession lists. Acquisition remains a separate step
before the GUI analysis run.

## Accepted inputs

- NCBI Run Selector tables in TSV, CSV, or text form.
- A text file containing accessions.
- Space-separated `SRR`, `ERR`, or `DRR` accessions.

Input priority is `RUN_TABLE`, then `SRR_LIST`, then `SRR`.

## Ubuntu and Linux

```bash
RUN_TABLE=metadata/SraRunTable.txt just srr
SRR_LIST=metadata/accessions.txt just srr
SRR="SRR123456 ERR123456 DRR123456" just srr
```

## Windows PowerShell

```powershell
$env:RUN_TABLE="metadata\SraRunTable.txt"; just srr-ps
$env:SRR_LIST="metadata\accessions.txt"; just srr-ps
$env:SRR="SRR123456 ERR123456 DRR123456"; just srr-ps
```

Set only the variable for the intended input source to avoid accidentally
selecting a higher-priority source.

## Condition mapping

Conditions are blank unless explicitly derived:

```bash
CONDITION_FROM=group RUN_TABLE=metadata/SraRunTable.txt just srr
CONDITION_MAP=metadata/conditions.tsv SRR_LIST=metadata/accessions.txt just srr
```

The condition map has two columns: sample or run accession, then condition.
Review the generated sample table before analysis. Repository metadata does
not establish biological independence.

## Local file paths

The acquisition helper accepts native Windows paths, Unix paths, and local
file URIs including:

- `file:///C:/data/sample.fastq.gz`
- `file://C:/data/sample.fastq.gz`
- `file:///home/user/data/sample.fastq.gz`
- `file://server/share/path/sample.fastq.gz`

Percent-encoded characters are decoded once. HTTP and HTTPS values are not
treated as local paths.

## Retries, resume, and logs

Existing valid downloads are reused. Set `SRR_FORCE=1` only when an explicit
replacement is required. Interrupted transfers use acquisition-specific
recovery rather than modifying Snakemake run metadata.

Each acquisition directory includes:

- `run/manifest.json`
- `run/srr_fetch.log`
- generated FASTQ files
- generated `samples.tsv`

Inspect the log and available disk space before retrying. Do not upload these
artifacts publicly without sanitization.

## Privacy and storage

Public accessions may still be associated with sensitive study metadata.
Review the applicable consent and data-use terms. FASTQ files can be large,
and conversion can require temporary space in addition to final files.

Never attach FASTQ, patient data, credentials, or identifiable sample
information to a public issue. See [SUPPORT.md](../SUPPORT.md).
