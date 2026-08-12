#!/usr/bin/env python3
"""Run the deterministic command-level smoke for Harako's agent interface."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml
from typer.testing import CliRunner

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import app.agent as agent_module
import app.agent_cli as agent_cli_module
from app.cli import app


RAW_MARKER = "RAW_FASTQ_SEQUENCE_MUST_NOT_APPEAR"
SECRET_MARKER = "HARAKO_AGENT_SMOKE_SECRET_MUST_NOT_APPEAR"
RUNNER = CliRunner()


def _invoke(arguments: list[str], expected: int = 0) -> dict[str, Any]:
    result = RUNNER.invoke(app, ["agent", *arguments])
    if result.exit_code != expected:
        raise AssertionError(
            f"agent {' '.join(arguments)} exited {result.exit_code}, expected {expected}:\n{result.stdout}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"agent command did not emit one JSON object: {result.stdout!r}") from exc
    assert payload["schema_version"] == 1
    assert payload["harako_version"]
    return payload


def _write_fixture_reference(root: Path) -> tuple[Path, Path]:
    preset = "mouse_ensembl_grcm39"
    release = "release-agent-smoke"
    cache = root / "refs_cache"
    bundle = cache / preset / release
    bundle.mkdir(parents=True)
    contents = {
        "transcripts_fasta_url": b">tx1\nACGT\n",
        "genome_fasta_url": b">chr1\nACGT\n",
        "gtf_url": b"chr1\tsmoke\tgene\t1\t4\t.\t+\t.\tgene_id \"gene1\";\n",
    }
    names = {
        "transcripts_fasta_url": "transcripts.fa.gz",
        "genome_fasta_url": "genome.fa.gz",
        "gtf_url": "annotation.gtf.gz",
    }
    hashes: dict[str, str] = {}
    for key, content in contents.items():
        (bundle / names[key]).write_bytes(content)
        hashes[key] = hashlib.sha256(content).hexdigest()
    manifest = {
        "schema_version": 2,
        "aliases": {},
        "preset_metadata": {
            preset: {
                "provider": "Ensembl",
                "species": "mouse",
                "assembly": "GRCm39",
                "annotation_release": "agent-smoke",
                "display_name": "Mouse agent smoke fixture",
                "pinned_release": release,
            }
        },
        "presets": {
            preset: {
                release: {
                    "transcripts_fasta_url": "https://example.invalid/transcripts",
                    "genome_fasta_url": "https://example.invalid/genome",
                    "gtf_url": "https://example.invalid/annotation",
                    "sha256": hashes,
                }
            }
        },
    }
    manifest_path = root / "ref_manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return manifest_path, cache


def _write_fastqs(root: Path, samples: list[str]) -> None:
    root.mkdir(parents=True)
    for sample in samples:
        for read in ("R1", "R2"):
            (root / f"{sample}_{read}.fastq.gz").write_text(
                f"{RAW_MARKER}:{sample}:{read}\n", encoding="utf-8"
            )


def _stub_executor(config_path: Path, plan: dict[str, Any], run_dir: Path) -> int:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    samples = [row["sample"] for row in plan["samples"]]
    mode = plan["analysis_plan"]["mode"]

    (run_dir / "run" / "manifest.json").write_text(
        json.dumps({"run_id": run_dir.name, "engine": config["engine"]}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_dir / "run" / "versions.tsv").write_text(
        "key\tvalue\nagent_smoke_executor\tdeterministic-stub\n", encoding="utf-8"
    )
    for sample in samples:
        (run_dir / "fastp").mkdir(exist_ok=True)
        (run_dir / "fastp" / f"{sample}.json").write_text("{}\n", encoding="utf-8")
        (run_dir / "fastp" / f"{sample}.html").write_text("<html></html>\n", encoding="utf-8")
        salmon = run_dir / "salmon" / sample
        salmon.mkdir(parents=True)
        (salmon / "quant.sf").write_text(
            "Name\tLength\tEffectiveLength\tTPM\tNumReads\ntx1\t4\t4\t1\t1\n", encoding="utf-8"
        )

    tximport = run_dir / "tximport"
    tximport.mkdir()
    header = "gene\t" + "\t".join(samples) + "\n"
    values = "gene1\t" + "\t".join("1" for _ in samples) + "\n"
    (tximport / "txi.tsv").write_text(header + values, encoding="utf-8")
    (tximport / "tpm.tsv").write_text(header + values, encoding="utf-8")

    deseq2 = run_dir / "deseq2"
    deseq2.mkdir()
    de_available = mode == "differential"
    (deseq2 / "status.json").write_text(
        json.dumps(
            {
                "mode": mode,
                "differential_results_available": de_available,
                "pca_available": True,
                "sample_distance_available": True,
                "enrichment_allowed": de_available,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (deseq2 / "pca.png").write_bytes(b"smoke-pca")
    (deseq2 / "sample_distance_heatmap.png").write_bytes(b"smoke-distance")
    if de_available:
        (deseq2 / "normalized_counts.tsv").write_text(header + values, encoding="utf-8")
        (deseq2 / "results.tsv").write_text("gene\tlog2FoldChange\tpadj\ngene1\t1\t0.05\n", encoding="utf-8")
        (deseq2 / "ma.png").write_bytes(b"smoke-ma")
        (deseq2 / "volcano.png").write_bytes(b"smoke-volcano")

    report = run_dir / "report"
    report.mkdir()
    (report / "report.html").write_text("<!doctype html><html><body>agent smoke</body></html>\n", encoding="utf-8")
    return 0


def _stub_dry_run(config_path: Path, plan: dict[str, Any], output_dir: Path) -> tuple[int, str]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    assert config["engine"] == "real"
    assert config["analysis_plan"] == plan["analysis_plan"]
    assert config["output"] == str(output_dir)
    assert Path(config["sample_table"]).is_file()
    return 0, "rule report:\n    input: smoke\n1 job\n"


def _invoke_dry_run(plan_path: Path, *, real_dry_run: bool) -> dict[str, Any]:
    if real_dry_run:
        return _invoke(["dry-run", "--plan", str(plan_path)])
    original_dry_run = agent_cli_module.dry_run_plan
    agent_cli_module.dry_run_plan = lambda envelope: agent_module.dry_run_plan(
        envelope, runner=_stub_dry_run
    )
    try:
        return _invoke(["dry-run", "--plan", str(plan_path)])
    finally:
        agent_cli_module.dry_run_plan = original_dry_run


def _plan_arguments(
    *, table: Path, fastq_root: Path, output: Path, manifest: Path, cache: Path, project: str, plan: Path,
    contrast_ref: str | None = None,
) -> list[str]:
    arguments = [
        "plan", "--samples", str(table), "--input", str(fastq_root), "--output", str(output),
        "--project-name", project, "--species", "mouse", "--ref-preset", "mouse_ensembl_grcm39",
        "--ref-release", "release-agent-smoke", "--ref-manifest", str(manifest),
        "--ref-cache-dir", str(cache), "--threads", "1", "--plan", str(plan),
    ]
    if contrast_ref is not None:
        arguments.extend(["--contrast-mode", "ref", "--contrast-ref", contrast_ref])
    return arguments


def _snapshot(run_dir: Path) -> dict[str, str]:
    return {
        path.relative_to(run_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(run_dir.rglob("*"))
        if path.is_file()
    }


def _run_differential(
    root: Path, manifest: Path, cache: Path, *, real_dry_run: bool
) -> dict[str, Any]:
    work = root / "differential"
    fastq_root = work / "fastq"
    samples = ["Con_1", "Con_2", "STZ_1", "STZ_2"]
    _write_fastqs(fastq_root, samples)
    output = work / "output"
    output.mkdir()

    inspection_path = work / "inspection.json"
    inspection = _invoke(["inspect-input", "--input", str(fastq_root), "--output", str(inspection_path)])
    paths = [item["path"] for item in inspection["fastq_files"]]
    assert paths == sorted(paths)
    assert RAW_MARKER not in json.dumps(inspection)

    proposed_table = work / "proposed.tsv"
    proposal = _invoke(
        ["propose-samples", "--inspection", str(inspection_path), "--output", str(proposed_table)]
    )
    assert proposal["conditions_inferred"] is False
    assert all(row["pairing_status"] == "paired" and row["condition"] == "" for row in proposal["samples"])

    condition_map = work / "conditions.tsv"
    condition_map.write_text(
        "sample\tcondition\nCon_1\tControl\nCon_2\tControl\nSTZ_1\tSTZ\nSTZ_2\tSTZ\n",
        encoding="utf-8",
    )
    table = work / "samples.tsv"
    approved = _invoke(
        [
            "propose-samples", "--inspection", str(inspection_path), "--condition-map", str(condition_map),
            "--output", str(table), "--report", str(work / "approved-samples.json"),
        ]
    )
    assert {row["sample"]: row["condition"] for row in approved["samples"]} == {
        "Con_1": "Control", "Con_2": "Control", "STZ_1": "STZ", "STZ_2": "STZ"
    }

    plan_path = work / "harako-plan.yaml"
    plan = _invoke(
        _plan_arguments(
            table=table, fastq_root=fastq_root, output=output, manifest=manifest, cache=cache,
            project="agent-differential", plan=plan_path, contrast_ref="Control",
        )
    )
    repeat_path = work / "harako-plan-repeat.yaml"
    repeat = _invoke(
        _plan_arguments(
            table=table, fastq_root=fastq_root, output=output, manifest=manifest, cache=cache,
            project="agent-differential", plan=repeat_path, contrast_ref="Control",
        )
    )
    assert (plan["plan_id"], plan["approval_hash"]) == (repeat["plan_id"], repeat["approval_hash"])
    assert plan["analysis_plan"]["mode"] == "differential"
    assert plan["reference"]["canonical_preset"] == "mouse_ensembl_grcm39"
    assert plan["reference"]["checksum_verified"] is True
    assert plan["contrasts"]["reference"] == "Control"

    validation = _invoke(["validate-plan", "--plan", str(plan_path)])
    assert validation["valid"] is True and validation["executable"] is True
    dry_run = _invoke_dry_run(plan_path, real_dry_run=real_dry_run)
    assert dry_run["valid"] is True and dry_run["dry_run_satisfies_approval"] is False

    refused = _invoke(["execute", "--plan", str(plan_path)], expected=3)
    assert refused["reason_code"] == "approval_required"
    wrong = _invoke(["execute", "--plan", str(plan_path), "--approve", "0" * 64], expected=3)
    assert wrong["reason_code"] == "approval_or_validation_failed"

    original_execute = agent_cli_module.execute_plan
    agent_cli_module.execute_plan = lambda envelope, approval: agent_module.execute_plan(
        envelope, approval=approval, executor=_stub_executor
    )
    try:
        executed = _invoke(
            ["execute", "--plan", str(plan_path), "--approve", plan["approval_hash"]]
        )
    finally:
        agent_cli_module.execute_plan = original_execute
    assert executed["state"] == "completed" and executed["exit_code"] == 0
    run_dir = Path(executed["run_dir"])

    status = _invoke(["status", "--run-dir", str(run_dir)])
    assert status["state"] == "completed" and status["analysis_mode"] == "differential"
    assert status["de_results_available"] is True
    artifacts = _invoke(["artifacts", "--run-dir", str(run_dir)])
    artifact_map = {item["artifact_type"]: item for item in artifacts["artifacts"]}
    for artifact_type in ("tximport_counts", "deseq2_results", "html_report", "approved_agent_plan"):
        assert artifact_map[artifact_type]["exists"] is True

    context_path = work / "agent-context.json"
    os.environ["HARAKO_AGENT_SMOKE_SECRET"] = SECRET_MARKER
    context = _invoke(["context", "--run-dir", str(run_dir), "--output", str(context_path)])
    encoded_context = json.dumps(context)
    assert SECRET_MARKER not in encoded_context and RAW_MARKER not in encoded_context
    assert all(not Path(item["relative_path"]).is_absolute() for item in context["artifacts"])

    before = _snapshot(run_dir)
    post = _invoke(
        [
            "post-analysis-init", "--run-dir", str(run_dir), "--name", "pathway-review",
            "--question", "Review stress-response pathways",
        ]
    )
    workspace = Path(post["workspace"])
    assert workspace == run_dir.parent / "post_analysis" / "pathway-review"
    assert workspace.is_dir() and _snapshot(run_dir) == before
    return {
        "plan_id": plan["plan_id"], "approval_hash": plan["approval_hash"], "run_dir": str(run_dir),
        "workspace": str(workspace), "status": status["state"], "analysis_mode": status["analysis_mode"],
        "de_results_available": status["de_results_available"], "context": str(context_path),
        "artifact_types": sorted(item["artifact_type"] for item in artifacts["artifacts"] if item["exists"]),
    }


def _run_qc_only(
    root: Path, manifest: Path, cache: Path, *, real_dry_run: bool
) -> dict[str, Any]:
    work = root / "qc_only"
    fastq_root = work / "fastq"
    _write_fastqs(fastq_root, ["QC_1", "QC_2"])
    output = work / "output"
    output.mkdir()
    inspection_path = work / "inspection.json"
    _invoke(["inspect-input", "--input", str(fastq_root), "--output", str(inspection_path)])
    condition_map = work / "conditions.tsv"
    condition_map.write_text("sample\tcondition\nQC_1\tControl\nQC_2\tControl\n", encoding="utf-8")
    table = work / "samples.tsv"
    _invoke(
        [
            "propose-samples", "--inspection", str(inspection_path), "--condition-map", str(condition_map),
            "--output", str(table),
        ]
    )
    plan_path = work / "harako-plan.yaml"
    plan = _invoke(
        _plan_arguments(
            table=table, fastq_root=fastq_root, output=output, manifest=manifest, cache=cache,
            project="agent-qc-only", plan=plan_path,
        )
    )
    assert plan["analysis_plan"]["mode"] == "qc_only"
    assert plan["contrasts"] == {"mode": None, "reference": None, "pairs": [], "active": False}
    assert plan["enrichment"]["enabled"] is False
    validation = _invoke(["validate-plan", "--plan", str(plan_path)])
    assert validation["valid"] is True and validation["executable"] is True
    _invoke_dry_run(plan_path, real_dry_run=real_dry_run)

    original_execute = agent_cli_module.execute_plan
    agent_cli_module.execute_plan = lambda envelope, approval: agent_module.execute_plan(
        envelope, approval=approval, executor=_stub_executor
    )
    try:
        executed = _invoke(["execute", "--plan", str(plan_path), "--approve", plan["approval_hash"]])
    finally:
        agent_cli_module.execute_plan = original_execute
    run_dir = Path(executed["run_dir"])
    status = _invoke(["status", "--run-dir", str(run_dir)])
    artifacts = _invoke(["artifacts", "--run-dir", str(run_dir)])
    de_result = next(item for item in artifacts["artifacts"] if item["artifact_type"] == "deseq2_results")
    assert status["state"] == "completed" and status["analysis_mode"] == "qc_only"
    assert status["de_results_available"] is False
    assert de_result["applicable"] is False and de_result["exists"] is False
    return {
        "plan_id": plan["plan_id"], "approval_hash": plan["approval_hash"], "run_dir": str(run_dir),
        "status": status["state"], "analysis_mode": status["analysis_mode"],
        "de_results_available": status["de_results_available"], "inferential_artifacts_applicable": False,
    }


def run(output: Path, *, real_dry_run: bool = False) -> Path:
    output = output.expanduser().resolve()
    if output.name != "agent_smoke" or output.parent.name != "output":
        raise ValueError("Agent smoke output must be the repository-local output/agent_smoke directory.")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    fixture = output / "fixture"
    fixture.mkdir()
    manifest, cache = _write_fixture_reference(fixture)
    differential = _run_differential(output, manifest, cache, real_dry_run=real_dry_run)
    qc_only = _run_qc_only(output, manifest, cache, real_dry_run=real_dry_run)
    summary = {
        "schema_version": 1,
        "smoke": "harako-agent-workflow",
        "differential": differential,
        "qc_only": qc_only,
        "raw_fastq_content_serialized": False,
        "secret_data_serialized": False,
        "production_reference_downloaded": False,
        "execution_adapter": "deterministic-stub",
        "dry_run_adapter": "snakemake" if real_dry_run else "deterministic-adapter-seam",
    }
    summary_path = output / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return summary_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("output/agent_smoke"))
    parser.add_argument("--real-dry-run", action="store_true")
    args = parser.parse_args()
    run(args.output, real_dry_run=args.real_dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
