from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

import app.agent as agent_module
from app.agent import (
    AgentInterfaceError,
    _pid_alive,
    artifact_inventory,
    build_agent_context,
    create_plan,
    dry_run_plan,
    execute_plan,
    init_post_analysis,
    inspect_input,
    load_plan,
    propose_samples,
    propose_samples_from_inspection,
    run_status,
    validate_plan_payload,
    write_sample_table,
)
from app.agent_contracts import approval_hash_for, plan_id_for, schema_errors
from app.cli import app
from app.version import VERSION


RUNNER = CliRunner()


def _write_fastq(path: Path, content: bytes = b"SECRET_SEQUENCE_CONTENT\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _reference_fixture(tmp_path: Path, *, verified: bool = True) -> tuple[Path, Path]:
    preset = "mouse_ensembl_grcm39"
    release = "release-test"
    cache = tmp_path / "refs_cache"
    bundle = cache / preset / release
    if verified:
        bundle.mkdir(parents=True)
    contents = {
        "transcripts_fasta_url": b"transcripts",
        "genome_fasta_url": b"genome",
        "gtf_url": b"annotation",
    }
    names = {
        "transcripts_fasta_url": "transcripts.fa.gz",
        "genome_fasta_url": "genome.fa.gz",
        "gtf_url": "annotation.gtf.gz",
    }
    hashes = {}
    for key, content in contents.items():
        if verified:
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
                "annotation_release": "test",
                "display_name": "Mouse test",
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
    manifest_path = tmp_path / "ref_manifest.yaml"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return manifest_path, cache


def _analysis_fixture(
    tmp_path: Path, condition_counts: dict[str, int], *, verified_reference: bool = True
) -> tuple[Path, Path, Path, Path, Path]:
    fastq_root = tmp_path / "fastq"
    rows = []
    for condition, count in condition_counts.items():
        for index in range(1, count + 1):
            sample = f"{condition or 'sample'}_{index}"
            r1 = fastq_root / f"{sample}_R1.fastq.gz"
            r2 = fastq_root / f"{sample}_R2.fastq.gz"
            _write_fastq(r1)
            _write_fastq(r2)
            rows.append(
                {
                    "sample": sample,
                    "condition": condition,
                    "fastq1": r1.relative_to(fastq_root).as_posix(),
                    "fastq2": r2.relative_to(fastq_root).as_posix(),
                }
            )
    table = tmp_path / "samples.tsv"
    write_sample_table(table, rows)
    manifest, cache = _reference_fixture(tmp_path, verified=verified_reference)
    output = tmp_path / "output"
    output.mkdir()
    return table, fastq_root, manifest, cache, output


def _plan(tmp_path: Path, counts: dict[str, int], *, verified_reference: bool = True) -> dict:
    table, fastq_root, manifest, cache, output = _analysis_fixture(
        tmp_path, counts, verified_reference=verified_reference
    )
    return create_plan(
        sample_table=table,
        input_root=fastq_root,
        output_root=output,
        project_name="study01",
        library_protocol="full_length",
        species="mouse",
        ref_preset="mouse_ensembl_grcm39",
        ref_release="pinned",
        ref_manifest=manifest,
        ref_cache_dir=cache,
        contrast_mode="ref",
        contrast_ref="Control" if len(counts) > 1 else None,
    )


def test_inspection_is_deterministic_and_never_reads_fastq_content(tmp_path, monkeypatch):
    root = tmp_path / "fastq"
    for name in (
        "z_single.fastq.gz",
        "a_R2.fastq.gz",
        "a_R1.fastq.gz",
        "amb_R1.fastq.gz",
        "amb_R2.fastq.gz",
        "amb_2.fastq.gz",
    ):
        _write_fastq(root / name)
    (root / "ignored.fastq.bz2").write_bytes(b"not read")
    original_open = Path.open

    def guarded_open(path: Path, *args, **kwargs):
        if path.name.lower().endswith((".fastq", ".fastq.gz", ".fq", ".fq.gz")):
            raise AssertionError("FASTQ content was opened")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    first = inspect_input(root)
    second = inspect_input(root)
    assert first == second
    assert first["harako_version"] == VERSION
    assert [item["path"] for item in first["fastq_files"]] == sorted(item["path"] for item in first["fastq_files"])
    assert {item["read_direction"] for item in first["fastq_files"]} >= {"R1", "R2", "single-end"}
    assert any(item["ambiguity_status"] == "ambiguous" for item in first["fastq_files"])
    assert first["summary"]["paired_candidates"] >= 1
    assert any("unsupported" in warning for warning in first["warnings"])
    assert "SECRET_SEQUENCE_CONTENT" not in json.dumps(first)


def test_inspection_reports_duplicate_single_end_candidates(tmp_path):
    root = tmp_path / "fastq"
    _write_fastq(root / "a" / "same.fastq.gz")
    _write_fastq(root / "b" / "same.fastq.gz")
    payload = inspect_input(root)
    assert payload["summary"]["duplicate_candidates"] == ["same"]
    assert any("Duplicate" in item for item in payload["unresolved"])


def test_sample_proposal_pairs_deterministically_and_never_infers_conditions(tmp_path):
    root = tmp_path / "fastq"
    for name in ("Con_R1.fastq.gz", "Con_R2.fastq.gz", "STZ_R1.fastq.gz", "STZ_R2.fastq.gz"):
        _write_fastq(root / name)
    inspection = inspect_input(root)
    proposal = propose_samples_from_inspection(inspection)
    assert [row["sample"] for row in proposal["samples"]] == ["Con", "STZ"]
    assert all(row["condition"] == "" for row in proposal["samples"])
    assert proposal["conditions_inferred"] is False
    condition_map = tmp_path / "conditions.tsv"
    condition_map.write_text("sample\tcondition\nCon\tControl\nSTZ\tSTZ\n", encoding="utf-8")
    mapped = propose_samples(root, condition_map)
    assert {row["sample"]: row["condition"] for row in mapped["samples"]} == {"Con": "Control", "STZ": "STZ"}


def test_sample_proposal_preserves_unresolved_pairing_and_rejects_conflicts(tmp_path):
    root = tmp_path / "fastq"
    for name in ("amb_R1.fastq.gz", "amb_R2.fastq.gz", "amb_2.fastq.gz", "single_R1.fastq.gz"):
        _write_fastq(root / name)
    proposal = propose_samples(root)
    assert [row["sample"] for row in proposal["samples"]] == ["single"]
    assert proposal["samples"][0]["pairing_status"] == "single-end"
    assert any("Ambiguous" in item for item in proposal["unresolved"])
    mapping = tmp_path / "conditions.tsv"
    mapping.write_text("sample\tcondition\nsingle\tA\nsingle\tB\n", encoding="utf-8")
    with pytest.raises(AgentInterfaceError, match="Conflicting"):
        propose_samples(root, mapping)


def test_sample_table_is_not_silently_overwritten(tmp_path):
    output = tmp_path / "samples.tsv"
    write_sample_table(output, [{"sample": "s", "condition": "", "fastq1": "s.fastq.gz", "fastq2": ""}])
    before = output.read_bytes()
    with pytest.raises(AgentInterfaceError, match="--force"):
        write_sample_table(output, [])
    assert output.read_bytes() == before


def test_plan_matches_schema_and_has_deterministic_hashes(tmp_path):
    plan = _plan(tmp_path, {"Control": 2, "STZ": 2})
    assert schema_errors(plan) == []
    assert validate_plan_payload(plan)["executable"] is True
    recreated = copy.deepcopy(plan)
    recreated["created_at_utc"] = "2099-01-01T00:00:00Z"
    assert plan_id_for(recreated) == plan["plan_id"]
    assert approval_hash_for(recreated) == plan["approval_hash"]
    assert plan["analysis_plan"]["mode"] == "differential"
    assert plan["analysis_plan"]["condition_counts"] == {"Control": 2, "STZ": 2}
    assert plan["library_protocol"] == "full_length"
    assert plan["reference"]["assembly"] == "GRCm39"
    assert plan["reference"]["checksum_verified"] is True


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p["samples"].__setitem__(0, {**p["samples"][0], "sample": "changed"}),
        lambda p: p["samples"][0].__setitem__("condition", "changed"),
        lambda p: p["reference"].__setitem__("canonical_preset", "changed"),
        lambda p: p["contrasts"].__setitem__("reference", "STZ"),
        lambda p: p["enrichment"].__setitem__("enabled", True),
        lambda p: p["resources"].__setitem__("threads", 99),
        lambda p: p.__setitem__("library_protocol", "three_prime_tag"),
    ],
)
def test_approval_hash_changes_for_every_execution_relevant_category(tmp_path, mutation):
    plan = _plan(tmp_path, {"Control": 2, "STZ": 2})
    changed = copy.deepcopy(plan)
    mutation(changed)
    assert approval_hash_for(changed) != plan["approval_hash"]


