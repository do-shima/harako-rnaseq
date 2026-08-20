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
