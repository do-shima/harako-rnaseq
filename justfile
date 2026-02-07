set dotenv-load := false

REPO := if os() == "windows" { `powershell -NoProfile -Command "(Get-Location).Path"` } else { invocation_directory() }
IMAGE := env_var_or_default("IMAGE", "rnaseq_pipeline")
ENGINE := env_var_or_default("ENGINE", "real")
THREADS := env_var_or_default("THREADS", "1")
ALIGN := env_var_or_default("ALIGN", "none")
SPECIES := env_var_or_default("SPECIES", "mouse")
ARGS := env_var_or_default("ARGS", "")
INPUT := env_var_or_default("INPUT", "")
OUT := env_var_or_default("OUT", "")
ENABLE_ENRICHMENT := env_var_or_default("ENABLE_ENRICHMENT", "0")
REPORT := env_var_or_default("REPORT", "")
CONFIG := env_var_or_default("CONFIG", "")
SELFCONTAINED := env_var_or_default("SELFCONTAINED", "strict")
SELFCONTAINED_ARGS := if SELFCONTAINED == "warn" { "--warn-only" } else { "" }
RUN_TABLE := env_var_or_default("RUN_TABLE", "")
SRR_LIST := env_var_or_default("SRR_LIST", "")
SRR := env_var_or_default("SRR", "")
CONDITION_FROM := env_var_or_default("CONDITION_FROM", "")
CONDITION_MAP := env_var_or_default("CONDITION_MAP", "")
SRR_FORCE := env_var_or_default("SRR_FORCE", "0")
AUTO_UI := env_var_or_default("AUTO_UI", "1")

_docker *ARGS:
    #!/usr/bin/env bash
    set -euo pipefail
    if command -v uname >/dev/null 2>&1; then
      case "$(uname -s)" in
        MSYS*|MINGW*|CYGWIN*)
          export MSYS_NO_PATHCONV=1
          export MSYS2_ARG_CONV_EXCL="*"
          ;;
      esac
    fi
    docker "${ARGS[@]}"

_docker_ps *ARGS:
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command 'docker @args' -- {{ARGS}}

build:
    just _docker -- build -t {{IMAGE}} .

build-if-needed:
    @just _docker -- image inspect {{IMAGE}} >/dev/null 2>&1 || just _docker -- build -t {{IMAGE}} .

build-ps:
    just _docker_ps -- build -t {{IMAGE}} .

build-if-needed-ps:
    @powershell.exe -NoProfile -ExecutionPolicy Bypass -Command 'if (-not (docker image inspect "{{IMAGE}}" *> $null)) { docker build -t "{{IMAGE}}" . }'

smoke: build
    just _docker -- run --rm -v "{{REPO}}:/app" rnaseq_pipeline bash -lc 'cd /app && \
      OUTDIR=out_smoke && rm -rf "$OUTDIR" && mkdir -p "$OUTDIR/metadata" && \
      printf "sample\tcondition\tfastq1\nsample1\tA\tsample1.fastq.gz\n" > "$OUTDIR/metadata/samples.tsv" && \
      printf "%s\n" \
        "engine: stub" \
        "species: mouse" \
        "samples:" \
        "  - sample1" \
        "input: /app/tests/data" \
        "output: /app/$OUTDIR" \
        "sample_table: /app/$OUTDIR/metadata/samples.tsv" \
        "ref:" \
        "  transcripts_fasta: transcripts.fa" \
        "  genome_fasta: genome.fa" \
        "  gtf: genes.gtf" \
        > "$OUTDIR/config.yaml" && \
      python -m app validate --config "$OUTDIR/config.yaml" --input /app/tests/data --output "/app/$OUTDIR" && \
      python -m app run-id --config "$OUTDIR/config.yaml" --input /app/tests/data --engine stub --threads 1 && \
      python -m app run --config "$OUTDIR/config.yaml" --input /app/tests/data --output "/app/$OUTDIR" --align none --engine stub && \
      test -f "$OUTDIR/report/report.html" && \
      OUTREAL=out_smoke_real && rm -rf "$OUTREAL" && mkdir -p "$OUTREAL/metadata" && \
      printf "sample\tcondition\tfastq1\nsample1\tA\tsample1.fastq.gz\n" > "$OUTREAL/metadata/samples.tsv" && \
      printf "%s\n" \
        "engine: real" \
        "species: mouse" \
        "samples:" \
        "  - sample1" \
        "input: /app/tests/data" \
        "output: /app/$OUTREAL" \
        "sample_table: /app/$OUTREAL/metadata/samples.tsv" \
        "ref:" \
        "  transcripts_fasta: transcripts.fa" \
        "  genome_fasta: genome.fa" \
        "  gtf: genes.gtf" \
        > "$OUTREAL/config.yaml" && \
      python -m snakemake --directory "/app/$OUTREAL" -s workflow/Snakefile --configfile "/app/$OUTREAL/config.yaml" --config input=/app/tests/data output="/app/$OUTREAL" engine=real --cores 1 -p -- fastp | tee "/app/$OUTREAL/fastp_real.log" && \
      grep -q "fastp -i" "/app/$OUTREAL/fastp_real.log" && \
      test ! -e "/app/$OUTREAL/.snakemake/scripts/fastp_stub.py" && \
      if [ "${ENABLE_ENRICHMENT:-0}" = "1" ]; then \
        python -m snakemake -s tests/enrichment_fixture/Snakefile --cores 1 -p && \
        test -f tests/enrichment_fixture/out/results/enrichment/contrast=A_vs_B/status.json; \
      fi && \
      python tests/test_srr_fetch_local.py && \
      python tests/test_dag_fastp.py && \
      python tests/test_species_dry_run.py && \
      python tests/test_ui_config_payload.py && \
      python tests/test_snakemake_cli_compat.py && \
      python tests/test_ref_manifest_presets.py && \
      python tests/test_i18n.py && \
      python tests/test_error_messages.py && \
      python tests/test_snakefile_no_output_functions.py'