def test_protocol_changes_plan_id_and_approval_hash(tmp_path):
    plan = _plan(tmp_path, {"Control": 2, "STZ": 2})
    changed = copy.deepcopy(plan)
    changed["library_protocol"] = "three_prime_tag"
    assert plan_id_for(changed) != plan["plan_id"]
    assert approval_hash_for(changed) != plan["approval_hash"]


def test_historical_v1_plan_is_hash_verifiable_but_not_executable():
    fixture = Path(__file__).parent / "fixtures" / "agent_plan_v1_legacy.json"
    plan = load_plan(fixture)
    original = copy.deepcopy(plan)

    assert "library_protocol" not in plan
    assert schema_errors(plan) == []
    assert plan_id_for(plan) == "5af35625dbb956534a84a3e3fdbb25a4b69e49b7a239ae886e64823880acf088"
    assert approval_hash_for(plan) == "5b600b5abacd4a6f212cb768aeee4366309c827c55f81116fec488ef67517e6f"
    assert plan_id_for(plan) == plan["plan_id"]
    assert approval_hash_for(plan) == plan["approval_hash"]

    validation = validate_plan_payload(plan)
    assert validation["valid"] is True
    assert validation["executable"] is False
    assert any("explicit library_protocol" in item for item in validation["unresolved"])
    assert any("predates explicit" in item for item in validation["warnings"])
    assert "library_protocol" not in plan

    runner_called = False

    def runner(*_args):
        nonlocal runner_called
        runner_called = True
        return 0, ""

    with pytest.raises(AgentInterfaceError, match="explicit library_protocol"):
        dry_run_plan(plan, runner=runner)
    with pytest.raises(AgentInterfaceError, match="explicit library_protocol"):
        execute_plan(plan, approval=plan["approval_hash"])
    assert runner_called is False
    assert not Path(plan["output_root"]).exists()
    assert plan == original


