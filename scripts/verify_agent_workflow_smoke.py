#!/usr/bin/env python3
"""Verify an existing agent workflow smoke without re-running it."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def verify(output: Path) -> dict:
    root = output.expanduser().resolve()
    summary_path = root / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["schema_version"] == 1
    assert summary["smoke"] == "harako-agent-workflow"
    assert summary["raw_fastq_content_serialized"] is False
    assert summary["secret_data_serialized"] is False
    assert summary["production_reference_downloaded"] is False
    assert summary["dry_run_adapter"] in {"snakemake", "deterministic-adapter-seam"}

    differential = summary["differential"]
    assert differential["status"] == "completed"
    assert differential["analysis_mode"] == "differential"
    assert differential["de_results_available"] is True
    assert Path(differential["run_dir"]).is_dir()
    assert Path(differential["context"]).is_file()
    assert Path(differential["workspace"]).is_dir()
    for artifact in ("tximport_counts", "deseq2_results", "html_report", "approved_agent_plan"):
        assert artifact in differential["artifact_types"]

    qc_only = summary["qc_only"]
    assert qc_only["status"] == "completed"
    assert qc_only["analysis_mode"] == "qc_only"
    assert qc_only["de_results_available"] is False
    assert qc_only["inferential_artifacts_applicable"] is False
    assert Path(qc_only["run_dir"]).is_dir()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("output/agent_smoke"))
    args = parser.parse_args()
    summary = verify(args.output)
    print(
        "agent_smoke=ok "
        f"differential={summary['differential']['status']} "
        f"qc_only={summary['qc_only']['status']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
