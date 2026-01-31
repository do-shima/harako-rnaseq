set dotenv-load := false

REPO := if os() == "windows" { `powershell -NoProfile -Command "(Get-Location).Path"` } else { invocation_directory() }
ENGINE := env_var_or_default("ENGINE", "real")
THREADS := env_var_or_default("THREADS", "1")
ARGS := env_var_or_default("ARGS", "")

build:
    docker build -t rnaseq_pipeline .

smoke: build
    docker run --rm -v "{{REPO}}:/app" rnaseq_pipeline bash -lc "cd /app && python -m app run --input tests/data --output out --config tests/config.yaml --align none"

init: build
    docker run --rm -it -v "{{REPO}}:/app" rnaseq_pipeline bash -lc "cd /app && python -m app init"

validate CONFIG:
    docker run --rm -it -v "{{REPO}}:/app" rnaseq_pipeline bash -lc \
      "cd /app && python -m app validate --config '{{CONFIG}}' {{ARGS}}"

run INPUT OUTPUT CONFIG ALIGN="none": build
    docker run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input:ro" -v "{{OUTPUT}}:/output" rnaseq_pipeline bash -lc "cd /app && python -m app run --input /input --output /output --config '{{CONFIG}}' --align {{ALIGN}} --engine {{ENGINE}} --threads {{THREADS}} {{ARGS}}"