def test_qc_only_and_unresolved_plans_preserve_inactive_requests(tmp_path):
    qc = _plan(tmp_path / "qc", {"Control": 2})
    assert qc["analysis_plan"]["mode"] == "qc_only"
    assert qc["contrasts"]["active"] is False
    assert qc["enrichment"]["enabled"] is False
    assert validate_plan_payload(qc)["executable"] is True

    table, root, manifest, cache, output = _analysis_fixture(tmp_path / "unresolved", {"": 2})
    unresolved = create_plan(
        sample_table=table,
        input_root=root,
        output_root=output,
        project_name="unresolved",
        library_protocol="full_length",
        species="mouse",
        ref_preset="mouse_ensembl_grcm39",
        ref_manifest=manifest,
        ref_cache_dir=cache,
        contrast_ref=None,
        enable_enrichment=True,
    )
    result = validate_plan_payload(unresolved)
    assert result["valid"] is True
    assert result["executable"] is False
    assert result["analysis_mode"] == "invalid"
    assert unresolved["requested_options"]["enrichment"] is True
    assert unresolved["enrichment"]["enabled"] is False


def test_unverified_reference_is_never_claimed_or_executable(tmp_path):
    plan = _plan(tmp_path, {"Control": 2}, verified_reference=False)
    assert plan["reference"]["checksum_verified"] is False
    validation = validate_plan_payload(plan)
    assert validation["valid"] is True
    assert validation["executable"] is False
    assert any("checksum" in item for item in validation["unresolved"])


