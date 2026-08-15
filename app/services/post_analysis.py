"""Isolated post-analysis workspace initialization service."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from app.adapters.filesystem import sha256_file
from app.agent_contracts import AGENT_SCHEMA_VERSION, AgentInterfaceError, response, utc_now
from app.services.run_inspection import artifact_inventory, require_run_dir, run_status
from app.version import VERSION


SCHEMA_VERSION = AGENT_SCHEMA_VERSION

def init_post_analysis(run_dir: Path, name: str, question: str = "") -> dict[str, Any]:
    run = require_run_dir(run_dir)
    analysis_id = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-._")
    if not analysis_id:
        raise AgentInterfaceError("Post-analysis name must contain a letter or number.")
    workspace = run.parent / "post_analysis" / analysis_id
    if workspace.exists():
        raise AgentInterfaceError(f"Post-analysis workspace already exists: {workspace}")
    for directory in ("scripts", "figures", "tables", "reports", "logs", "environment"):
        (workspace / directory).mkdir(parents=True, exist_ok=False)
    status = run_status(run)
    inventory = artifact_inventory(run)
    selected = []
    hashable = {"run_manifest", "frozen_config", "sample_table", "tximport_counts", "gene_level_tpm", "deseq2_status", "deseq2_results"}
    for item in inventory["artifacts"]:
        if not item["exists"] or item["artifact_type"] not in hashable:
            continue
        path = run / item["relative_path"]
        selected.append({**item, "sha256": sha256_file(path) if path.stat().st_size <= 100 * 1024 * 1024 else None})
    created = utc_now()
    source_manifest = response(
        {
            "source_run_id": status.get("run_id"),
            "source_run_relative_path": run.name,
            "harako_version": VERSION,
            "analysis_mode": status.get("analysis_mode"),
            "source_manifest": "run/manifest.json",
            "selected_read_only_artifacts": selected,
        }
    )
    analysis = {
        "schema_version": SCHEMA_VERSION,
        "analysis_id": analysis_id,
        "created_at_utc": created,
        "user_question": question,
        "source_run_id": status.get("run_id"),
        "source_analysis_mode": status.get("analysis_mode"),
        "ownership": {
            "harako_outputs": "read-only source evidence",
            "post_analysis_outputs": "agent- or user-generated, not Harako core results",
        },
        "scripts": [],
        "generated_outputs": [],
    }
    (workspace / "input_manifest.json").write_text(json.dumps(source_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (workspace / "analysis.yaml").write_text(yaml.safe_dump(analysis, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (workspace / "README.md").write_text(
        "# Post-analysis workspace\n\n"
        "This workspace is separate from the immutable Harako core run. Treat all referenced Harako artifacts as read-only. "
        "Scripts and interpretations created here are not Harako-generated scientific outputs.\n",
        encoding="utf-8",
    )
    return response(
        {"analysis_id": analysis_id, "workspace": str(workspace), "source_run_id": status.get("run_id"), "question": question}
    )