verify-smoke:
    just smoke
    just check-report-selfcontained out_smoke/report/report.html
    just _docker -- run --rm -v "{{REPO}}:/app" rnaseq_pipeline bash -lc 'test -f /app/out_smoke/report/report.html && test -f /app/out_smoke/deseq2/results.tsv && test -f /app/out_smoke/tximport/txi.tsv && test -f /app/out_smoke/salmon/sample1/quant.sf && if [ "{{ENABLE_ENRICHMENT}}" = "1" ]; then test -f /app/tests/enrichment_fixture/out/results/enrichment/contrast=A_vs_B/status.json; fi'

list-rules: build
    just _docker -- run --rm -v "{{REPO}}:/app" rnaseq_pipeline bash -lc "cd /app && python -m snakemake -s workflow/Snakefile --configfile tests/config.yaml --config input=tests/data output=out --list-rules"

list_rules: list-rules

init: build
    just _docker -- run --rm -it -v "{{REPO}}:/app" -v "{{INPUT}}:/input" -v "{{OUT}}:/output" rnaseq_pipeline bash -lc "cd /app && python -m app init --input-base /input --out /output"

validate CONFIG=CONFIG:
    if [ -z "{{CONFIG}}" ]; then echo "CONFIG is required (use CONFIG=... or set CONFIG env var)"; exit 2; fi
    just _docker -- run --rm -it -v "{{REPO}}:/app" rnaseq_pipeline bash -lc \
      "cd /app && p='{{CONFIG}}'; p=\${p#CONFIG=}; python -m app validate --config \"\$p\" {{ARGS}}"

validate-out: build
    just _docker -- run --rm -it -v "{{REPO}}:/app" -v "{{INPUT}}:/input:ro" -v "{{OUT}}:/output" rnaseq_pipeline bash -lc \
      "cd /app && python -m app validate --config /output/config.yaml --input /input --output /output {{ARGS}}"

dry-run: build
    just _docker -- run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input" -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'cd /app && python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output --cores {{THREADS}} -n -p --latency-wait 60 --'

dry-run-rat: build
    just _docker -- run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input" -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'cd /app && python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output species=rat --cores {{THREADS}} -n -p --latency-wait 60 --'

gentrome: build
    just _docker -- run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input" -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'cd /app && python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output --cores {{THREADS}} -p --latency-wait 60 -- gentrome'

gentrome-rat: build
    just _docker -- run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input" -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'cd /app && python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output species=rat --cores {{THREADS}} -p --latency-wait 60 -- gentrome'

all: build
    just _docker -- run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input" -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'cd /app && python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output --cores {{THREADS}} -p --latency-wait 60 --'

all-nobuild:
    just _docker -- run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input" -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'cd /app && python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output --cores {{THREADS}} -p --latency-wait 60 --'

all-rat-nobuild:
    just _docker -- run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input" -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'cd /app && python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output species=rat --cores {{THREADS}} -p --latency-wait 60 --'

check-outputs:
    just _docker -- run --rm -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'ls -lh /output/report/report.html /output/deseq2/results.tsv /output/tximport/txi.tsv /output/tximport/tpm.tsv /output/tximport/qc_library_sizes.tsv'

check-salmon-meta:
    just _docker -- run --rm -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'for s in /output/salmon/*; do if [ -d "$s" ]; then echo "== $s"; ls -lh "$s/meta_info.json" "$s/aux_info/meta_info.json" "$s/cmd_info.json" 2>/dev/null || true; fi; done'

logs:
    just _docker -- run --rm -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'echo "== /output/logs =="; ls -lh /output/logs || true; echo "== /output/.snakemake/log =="; ls -lh /output/.snakemake/log || true; echo "== tail gentrome =="; tail -n 50 /output/logs/gentrome.log 2>/dev/null || true; echo "== tail salmon_quant =="; tail -n 50 /output/logs/salmon_quant/*.log 2>/dev/null || true'