def test_plan_rejects_arbitrary_commands_and_hash_mutation(tmp_path):
    plan = _plan(tmp_path, {"Control": 2, "STZ": 2})
    plan["requested_options"]["command"] = "dangerous"
    plan["plan_id"] = plan_id_for(plan)
    plan["approval_hash"] = approval_hash_for(plan)
    result = validate_plan_payload(plan)
    assert result["valid"] is False
    assert any("commands" in error for error in result["errors"])

    changed = _plan(tmp_path / "changed", {"Control": 2, "STZ": 2})
    changed["resources"]["threads"] = 3
    assert validate_plan_payload(changed)["valid"] is False


def test_dry_run_validates_and_uses_existing_adapter_without_persistent_run(tmp_path):
    plan = _plan(tmp_path, {"Control": 2, "STZ": 2})
    calls = []

    def runner(config_path: Path, envelope: dict, output_dir: Path):
        calls.append((yaml.safe_load(config_path.read_text(encoding="utf-8")), envelope, output_dir))
        return 0, "rule fastp:\nrule salmon_quant:\n4 jobs"

    result = dry_run_plan(plan, runner=runner)
    assert result["valid"] is True
    assert result["dry_run_satisfies_approval"] is False
    assert result["planned_rules"] == ["fastp", "salmon_quant"]
    assert not (Path(plan["output_root"]) / "data_out").exists()
    assert calls[0][0]["analysis_plan"]["mode"] == "differential"


def test_execution_requires_exact_current_approval_hash_and_existing_adapter(tmp_path):
    plan = _plan(tmp_path, {"Control": 2, "STZ": 2})
    with pytest.raises(AgentInterfaceError, match="requires"):
        execute_plan(plan, approval=None)
    with pytest.raises(AgentInterfaceError, match="does not match"):
        execute_plan(plan, approval="wrong")
    changed = copy.deepcopy(plan)
    changed["resources"]["threads"] = 8
    with pytest.raises(AgentInterfaceError, match="does not match"):
        execute_plan(changed, approval=plan["approval_hash"])

    calls = []

    def adapter(config_path: Path, envelope: dict, run_dir: Path) -> int:
        calls.append((config_path, envelope["plan_id"], run_dir))
        (run_dir / "run" / "manifest.json").write_text(json.dumps({"run_id": "existing-run-id"}), encoding="utf-8")
        (run_dir / "deseq2").mkdir()
        (run_dir / "deseq2" / "status.json").write_text(
            json.dumps({"mode": "differential", "differential_results_available": True}), encoding="utf-8"
        )
        (run_dir / "report").mkdir()
        (run_dir / "report" / "report.html").write_text("<html></html>", encoding="utf-8")
        return 0

    result = execute_plan(plan, approval=plan["approval_hash"], executor=adapter)
    run = Path(result["run_dir"])
    assert result["state"] == "completed"
    assert len(calls) == 1
    assert (run / "run" / "approved-agent-plan.yaml").is_file()
    approval = json.loads((run / "run" / "agent_approval.json").read_text(encoding="utf-8"))
    assert approval["approval_hash"] == plan["approval_hash"]
    frozen = yaml.safe_load((run / "run" / "config_resolved.yaml").read_text(encoding="utf-8"))
    assert frozen["analysis_plan"]["mode"] == "differential"
    assert frozen["library_protocol"] == "full_length"


