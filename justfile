set dotenv-load := false

REPO := if os() == "windows" { `powershell -NoProfile -Command "(Get-Location).Path"` } else { invocation_directory() }

build:
    docker build -t rnaseq_pipeline .

smoke: build
    docker run --rm -v "{{REPO}}:/app" rnaseq_pipeline bash -lc "cd /app && python -m app run --input tests/data --output out --config tests/config.yaml --align none"

run INPUT OUTPUT CONFIG ALIGN="none": build
    docker run --rm -v "{{REPO}}:/app" -v "{{INPUT}}:/input:ro" -v "{{OUTPUT}}:/output" rnaseq_pipeline bash -lc "cd /app && python -m app run --input /input --output /output --config '{{CONFIG}}' --align {{ALIGN}}"
