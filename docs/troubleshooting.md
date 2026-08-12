# Troubleshooting

Start with `just doctor-ui`, then inspect the affected run's logs. Preserve the
run directory until the cause is understood.

## Docker server is not running

Run `docker version` and `docker info`. Both client and Linux server sections
must respond. On Windows, start Docker Desktop and confirm Linux containers
are selected.

## Port 8501 is already allocated

Find and stop the existing container:

```powershell
docker ps
docker stop <container-id>
```

Then restart with `just app` or `just app-ps`.

## Initial build or build-cache errors

The first build installs R and Bioconductor dependencies and can be slow.
Confirm internet access, available Docker disk space, and the active Docker context.
Snapshot or package-download errors should be retried only after checking the
complete build error; do not delete source or run data.

## Missing FASTQ or paired-end mismatch

- Confirm the selected input subdirectories.
- Use paths relative to the mounted input root where possible.
- Do not put `/app` paths in the sample table.
- Confirm each paired sample has matching read-one/read-two files.
- Re-run Auto-pair, then inspect every row before Save.

Missing, inaccessible, or invalid pairings remain blocking structural errors.

## Reference download or checksum failure

Confirm the provider, assembly, annotation release, URL, and available disk
space. A checksum mismatch is blocking and may indicate a partial, corrupted,
or changed file. Do not bypass built-in checksum enforcement.

The fetcher removes an invalid individual file and preserves other valid cache
files. Legacy cache directories are reused in place only after their contents
match the canonical hashes.

## Snakemake lock or incomplete output

Use the UI Resume or Recover action for the affected frozen run. On Windows,
the run-specific helpers are available after setting `OUT` to that run:

```powershell
just windows-dry-run-ps
just windows-unlock-ps
just windows-run-ps
```

Unlock only when no workflow process is still running. Do not delete arbitrary
`.snakemake` metadata or copy files between run directories.

## Windows bind mounts and Git Bash

PowerShell is the verified Windows shell. Git Bash/MSYS can rewrite container
paths. Use PowerShell, or explicitly disable MSYS path conversion for direct
Docker commands.

If a drive is unavailable to Docker Desktop, verify Docker file-sharing and
Windows permissions for the input and output directories.

PowerShell recipe arguments are normally supplied through environment
variables such as `$env:INPUT`, `$env:OUT`, and `$env:CONFIG`; writing
`INPUT=...` after a recipe is not portable PowerShell syntax.

The repository enforces LF for executable scripts. If Git repeatedly reports
line-ending noise on Windows, use the repository `.gitattributes` policy and
review the local `core.autocrlf` setting rather than rewriting files in bulk.

## Validation state or missing details

After changing samples, references, or Advanced settings, Save and Validate
again before Dry run or Run. A stale validation state is intentional. If a
historical run lacks details, inspect its frozen configuration and run logs;
do not replace them with the current UI draft.

## Logs and support bundles

Use:

```bash
just logs
```

Run-local logs and metadata are stored with the frozen run, including
Snakemake command/stdout/stderr records and captured tool versions. UI session
logs remain session-scoped.

Before sharing a support bundle, remove host paths, sample identifiers,
credentials, patient data, and confidential metadata. Follow
[SUPPORT.md](../SUPPORT.md).

## Report missing or not self-contained

First confirm the workflow completed and inspect the report rule log. Validate
an existing report with:

```bash
just check-report-selfcontained path/to/report.html
```

Use `just report-out` only with the intended frozen run. The checker exits
nonzero for missing reports or external HTTP resources.

## Safe escalation

Report the Harako version or commit, OS, Docker version, launch command,
pipeline stage, expected and actual behavior, and sanitized logs. Do not post raw
FASTQ or confidential data.