def _run_fixture(tmp_path: Path, mode: str, state: str = "completed") -> Path:
    run = tmp_path / f"{mode}_{state}_run"
    (run / "run" / "metadata").mkdir(parents=True)
    (run / "run" / "manifest.json").write_text(json.dumps({"run_id": f"{mode}-id"}), encoding="utf-8")
    samples = run / "run" / "metadata" / "samples.tsv"
    samples.write_text("sample\tcondition\tfastq1\tfastq2\ns1\tA\ts1.fastq.gz\t\n", encoding="utf-8")
    analysis = {
        "mode": mode,
        "reason_code": "eligible" if mode == "differential" else "single_condition",
        "condition_counts": {"A": 1},
    }
    (run / "run" / "config_resolved.yaml").write_text(
        yaml.safe_dump({"project_name": "project", "sample_table": str(samples), "analysis_plan": analysis}), encoding="utf-8"
    )
    agent = {"state": state}
    if state == "running":
        agent["pid"] = os.getpid()
    if state == "interrupted":
        agent = {"state": "running", "pid": 99999999}
    if state == "failed":
        agent["failed_stage"] = "salmon"
    (run / "run" / "agent_status.json").write_text(json.dumps(agent), encoding="utf-8")
    if state == "completed":
        (run / "deseq2").mkdir()
        (run / "deseq2" / "status.json").write_text(
            json.dumps(
                {
                    "mode": mode,
                    "differential_results_available": mode == "differential",
                    "pca_available": True,
                    "sample_distance_available": True,
                    "enrichment_allowed": mode == "differential",
                }
            ),
            encoding="utf-8",
        )
        (run / "report").mkdir()
        (run / "report" / "report.html").write_text("<html></html>", encoding="utf-8")
        (run / "tximport").mkdir()
        (run / "tximport" / "txi.tsv").write_text("gene\ts1\n", encoding="utf-8")
        (run / "tximport" / "tpm.tsv").write_text("gene\ts1\n", encoding="utf-8")
        (run / "deseq2" / "results.tsv").write_text("gene\tpadj\n", encoding="utf-8")
    return run


@pytest.mark.parametrize("pid", [None, "1", True, 0, -1, 0x1_0000_0000])
def test_pid_alive_rejects_invalid_values(pid):
    assert _pid_alive(pid) is False


def test_pid_alive_reports_current_process():
    assert _pid_alive(os.getpid()) is True


def test_pid_alive_reports_child_until_it_exits():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert _pid_alive(child.pid) is True
    finally:
        child.terminate()
        child.wait(timeout=10)
    assert _pid_alive(child.pid) is False


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific non-signaling PID query")
def test_pid_alive_windows_never_calls_os_kill(monkeypatch):
    def fail_if_called(*_args):
        raise AssertionError("Windows PID liveness checks must not call os.kill")

    monkeypatch.setattr(agent_module.os, "kill", fail_if_called)
    assert _pid_alive(os.getpid()) is True


def test_windows_pid_query_source_does_not_use_os_kill():
    assert "os.kill" not in inspect.getsource(agent_module._pid_alive_windows)


@pytest.mark.skipif(os.name == "nt", reason="POSIX-specific PID query")
def test_pid_alive_posix_preserves_kill_zero_semantics(monkeypatch):
    calls = []

    def alive(pid, signal):
        calls.append((pid, signal))

    monkeypatch.setattr(agent_module.os, "kill", alive)
    assert _pid_alive(123) is True
    assert calls == [(123, 0)]

    def missing(_pid, _signal):
        raise ProcessLookupError

    monkeypatch.setattr(agent_module.os, "kill", missing)
    assert _pid_alive(123) is False

    def inaccessible(_pid, _signal):
        raise PermissionError

    monkeypatch.setattr(agent_module.os, "kill", inaccessible)
    assert _pid_alive(123) is True

    def invalid(_pid, _signal):
        raise OSError

    monkeypatch.setattr(agent_module.os, "kill", invalid)
    assert _pid_alive(123) is False


@pytest.mark.parametrize("state", ["running", "completed", "failed", "interrupted"])
def test_status_contract_reports_runtime_states(tmp_path, state):
    run = _run_fixture(tmp_path, "differential", state)
    payload = run_status(run)
    assert payload["state"] == state
    assert payload["harako_version"] == VERSION
    if state == "failed":
        assert payload["failed_stage"] == "salmon"
    if state == "completed":
        assert payload["report_available"] is True
        assert payload["de_results_available"] is True
        assert payload["library_protocol"] == "legacy_unspecified"
        assert payload["legacy_handoff"] is True
        assert "predates explicit" in payload["scientific_warning"]


