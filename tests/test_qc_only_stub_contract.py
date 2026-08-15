from __future__ import annotations

import json
import runpy
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


class NamedIO(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


def plan(mode: str = "qc_only") -> dict[str, object]:
    differential = mode == "differential"
    return {
        "schema_version": 1,
        "policy_version": 1,
        "mode": mode,
        "structurally_valid": True,
        "eligible_for_de": differential,
        "reason_code": "eligible" if differential else "single_condition",
        "condition_counts": {"A": 2, "B": 2} if differential else {"A": 1},
        "total_samples": 4 if differential else 1,
        "contrast_allowed": differential,
        "enrichment_allowed": differential,
    }


def run_deseq_stub(tmp_path: Path, analysis_plan: dict[str, object]) -> NamedIO:
    outputs = NamedIO(
        results=str(tmp_path / "deseq2" / "results.tsv"),
        status=str(tmp_path / "deseq2" / "status.json"),
        normalized=str(tmp_path / "deseq2" / "normalized_counts.tsv"),
        pca=str(tmp_path / "deseq2" / "pca.png"),
        heatmap=str(tmp_path / "deseq2" / "sample_distance_heatmap.png"),
        ma=str(tmp_path / "deseq2" / "ma_plot.png"),
    )
    fake = SimpleNamespace(
        input=NamedIO(counts=str(tmp_path / "tximport" / "txi.tsv")),
        output=outputs,
        params={"analysis_plan": analysis_plan, "library_protocol": "full_length"},
        config={"samples": ["s1"] if analysis_plan["mode"] == "qc_only" else ["a1", "a2", "b1", "b2"]},
    )
    runpy.run_path(
        str(ROOT / "scripts" / "deseq2_stub.py"),
        init_globals={"snakemake": fake},
    )
    return outputs


def test_qc_only_stub_writes_header_only_results_and_status(tmp_path):
    outputs = run_deseq_stub(tmp_path, plan())
    lines = Path(outputs["results"]).read_text(encoding="utf-8").splitlines()
    assert lines == [
        "contrast\tgene_id\tbaseMean\tlog2FoldChange\tlfcSE\tstat\tpvalue\tpadj"
    ]
    status = json.loads(Path(outputs["status"]).read_text(encoding="utf-8"))
    assert status["mode"] == "qc_only"
    assert status["differential_results_available"] is False
    assert status["pca_available"] is False
    assert status["sample_distance_available"] is False
    assert status["ma_plot_available"] is False
    for key in ("normalized", "pca", "heatmap", "ma"):
        assert Path(outputs[key]).is_file()


def test_differential_stub_retains_standard_result_columns(tmp_path):
    outputs = run_deseq_stub(tmp_path, plan("differential"))
    lines = Path(outputs["results"]).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert lines[0].split("\t") == [
        "contrast",
        "gene_id",
        "baseMean",
        "log2FoldChange",
        "lfcSE",
        "stat",
        "pvalue",
        "padj",
    ]
    status = json.loads(Path(outputs["status"]).read_text(encoding="utf-8"))
    assert status["differential_results_available"] is True
    assert status["enrichment_allowed"] is True


def test_stub_qc_summary_consumes_status(tmp_path):
    deseq_outputs = run_deseq_stub(tmp_path, plan())
    qc_outputs = NamedIO(
        summary_tsv=str(tmp_path / "deseq2" / "qc_summary.tsv"),
        summary_json=str(tmp_path / "deseq2" / "qc_summary.json"),
        padj_hist=str(tmp_path / "deseq2" / "padj_hist.png"),
        lfc_hist=str(tmp_path / "deseq2" / "lfc_hist.png"),
        mean_vs_lfc=str(tmp_path / "deseq2" / "mean_vs_lfc.png"),
        volcano=str(tmp_path / "deseq2" / "volcano.png"),
    )
    fake = SimpleNamespace(
        input=NamedIO(
            results=deseq_outputs["results"],
            status=deseq_outputs["status"],
        ),
        output=qc_outputs,
    )
    runpy.run_path(
        str(ROOT / "scripts" / "deseq2_qc_stub.py"),
        init_globals={"snakemake": fake},
    )
    summary = json.loads(Path(qc_outputs["summary_json"]).read_text(encoding="utf-8"))
    assert summary["analysis_mode"] == "qc_only"
    assert summary["inferential_qc_plots_available"] is False
    for key in ("padj_hist", "lfc_hist", "mean_vs_lfc", "volcano"):
        assert Path(qc_outputs[key]).is_file()


def test_stub_report_has_qc_only_banner_and_no_input_path(tmp_path):
    deseq_outputs = run_deseq_stub(tmp_path, plan())
    report_path = tmp_path / "report" / "report.html"
    fake = SimpleNamespace(
        input=NamedIO(
            results=deseq_outputs["results"],
            status=deseq_outputs["status"],
        ),
        output=NamedIO(html=str(report_path)),
        config={"species": "mouse", "reference_provenance": {}},
    )
    runpy.run_path(
        str(ROOT / "scripts" / "report_stub.py"),
        init_globals={"snakemake": fake},
    )
    html = report_path.read_text(encoding="utf-8")
    assert "QC-only analysis" in html
    assert "differential expression analysis was not performed" in html
    assert "differential expression results are unavailable, so enrichment was not run" in html
    assert "Only one condition was provided (single_condition)" in html
    assert str(tmp_path) not in html


def test_snakefile_status_and_enrichment_gate_are_explicit():
    text = (ROOT / "workflow" / "Snakefile").read_text(encoding="utf-8")
    assert 'os.path.join(OUTDIR, "deseq2", "status.json")' in text
    assert 'ANALYSIS_MODE == "differential"' in text
    assert 'ANALYSIS_PLAN.get("enrichment_allowed")' in text