fetch-refs-rat:
    just _docker -- run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input" rnaseq_pipeline bash -lc 'sh /app/scripts/fetch_refs_ensembl.sh rat'

fetch-refs-ps: build-if-needed-ps
    @powershell.exe -NoProfile -ExecutionPolicy Bypass -Command '$ErrorActionPreference="Stop"; $ctx = (docker context show).Trim(); if ($ctx -ne "default") { Write-Warning ("docker context is " + $ctx + " (expected default). Use: docker context use default") }; if (-not $env:INPUT) { throw "INPUT is required (set INPUT to an input-base folder; refs will be created under INPUT\refs)" }; docker run --rm --mount ("type=bind,src={{REPO}},target=/app") --mount ("type=bind,src=" + $env:INPUT + ",target=/input") "{{IMAGE}}" bash -lc "sh /app/scripts/fetch_refs_ensembl.sh {{SPECIES}}"'

fetch-refs-run-ps: build-if-needed-ps
    @powershell.exe -NoProfile -ExecutionPolicy Bypass -Command '$ErrorActionPreference="Stop"; $ctx = (docker context show).Trim(); if ($ctx -ne "default") { Write-Warning ("docker context is " + $ctx + " (expected default). Use: docker context use default") }; if (-not $env:INPUT) { throw "INPUT is required (set INPUT to the run_dir)" }; docker run --rm --mount ("type=bind,src={{REPO}},target=/app") --mount ("type=bind,src=" + $env:INPUT + ",target=/input") "{{IMAGE}}" bash -lc "sh /app/scripts/fetch_refs_ensembl.sh {{SPECIES}}"'

check-refs-rat:
    just _docker -- run --rm -v "{{INPUT}}:/input" rnaseq_pipeline bash -lc 'ls -lh /input/refs/rat/*.fa* /input/refs/rat/*.gtf*'

rat-config:
    just _docker -- run --rm -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'python -c "import yaml; p=\"/output/config.yaml\"; d=yaml.safe_load(open(p)) or {}; d[\"species\"]=\"rat\"; d.setdefault(\"ref\", {}); d[\"ref\"][\"rat\"]={\"transcripts_fasta\":\"refs/rat/Rattus_norvegicus.GRCr8.cdna.all.fa.gz\",\"genome_fasta\":\"refs/rat/Rattus_norvegicus.GRCr8.dna.toplevel.fa.gz\",\"gtf\":\"refs/rat/Rattus_norvegicus.GRCr8.115.gtf.gz\"}; yaml.safe_dump(d, open(p, \"w\"), sort_keys=False)"'