def test_qc_only_artifacts_are_typed_and_inferential_outputs_are_inapplicable(tmp_path):
    run = _run_fixture(tmp_path, "qc_only")
    (run / "unrelated-secret.txt").write_text("secret", encoding="utf-8")
    inventory = artifact_inventory(run)
    paths = {item["relative_path"] for item in inventory["artifacts"]}
    assert "unrelated-secret.txt" not in paths
    result = next(item for item in inventory["artifacts"] if item["artifact_type"] == "deseq2_results")
    assert result["applicable"] is False
    assert result["exists"] is False
    assert all(".." not in Path(item["relative_path"]).parts for item in inventory["artifacts"])


def test_differential_artifacts_use_the_generated_ma_plot_path(tmp_path):
    run = _run_fixture(tmp_path, "differential")
    (run / "deseq2" / "ma_plot.png").write_bytes(b"png")
    inventory = artifact_inventory(run)
    ma_plot = next(item for item in inventory["artifacts"] if item["artifact_type"] == "ma_plot")
    assert ma_plot["relative_path"] == "deseq2/ma_plot.png"
    assert ma_plot["exists"] is True


def test_context_is_sanitized_and_contains_only_safe_relative_artifacts(tmp_path, monkeypatch):
    run = _run_fixture(tmp_path, "differential")
    monkeypatch.setenv("HARAKO_TEST_SECRET", "must-not-leak")
    context = build_agent_context(run)
    encoded = json.dumps(context)
    assert "must-not-leak" not in encoded
    assert "SECRET_SEQUENCE_CONTENT" not in encoded
    assert str(run.resolve()) not in encoded
    assert context["run"]["analysis_mode"] == "differential"
    assert context["run"]["library_protocol"] == "legacy_unspecified"
    assert context["run"]["legacy_handoff"] is True
    assert all(not Path(item["relative_path"]).is_absolute() for item in context["artifacts"])


def test_context_uses_approved_plan_contrasts(tmp_path):
    run = _run_fixture(tmp_path, "differential")
    approved_contrasts = {
        "mode": "pairwise",
        "reference": None,
        "pairs": [["A", "B"], ["A", "C"], ["B", "C"]],
        "active": True,
    }
    (run / "run" / "approved-agent-plan.yaml").write_text(
        yaml.safe_dump({"contrasts": approved_contrasts}), encoding="utf-8"
    )
    context = build_agent_context(run)
    assert context["contrasts"] == {
        "mode": "pairwise",
        "reference": None,
        "pairs": [["A", "B"], ["A", "C"], ["B", "C"]],
    }


def test_post_analysis_workspace_is_isolated_and_core_files_are_unchanged(tmp_path):
    run = _run_fixture(tmp_path, "differential")
    config = run / "run" / "config_resolved.yaml"
    result_file = run / "deseq2" / "results.tsv"
    before = {config: config.read_bytes(), result_file: result_file.read_bytes()}
    result = init_post_analysis(run, "pathway-review", "Summarize stress-response pathways")
    workspace = Path(result["workspace"])
    assert workspace == run.parent / "post_analysis" / "pathway-review"
    assert {"analysis.yaml", "input_manifest.json", "README.md", "scripts", "figures", "tables", "reports", "logs", "environment"} == {path.name for path in workspace.iterdir()}
    analysis = yaml.safe_load((workspace / "analysis.yaml").read_text(encoding="utf-8"))
    assert analysis["user_question"] == "Summarize stress-response pathways"
    assert analysis["ownership"]["harako_outputs"] == "read-only source evidence"
    assert all(path.read_bytes() == content for path, content in before.items())


