from pathlib import Path


SNAKEFILE = Path(__file__).resolve().parents[1] / "workflow" / "Snakefile"


def test_rule_all_precedes_wildcarded_fastp_rule():
    text = SNAKEFILE.read_text(encoding="utf-8")

    assert text.index("rule all:") < text.index("rule fastp:")