run INPUT=INPUT OUTPUT=OUT CONFIG=CONFIG ALIGN="none": build
    just _docker -- run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input:ro" -v "{{OUTPUT}}:/output" {{IMAGE}} bash -lc "cd /app && p='{{CONFIG}}'; p=\${p#CONFIG=}; python -m app run --input /input --output /output --config \"\$p\" --align {{ALIGN}} --engine {{ENGINE}} --threads {{THREADS}} {{ARGS}}"

run-ps: build-if-needed-ps
    @powershell.exe -NoProfile -ExecutionPolicy Bypass -Command '$ErrorActionPreference = "Stop"; $ctx = (docker context show).Trim(); if ($ctx -ne "default") { Write-Warning ("docker context is " + $ctx + " (expected default). Use: docker context use default") }; if (-not $env:INPUT -or -not $env:OUT -or -not $env:CONFIG) { throw "INPUT/OUT/CONFIG are required (set env vars or pass CONFIG=...)" }; if (-not (Test-Path $env:INPUT)) { throw "INPUT は Windows 側の絶対パス（例: D:\\）を設定してください" }; $cfg = $env:CONFIG; if ($cfg -like "CONFIG=*") { $cfg = $cfg.Substring(7) }; $repoAbs = [System.IO.Path]::GetFullPath("{{REPO}}"); $outBase = [System.IO.Path]::GetFullPath($env:OUT); $cfgAbs = [System.IO.Path]::GetFullPath($cfg); if ($cfgAbs.StartsWith($outBase, [System.StringComparison]::OrdinalIgnoreCase)) { $rel = $cfgAbs.Substring($outBase.Length).TrimStart([char]92, [char]47); $cfgIn = "/out_base/" + $rel.Replace([char]92, [char]47); } elseif ($cfgAbs.StartsWith($repoAbs, [System.StringComparison]::OrdinalIgnoreCase)) { $rel = $cfgAbs.Substring($repoAbs.Length).TrimStart([char]92, [char]47); $cfgIn = "/app/" + $rel.Replace([char]92, [char]47); } else { throw "CONFIG must live under OUT or repo for Docker access: " + $cfgAbs }; $runId = $env:RUN_ID; if (-not $runId) { $idArgs = @("run","--rm","--mount",("type=bind,src={{REPO}},target=/app"),"--mount",("type=bind,src=" + $env:INPUT + ",target=/input,readonly"),"--mount",("type=bind,src=" + $outBase + ",target=/out_base,readonly"),"{{IMAGE}}","python","-m","app","run-id","--config",$cfgIn,"--input","/input","--align","{{ALIGN}}","--engine","{{ENGINE}}","--threads","{{THREADS}}"); $runId = (& docker @idArgs).Trim(); if (-not $runId) { throw "Failed to compute run_id" } }; Write-Host ("run_id=" + $runId); $outDir = Join-Path (Join-Path $outBase "data_out") $runId; New-Item -ItemType Directory -Force -Path $outDir | Out-Null; $resumeArg = ""; if (Test-Path $outDir) { $count = (Get-ChildItem -Force $outDir | Measure-Object).Count; if ($count -gt 0) { $resumeArg = "--resume" } }; $runArgs = @("run","--rm","--mount",("type=bind,src={{REPO}},target=/app"),"--mount",("type=bind,src=" + $env:INPUT + ",target=/input,readonly"),"--mount",("type=bind,src=" + $outBase + ",target=/out_base,readonly"),"--mount",("type=bind,src=" + $outDir + ",target=/output"),"{{IMAGE}}","python","-m","app","run","--input","/input","--output","/output","--config",$cfgIn,"--align","{{ALIGN}}","--engine","{{ENGINE}}","--threads","{{THREADS}}","--run-id",$runId); if ($resumeArg) { $runArgs += $resumeArg }; if ($env:ARGS) { $runArgs += $env:ARGS.Split(" ") }; $output = (& docker @runArgs 2>&1); $rc = $LASTEXITCODE; if ($output) { Write-Host $output }; if ($rc -ne 0 -and ($output -match "Directory cannot be locked|LockException|Another snakemake instance")) { Write-Host "UI コンテナが /output を使用中。UI を停止するか、別 run_id の OUT に切り替えてください"; }; exit $rc'

unlock-ps: build-if-needed-ps
    @powershell.exe -NoProfile -ExecutionPolicy Bypass -Command '$ErrorActionPreference="Stop"; $ctx = (docker context show).Trim(); if ($ctx -ne "default") { Write-Warning ("docker context is " + $ctx + " (expected default). Use: docker context use default") }; if (-not $env:OUT -or -not $env:RUN_ID) { throw "OUT/RUN_ID are required (set OUT to base dir, RUN_ID to run id)" }; $outBase = [System.IO.Path]::GetFullPath($env:OUT); $outDir = Join-Path (Join-Path $outBase "data_out") $env:RUN_ID; if (-not (Test-Path $outDir)) { throw ("Run directory not found: " + $outDir) }; $cfgPath = Join-Path $outDir "config.yaml"; if (-not (Test-Path $cfgPath)) { throw "UI で Save して /output/config.yaml を生成してから実行してください。" }; docker run --rm --mount ("type=bind,src={{REPO}},target=/app") --mount ("type=bind,src=" + $outDir + ",target=/output") "{{IMAGE}}" python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output --unlock'

resume-ps: build-if-needed-ps
    @powershell.exe -NoProfile -ExecutionPolicy Bypass -Command '$ErrorActionPreference="Stop"; $ctx = (docker context show).Trim(); if ($ctx -ne "default") { Write-Warning ("docker context is " + $ctx + " (expected default). Use: docker context use default") }; if (-not $env:OUT -or -not $env:RUN_ID -or -not $env:INPUT) { throw "OUT/RUN_ID/INPUT are required" }; if (-not (Test-Path $env:INPUT)) { throw "INPUT は Windows 側の絶対パス（例: D:\\）を設定してください" }; $outBase = [System.IO.Path]::GetFullPath($env:OUT); $outDir = Join-Path (Join-Path $outBase "data_out") $env:RUN_ID; if (-not (Test-Path $outDir)) { throw ("Run directory not found: " + $outDir) }; $cfgPath = Join-Path $outDir "config.yaml"; if (-not (Test-Path $cfgPath)) { throw "UI で Save して /output/config.yaml を生成してから実行してください。" }; $runArgs = @("run","--rm","--mount",("type=bind,src={{REPO}},target=/app"),"--mount",("type=bind,src=" + $env:INPUT + ",target=/input,readonly"),"--mount",("type=bind,src=" + $outDir + ",target=/output"),"{{IMAGE}}","python","-m","snakemake","--directory","/output","-s","workflow/Snakefile","--configfile","/output/config.yaml","--config","input=/input","output=/output","engine={{ENGINE}}","--cores","{{THREADS}}","--rerun-incomplete"); if ($env:ARGS) { $runArgs += $env:ARGS.Split(" ") }; $output = (& docker @runArgs 2>&1); $rc = $LASTEXITCODE; if ($output) { Write-Host $output }; if ($rc -ne 0 -and ($output -match "Directory cannot be locked|LockException|Another snakemake instance")) { Write-Host "UI コンテナが /output を使用中。UI を停止するか、別 run_id の OUT に切り替えてください"; }; exit $rc'

windows-unlock-ps: build-if-needed-ps
    @powershell.exe -NoProfile -ExecutionPolicy Bypass -Command '$ErrorActionPreference="Stop"; $ctx = (docker context show).Trim(); if ($ctx -ne "default") { Write-Warning ("docker context is " + $ctx + " (expected default). Use: docker context use default") }; if (-not $env:INPUT -or -not $env:OUT) { throw "INPUT/OUT are required" }; if (-not (Test-Path $env:INPUT)) { throw "INPUT は Windows 側の絶対パス（例: D:\\）を設定してください" }; if (-not (Test-Path $env:OUT)) { throw "OUT は run_id の出力ディレクトリを指定してください" }; $cfgPath = Join-Path $env:OUT "config.yaml"; if (-not (Test-Path $cfgPath)) { throw "UI で Save して /output/config.yaml を生成してから実行してください。" }; docker run --rm --mount ("type=bind,src={{REPO}},target=/app") --mount ("type=bind,src=" + $env:INPUT + ",target=/input,readonly") --mount ("type=bind,src=" + $env:OUT + ",target=/output") "{{IMAGE}}" python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output --unlock'

windows-dry-run-ps: build-if-needed-ps
    @powershell.exe -NoProfile -ExecutionPolicy Bypass -Command '$ErrorActionPreference="Stop"; $ctx = (docker context show).Trim(); if ($ctx -ne "default") { Write-Warning ("docker context is " + $ctx + " (expected default). Use: docker context use default") }; if (-not $env:INPUT -or -not $env:OUT) { throw "INPUT/OUT are required" }; if (-not (Test-Path $env:INPUT)) { throw "INPUT は Windows 側の絶対パス（例: D:\\）を設定してください" }; if (-not (Test-Path $env:OUT)) { throw "OUT は run_id の出力ディレクトリを指定してください" }; $cfgPath = Join-Path $env:OUT "config.yaml"; if (-not (Test-Path $cfgPath)) { throw "UI で Save して /output/config.yaml を生成してから実行してください。" }; & just windows-unlock-ps; $runArgs = @("run","--rm","--mount",("type=bind,src={{REPO}},target=/app"),"--mount",("type=bind,src=" + $env:INPUT + ",target=/input,readonly"),"--mount",("type=bind,src=" + $env:OUT + ",target=/output"),"{{IMAGE}}","python","-m","snakemake","--directory","/output","-s","workflow/Snakefile","--configfile","/output/config.yaml","--config","input=/input","output=/output","--cores","{{THREADS}}","-n","-p","--latency-wait","60","--"); $output = (& docker @runArgs 2>&1); $rc = $LASTEXITCODE; if ($output) { Write-Host $output }; if ($rc -ne 0 -and ($output -match "Directory cannot be locked|LockException|Another snakemake instance")) { Write-Host "UI コンテナが /output を使用中。UI を停止するか、別 run_id の OUT に切り替えてください"; }; exit $rc'

windows-run-ps: build-if-needed-ps
    @powershell.exe -NoProfile -ExecutionPolicy Bypass -Command '$ErrorActionPreference="Stop"; $ctx = (docker context show).Trim(); if ($ctx -ne "default") { Write-Warning ("docker context is " + $ctx + " (expected default). Use: docker context use default") }; if (-not $env:INPUT -or -not $env:OUT) { throw "INPUT/OUT are required" }; if (-not (Test-Path $env:INPUT)) { throw "INPUT は Windows 側の絶対パス（例: D:\\）を設定してください" }; if (-not (Test-Path $env:OUT)) { throw "OUT は run_id の出力ディレクトリを指定してください" }; $cfgPath = Join-Path $env:OUT "config.yaml"; if (-not (Test-Path $cfgPath)) { throw "UI で Save して /output/config.yaml を生成してから実行してください。" }; & just windows-unlock-ps; $runArgs = @("run","--rm","--mount",("type=bind,src={{REPO}},target=/app"),"--mount",("type=bind,src=" + $env:INPUT + ",target=/input,readonly"),"--mount",("type=bind,src=" + $env:OUT + ",target=/output"),"{{IMAGE}}","python","-m","snakemake","--directory","/output","-s","workflow/Snakefile","--configfile","/output/config.yaml","--config","input=/input","output=/output","--cores","{{THREADS}}","-p","--latency-wait","60","--","report"); $output = (& docker @runArgs 2>&1); $rc = $LASTEXITCODE; if ($output) { Write-Host $output }; if ($rc -ne 0 -and ($output -match "Directory cannot be locked|LockException|Another snakemake instance")) { Write-Host "UI コンテナが /output を使用中。UI を停止するか、別 run_id の OUT に切り替えてください"; }; exit $rc'

run-real: build
    just _docker -- run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input:ro" -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'cd /app && python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output --cores {{THREADS}} {{ARGS}} -- report'

run-real-rat: build
    just _docker -- run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input:ro" -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'cd /app && python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output species=rat --cores {{THREADS}} {{ARGS}} -- report'

run-out: build
    if [ -z "{{INPUT}}" ] || [ -z "{{OUT}}" ]; then echo "INPUT/OUT are required (set env vars)"; exit 2; fi
    @just _docker -- run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input:ro" -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'cd /app && test -f /output/config.yaml || (echo "Missing /output/config.yaml (run UI Save first)"; exit 2); python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output engine={{ENGINE}} --cores {{THREADS}} {{ARGS}} -- report'

run-out-ps: build-if-needed-ps
    @powershell.exe -NoProfile -ExecutionPolicy Bypass -Command '$ErrorActionPreference = "Stop"; $ctx = (docker context show).Trim(); if ($ctx -ne "default") { Write-Warning ("docker context is " + $ctx + " (expected default). Use: docker context use default") }; if (-not $env:INPUT -or -not $env:OUT) { throw "INPUT/OUT are required (set env vars)" }; if (-not (Test-Path $env:INPUT)) { throw "INPUT は Windows 側の絶対パス（例: D:\\）を設定してください" }; $cfgPath = Join-Path $env:OUT "config.yaml"; if (-not (Test-Path $cfgPath)) { throw ("UI で Save して /output/config.yaml を生成してから実行してください。") }; $runArgs = @("run","--rm","--mount",("type=bind,src={{REPO}},target=/app"),"--mount",("type=bind,src=" + $env:INPUT + ",target=/input,readonly"),"--mount",("type=bind,src=" + $env:OUT + ",target=/output"),"{{IMAGE}}","python","-m","snakemake","--directory","/output","-s","workflow/Snakefile","--configfile","/output/config.yaml","--config","input=/input","output=/output","engine={{ENGINE}}","--cores","{{THREADS}}"); if ($env:ARGS) { $runArgs += $env:ARGS.Split(" ") }; $runArgs += @("--","report"); $output = (& docker @runArgs 2>&1); $rc = $LASTEXITCODE; if ($output) { Write-Host $output }; if ($rc -ne 0 -and ($output -match "Directory cannot be locked|LockException|Another snakemake instance")) { Write-Host "UI コンテナが /output を使用中。UI を停止するか、別 run_id の OUT に切り替えてください"; }; exit $rc'

report-out: build
    if [ -z "{{INPUT}}" ] || [ -z "{{OUT}}" ]; then echo "INPUT/OUT are required (set env vars)"; exit 2; fi
    @just _docker -- run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input:ro" -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'cd /app && test -f /output/config.yaml || (echo "Missing /output/config.yaml (run UI Save first)"; exit 2); python -m snakemake --directory /output -s workflow/Snakefile --configfile /output/config.yaml --config input=/input output=/output engine={{ENGINE}} --cores {{THREADS}} {{ARGS}} -- report'

open-out:
    if [ -z "{{OUT}}" ]; then echo "OUT is required (set env var)"; exit 2; fi
    @echo "Report: {{OUT}}/report/report.html"

app: build-if-needed
    @echo "Starting UI... open http://127.0.0.1:8501"
    @just _docker -- run --rm -p 127.0.0.1:8501:8501 -e HOST_INPUT="{{INPUT}}" -e HOST_OUT="{{OUT}}" -v "{{REPO}}:/app" -v "{{INPUT}}:/input:ro" -v "{{OUT}}:/output" {{IMAGE}} bash -lc 'cd /app && streamlit run app/ui/app_ui.py --server.address 0.0.0.0 --server.port 8501 --server.headless true --browser.gatherUsageStats false --logger.level=warning'

app-ps: build-if-needed-ps
    @powershell.exe -NoProfile -ExecutionPolicy Bypass -Command '$ctx = (docker context show).Trim(); if ($ctx -ne "default") { Write-Warning ("docker context is " + $ctx + " (expected default). Use: docker context use default") }; if (-not $env:INPUT -or -not $env:OUT) { throw "INPUT/OUT are required" }; if (-not (Test-Path $env:INPUT)) { throw "INPUT は Windows 側の絶対パス（例: D:\\）を設定してください" }; if (-not (Test-Path $env:OUT)) { throw "OUT は Windows 側の絶対パスを設定してください" }; Write-Host "Starting UI... open http://127.0.0.1:8501"; docker run --rm -p 127.0.0.1:8501:8501 -e ("HOST_INPUT=" + $env:INPUT) -e ("HOST_OUT=" + $env:OUT) -e PYTHONPATH=/app -w /app --mount "type=bind,src={{REPO}},target=/app" --mount ("type=bind,src=" + $env:INPUT + ",target=/input,readonly") --mount ("type=bind,src=" + $env:OUT + ",target=/output") "{{IMAGE}}" streamlit run app/ui/app_ui.py --server.address 0.0.0.0 --server.port 8501 --server.headless true --browser.gatherUsageStats false --logger.level=warning'

ui-ps: app-ps

srr: build-if-needed
    @set -e; \
      if [ -n "{{RUN_TABLE}}" ]; then mode="run_table"; src="{{RUN_TABLE}}"; \
      elif [ -n "{{SRR_LIST}}" ]; then mode="srr_list"; src="{{SRR_LIST}}"; \
      elif [ -n "{{SRR}}" ]; then mode="runs"; \
      else echo "Set one input source: RUN_TABLE=... or SRR_LIST=... or SRR=\"SRRxxxx SRRyyyy\""; exit 2; fi; \
      force_arg=""; \
      if [ "{{SRR_FORCE}}" = "1" ]; then force_arg="--force"; fi; \
      if [ -n "{{CONDITION_MAP}}" ] && [ ! -f "{{CONDITION_MAP}}" ]; then echo "CONDITION_MAP not found: {{CONDITION_MAP}}"; exit 2; fi; \
      if [ "$mode" = "run_table" ] || [ "$mode" = "srr_list" ]; then \
        if [ ! -f "$src" ]; then echo "Input file not found: $src"; exit 2; fi; \
        if [ -n "{{CONDITION_MAP}}" ]; then \
          RUN_ID=$(just _docker -- run --rm --mount "type=bind,src={{REPO}},target=/app" --mount "type=bind,src=$src,target=/ext/input,readonly" --mount "type=bind,src={{CONDITION_MAP}},target=/ext/condition_map,readonly" {{IMAGE}} python /app/scripts/srr_fetch.py --repo-root /app --input-file /ext/input --condition-from "{{CONDITION_FROM}}" --condition-map /ext/condition_map $force_arg --emit-run-id); \
        else \
          RUN_ID=$(just _docker -- run --rm --mount "type=bind,src={{REPO}},target=/app" --mount "type=bind,src=$src,target=/ext/input,readonly" {{IMAGE}} python /app/scripts/srr_fetch.py --repo-root /app --input-file /ext/input --condition-from "{{CONDITION_FROM}}" $force_arg --emit-run-id); \
        fi; \
      else \
        if [ -n "{{CONDITION_MAP}}" ]; then \
          RUN_ID=$(just _docker -- run --rm --mount "type=bind,src={{REPO}},target=/app" --mount "type=bind,src={{CONDITION_MAP}},target=/ext/condition_map,readonly" {{IMAGE}} python /app/scripts/srr_fetch.py --repo-root /app --runs {{SRR}} --condition-map /ext/condition_map $force_arg --emit-run-id); \
        else \
          RUN_ID=$(just _docker -- run --rm --mount "type=bind,src={{REPO}},target=/app" {{IMAGE}} python /app/scripts/srr_fetch.py --repo-root /app --runs {{SRR}} $force_arg --emit-run-id); \
        fi; \
      fi; \
      echo "run_id=$RUN_ID"; \
      echo "Next (PowerShell): \$env:INPUT='{{REPO}}/data_in/srr/$RUN_ID'; \$env:OUT='{{REPO}}/data_out/$RUN_ID'; just app"; \
      echo "Next (cmd.exe): set INPUT={{REPO}}/data_in/srr/$RUN_ID & set OUT={{REPO}}/data_out/$RUN_ID & just app"

srr-ps: build-if-needed-ps
    @powershell.exe -NoProfile -ExecutionPolicy Bypass -Command '$ErrorActionPreference="Stop"; $ctx = (docker context show).Trim(); if ($ctx -ne "default") { Write-Warning ("docker context is " + $ctx + " (expected default). Use: docker context use default") }; if ($env:RUN_TABLE) { $mode="run_table"; $src=$env:RUN_TABLE } elseif ($env:SRR_LIST) { $mode="srr_list"; $src=$env:SRR_LIST } elseif ($env:SRR) { $mode="runs" } else { throw "Set one input source: RUN_TABLE=... or SRR_LIST=... or SRR=`"SRRxxxx SRRyyyy`"" }; $forceArg=@(); if ($env:SRR_FORCE -eq "1") { $forceArg=@("--force") }; if ($env:CONDITION_MAP -and -not (Test-Path $env:CONDITION_MAP)) { throw ("CONDITION_MAP not found: " + $env:CONDITION_MAP) }; if (($mode -eq "run_table" -or $mode -eq "srr_list") -and -not (Test-Path $src)) { throw ("Input file not found: " + $src) }; $args=@("run","--rm","--mount",("type=bind,src={{REPO}},target=/app")); if ($mode -eq "run_table" -or $mode -eq "srr_list") { $args += @("--mount",("type=bind,src=" + $src + ",target=/ext/input,readonly")) }; if ($env:CONDITION_MAP) { $args += @("--mount",("type=bind,src=" + $env:CONDITION_MAP + ",target=/ext/condition_map,readonly")) }; $args += @("{{IMAGE}}","python","/app/scripts/srr_fetch.py","--repo-root","/app"); if ($mode -eq "run_table" -or $mode -eq "srr_list") { $args += @("--input-file","/ext/input"); if ($env:CONDITION_FROM) { $args += @("--condition-from",$env:CONDITION_FROM) } } else { $runs = ($env:SRR -split "\s+") | Where-Object { $_ -ne "" }; $args += @("--runs") + $runs }; if ($env:CONDITION_MAP) { $args += @("--condition-map","/ext/condition_map") }; $args += $forceArg + @("--emit-run-id"); $runId = (& docker @args).Trim(); if (-not $runId) { throw "Failed to obtain run_id" }; Write-Host ("run_id=" + $runId); $nextIn = Join-Path "{{REPO}}" ("data_in\srr\" + $runId); $nextOut = Join-Path "{{REPO}}" ("data_out\srr\" + $runId); $env:INPUT = $nextIn; $env:OUT = $nextOut; Write-Host ("Starting UI... open http://127.0.0.1:8501"); docker run --rm -p 127.0.0.1:8501:8501 -e ("HOST_INPUT=" + $env:INPUT) -e ("HOST_OUT=" + $env:OUT) -e PYTHONPATH=/app -w /app --mount "type=bind,src={{REPO}},target=/app" --mount ("type=bind,src=" + $env:INPUT + ",target=/input,readonly") --mount ("type=bind,src=" + $env:OUT + ",target=/output") "{{IMAGE}}" streamlit run app/ui/app_ui.py --server.address 0.0.0.0 --server.port 8501 --server.headless true --browser.gatherUsageStats false --logger.level=warning'

ui-import-check-ps: build-if-needed-ps
    @powershell.exe -NoProfile -ExecutionPolicy Bypass -Command '$ctx = (docker context show).Trim(); if ($ctx -ne "default") { Write-Warning ("docker context is " + $ctx + " (expected default). Use: docker context use default") }; docker run --rm --mount "type=bind,src={{REPO}},target=/app" -w /app -e PYTHONPATH=/app "{{IMAGE}}" python -c "import app; import app.ui.i18n; print(''OK'')"'

ui: app

launcher-web:
    @echo "Deprecated: use just app"

launcher: launcher-web

test-tximport: build
    just _docker -- run --rm -v "{{REPO}}:/app" rnaseq_pipeline bash -lc 'cd /app && rm -rf tests/tximport_mismatch/out && python -m snakemake -s tests/tximport_mismatch/Snakefile --cores 1 -p'

test-tximport-rat-header: build
    just _docker -- run --rm -v "{{REPO}}:/app" rnaseq_pipeline bash -lc 'cd /app && rm -rf tests/tximport_rat_header/out && python -m snakemake -s tests/tximport_rat_header/Snakefile --cores 1 -p'

test-enrichment: build
    just _docker -- run --rm -v "{{REPO}}:/app" rnaseq_pipeline bash -lc 'cd /app && rm -rf tests/enrichment_fixture/out && python -m snakemake -s tests/enrichment_fixture/Snakefile --cores 1 -p'

git-sanity:
    python scripts/git_sanity.py

check-report-selfcontained PATH:
    just _docker -- run --rm -v "{{REPO}}:/app" rnaseq_pipeline bash -lc 'cd /app && p="{{PATH}}"; p="${p#REPORT=}"; python /app/scripts/check_report_selfcontained.py --report "$p"'

debug-report-externals:
    just _docker -- run --rm -v "{{OUT}}:/output" rnaseq_pipeline bash -lc 'python /app/scripts/check_report_selfcontained.py --report /output/report/report.html --print-externals --strict-links || true'

verify-real: build
    @just _docker -- run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input:ro" -v "{{OUT}}:/output" {{IMAGE}} bash -lc 'set -euo pipefail; test -d /input || { echo "Missing /input mount (set INPUT env var)"; exit 2; }; test -d /output || { echo "Missing /output mount (set OUT env var)"; exit 2; }; test -f /output/config.yaml; test -f /output/metadata/samples.tsv; samples=$(tail -n +2 /output/metadata/samples.tsv | cut -f1 | tr "\r" "\n"); for s in $samples; do test -f "/output/salmon/$s/quant.sf"; done; test -f /output/tximport/txi.tsv; engine=$(python -c "import yaml; cfg=yaml.safe_load(open('\''/output/config.yaml'\'')) or {}; print(cfg.get('\''engine'\'','\''real'\''))"); if [ "$engine" = "real" ]; then test -f /output/deseq2/results.tsv; fi; test -f /output/report/report.html; python /app/scripts/check_report_selfcontained.py --report /output/report/report.html {{SELFCONTAINED_ARGS}}; echo "Share these outputs:"; echo " - /output/report/report.html"; echo " - /output/run/config_resolved.yaml"; echo " - /output/run/versions.tsv"; echo " - /output/deseq2/results.tsv"'

check: verify-real