def test_agent_cli_json_exit_codes_and_backward_compatible_root_commands(tmp_path):
    root = tmp_path / "fastq"
    _write_fastq(root / "sample.fastq.gz")
    inspection_path = tmp_path / "inspection.json"
    inspected = RUNNER.invoke(app, ["agent", "inspect-input", "--input", str(root), "--output", str(inspection_path)])
    assert inspected.exit_code == 0
    assert json.loads(inspected.stdout)["schema_version"] == 1
    assert inspection_path.is_file()
    table = tmp_path / "samples.tsv"
    proposed = RUNNER.invoke(
        app, ["agent", "propose-samples", "--inspection", str(inspection_path), "--output", str(table)]
    )
    assert proposed.exit_code == 0
    assert json.loads(proposed.stdout)["conditions_inferred"] is False
    assert table.is_file()
    missing = RUNNER.invoke(app, ["agent", "status", "--run-dir", str(tmp_path / "missing")])
    assert missing.exit_code == 5
    assert json.loads(missing.stdout)["reason_code"] == "run_not_found"
    help_result = RUNNER.invoke(app, ["--help"])
    assert help_result.exit_code == 0
    for command in ("init", "validate", "run", "run-id", "fetch", "agent"):
        assert command in help_result.stdout


def test_execute_cli_refuses_missing_and_wrong_approval_without_calling_pipeline(tmp_path):
    plan = _plan(tmp_path, {"Control": 2, "STZ": 2})
    plan_path = tmp_path / "harako-plan.yaml"
    plan_path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")
    missing = RUNNER.invoke(app, ["agent", "execute", "--plan", str(plan_path)])
    assert missing.exit_code == 3
    wrong = RUNNER.invoke(app, ["agent", "execute", "--plan", str(plan_path), "--approve", "wrong"])
    assert wrong.exit_code == 3
    assert not (Path(plan["output_root"]) / "data_out").exists()


def test_non_execution_commands_make_no_network_calls(tmp_path, monkeypatch):
    def deny_network(*args, **kwargs):
        raise AssertionError("network call attempted")

    monkeypatch.setattr("socket.create_connection", deny_network)
    plan = _plan(tmp_path, {"Control": 2})
    assert validate_plan_payload(plan)["valid"] is True
    run = _run_fixture(tmp_path / "run", "qc_only")
    run_status(run)
    artifact_inventory(run)
    build_agent_context(run)
    init_post_analysis(run, "local-only")


def test_complete_control_stz_acceptance_sequence(tmp_path):
    root = tmp_path / "fastq"
    for sample in ("Con_Hard_1", "Con_Hard_2", "STZ_Hard_1", "STZ_Hard_2"):
        _write_fastq(root / f"{sample}_R1.fastq.gz")
        _write_fastq(root / f"{sample}_R2.fastq.gz")
    inspection = inspect_input(root)
    condition_map = tmp_path / "conditions.tsv"
    condition_map.write_text(
        "sample\tcondition\nCon_Hard_1\tcontrol\nCon_Hard_2\tcontrol\nSTZ_Hard_1\tSTZ\nSTZ_Hard_2\tSTZ\n",
        encoding="utf-8",
    )
    proposal = propose_samples_from_inspection(inspection, condition_map)
    table = tmp_path / "samples.tsv"
    write_sample_table(table, proposal["samples"])
    manifest, cache = _reference_fixture(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    plan = create_plan(
        sample_table=table,
        input_root=root,
        output_root=output,
        project_name="stz-study",
        library_protocol="full_length",
        species="mouse",
        ref_preset="mouse_ensembl_grcm39",
        ref_manifest=manifest,
        ref_cache_dir=cache,
        contrast_mode="ref",
        contrast_ref="control",
    )
    validation = validate_plan_payload(plan)
    assert validation["executable"] is True
    assert plan["analysis_plan"]["mode"] == "differential"
    assert plan["contrasts"]["reference"] == "control"
    with pytest.raises(AgentInterfaceError):
        execute_plan(plan, approval=None)


def test_agent_plan_requires_explicit_library_protocol(tmp_path):
    table, root, manifest, cache, output = _analysis_fixture(
        tmp_path, {"Control": 2, "STZ": 2}
    )
    with pytest.raises(AgentInterfaceError, match="library_protocol is required"):
        create_plan(
            sample_table=table,
            input_root=root,
            output_root=output,
            project_name="explicit-protocol",
            library_protocol="",
            species="mouse",
            ref_preset="mouse_ensembl_grcm39",
            ref_manifest=manifest,
            ref_cache_dir=cache,
            contrast_ref="Control",
        )
