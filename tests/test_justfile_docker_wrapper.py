import ast
import re
from pathlib import Path


JUSTFILE = Path(__file__).resolve().parents[1] / "justfile"
ROOT = JUSTFILE.parent


def _recipe(text: str, name: str) -> str:
    lines = text.splitlines()
    start = next(
        (index for index, line in enumerate(lines) if re.match(rf"^{re.escape(name)}(?:\s|:)", line)),
        None,
    )
    assert start is not None, f"missing recipe: {name}"
    body = []
    for line in lines[start + 1 :]:
        if line and not line[0].isspace() and not line.startswith("#"):
            break
        body.append(line)
    return "\n".join(body)


def test_docker_recipes_preserve_arguments_without_nested_wrappers():
    text = JUSTFILE.read_text(encoding="utf-8")

    assert 'export MSYS_NO_PATHCONV := "1"' in text
    assert 'export MSYS2_ARG_CONV_EXCL := "*"' in text
    assert "just _docker" not in text
    assert "_docker *ARGS:" not in text
    assert 'docker run --rm -e PYTHONPATH=/app -v "{{REPO}}:/app"' in text
    assert "-- fastp" not in text
    assert '"/app/$OUTREAL/fastp/sample1.fastq"' in text
    assert '2>&1 | tee "/app/$OUTREAL/fastp_real.log"' in text
    assert "print(streamlit.__version__)" in text


def test_ci_recipes_reuse_the_selected_image_without_duplicate_smoke():
    text = JUSTFILE.read_text(encoding="utf-8")
    ci = _recipe(text, "ci-docker")
    smoke = _recipe(text, "smoke")
    verify = _recipe(text, "verify-smoke")

    assert "ci-docker:" in text
    assert ci.count("docker build") == 1
    assert "docker tag" not in ci
    assert "just smoke" not in ci
    assert ci.count("verify-smoke") == 1
    assert "smoke: build-if-needed" in text
    assert verify.count("just IMAGE={{IMAGE}} smoke") == 1
    assert "just IMAGE={{IMAGE}} check-report-selfcontained" in verify
    assert "rnaseq_pipeline" not in smoke
    assert "{{IMAGE}}" in smoke
    assert "{{IMAGE}}" in verify


def test_docker_diagnostics_use_build_if_needed_and_selected_image():
    text = JUSTFILE.read_text(encoding="utf-8")
    for name in (
        "test-tximport",
        "test-tximport-rat-header",
        "test-enrichment",
        "check-report-selfcontained",
    ):
        recipe = _recipe(text, name)
        header = next(line for line in text.splitlines() if line.startswith(f"{name}"))
        assert "build-if-needed" in header
        assert "{{IMAGE}}" in recipe
        assert " rnaseq_pipeline " not in recipe


def test_test_style_files_are_collected_or_one_documented_script_diagnostic():
    text = JUSTFILE.read_text(encoding="utf-8")
    standalone = set()
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        has_test = any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
            for node in tree.body
        )
        marker = "Pytest collection: standalone Docker/Snakemake diagnostic"
        if has_test:
            assert f"python tests/{path.name}" not in text
        else:
            assert marker in source, path.name
            assert text.count(f"python tests/{path.name}") == 1
            standalone.add(path.name)

    assert standalone == {
        "test_dag_fastp.py",
        "test_snakemake_cli_compat.py",
        "test_species_dry_run.py",
    }


def test_local_launch_modes_are_explicit_and_keep_release_isolated_from_source():
    text = JUSTFILE.read_text(encoding="utf-8")
    app = _recipe(text, "app")
    release = _recipe(text, "app-release")
    release_unix = _recipe(text, "app-release-unix")
    release_ps = _recipe(text, "app-release-ps")
    dev_unix = _recipe(text, "app-dev-fast-unix")
    dev_ps = _recipe(text, "app-dev-fast-ps")
    build = _recipe(text, "app-build")

    exact_image = "ghcr.io/do-shima/harako-rnaseq:v0.3.0-beta.2"
    assert f'PUBLISHED_IMAGE := env_var_or_default("PUBLISHED_IMAGE", "{exact_image}")' in text
    assert "app: app-release" in text
    assert app == ""
    assert "app-release-" in release
    assert release.count("@just app-release-") == 1
    assert '_app-unix release "{{PUBLISHED_IMAGE}}" 0' in release_unix
    assert "-Mode release" in release_ps
    assert '_app-unix source_overlay "{{PUBLISHED_IMAGE}}" 1' in dev_unix
    assert "-Mode source_overlay" in dev_ps
    assert "app-build-" in build
    assert "app-build-unix: build" in text
    assert "app-build-ps: build-ps" in text
    assert "app-unix: app-release-unix" in text
    assert "app-ps: app-release-ps" in text

    for recipe in (app, release, release_unix, release_ps, dev_unix, dev_ps):
        assert "docker build" not in recipe
        assert "pip install" not in recipe
    assert ":latest" not in text
    assert "ghcr.io/do-shima/harako-rnaseq:beta" not in text


def test_fast_launch_mounts_and_pull_if_needed_are_guarded():
    text = JUSTFILE.read_text(encoding="utf-8")
    launcher = _recipe(text, "_app-unix")
    ensure_unix = _recipe(text, "_ensure-published-image-unix")
    ensure_ps = _recipe(text, "_ensure-published-image-ps")

    assert "target=/input,readonly" in launcher
    assert 'target=/output"' in launcher
    assert "target=/app" in launcher
    assert "127.0.0.1:{{APP_PORT}}:8501" in launcher
    assert 'docker image inspect "{{PUBLISHED_IMAGE}}"' in ensure_unix
    assert ensure_unix.count('docker pull "{{PUBLISHED_IMAGE}}"') == 1
    assert "published Harako image could not be obtained" in ensure_unix
    assert "docker build" not in ensure_unix
    assert 'docker image inspect "{{PUBLISHED_IMAGE}}"' in ensure_ps
    assert ensure_ps.count('docker pull "{{PUBLISHED_IMAGE}}"') == 1
    assert "published Harako image could not be obtained" in ensure_ps
    assert "docker build" not in ensure_ps


def test_full_source_launcher_always_builds_before_starting():
    text = JUSTFILE.read_text(encoding="utf-8")
    build_unix = _recipe(text, "app-build-unix")
    build_ps = _recipe(text, "app-build-ps")
    assert "app-build-unix: build" in text
    assert "app-build-ps: build-ps" in text
    assert '_app-unix source "{{IMAGE}}" 1' in build_unix
    assert "-Mode source" in build_ps
    assert "_build-app-if-needed" not in text


def test_source_overlay_checks_release_dependency_contract_before_launch():
    text = JUSTFILE.read_text(encoding="utf-8")
    launcher = _recipe(text, "_app-unix")
    dependency_files = (
        "Dockerfile requirements.in requirements.lock.txt scripts/install_tools.sh "
        "config/copyleft-r-sources.yaml"
    )
    assert text.count(f'RUNTIME_DEPENDENCY_FILES := "{dependency_files}"') == 1
    assert 'git rev-parse --verify "{{PUBLISHED_RUNTIME_TAG}}^{commit}"' in launcher
    assert 'git diff --quiet "{{PUBLISHED_RUNTIME_TAG}}" -- {{RUNTIME_DEPENDENCY_FILES}}' in launcher
    assert "git fetch --tags origin" in launcher
    assert "Use just app-build" in launcher
