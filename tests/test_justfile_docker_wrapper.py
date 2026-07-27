from pathlib import Path


JUSTFILE = Path(__file__).resolve().parents[1] / "justfile"


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
