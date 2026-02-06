import json
from pathlib import Path


def _load(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main():
    repo_root = Path(__file__).resolve().parents[1]
    locale_dir = repo_root / "app" / "ui" / "locales"
    en_path = locale_dir / "en.json"
    ja_path = locale_dir / "ja.json"

    en = _load(en_path)
    ja = _load(ja_path)

    required_keys = {
        "sidebar.language",
        "info.io_fixed",
        "info.mount_note",
        "info.host_paths",
        "info.run_dir",
        "info.resolved_species",
        "msg.io_inaccessible",
        "msg.refs_missing",
        "msg.engine_need_two_conditions",
        "msg.run.locked",
        "msg.run.fastp_gzip",
        "msg.run.fastp_missing",
        "msg.run.incomplete_files",
        "msg.run_generic",
        "label.details",
        "label.precheck_details",
        "label.advanced",
        "label.input_scan",
        "label.cache_directory",
        "label.io_status",
        "label.output_contents",
        "label.auto_recover",
        "label.empty",
        "label.no_output",
        "label.validate_output",
        "label.dryrun_output",
        "label.rerun_incomplete",
        "label.run_precheck",
        "label.config_stat",
        "label.run_config_summary",
        "label.saved_species",
        "label.run_output_live",
        "label.run_output",
        "label.snakemake_log",
        "label.next_steps",
        "label.recover_output",
        "label.cleanup_output",
        "label.selfcontained_output",
        "label.fetch_refs_output",
        "label.use_custom_refs",
        "btn.test_output_write",
        "btn.fetch_refs",
        "btn.fetch_refs_url",
        "btn.go_reference",
        "btn.stop_run",
        "btn.recover",
        "btn.rerun_incomplete",
        "btn.cleanup_metadata",
        "btn.delete_incomplete",
        "btn.check_report_selfcontained",
        "success.ref_fetch_completed",
        "success.saved_ok",
        "success.recover_ok",
        "success.cleanup_ok",
        "success.deleted_incomplete",
        "success.selfcontained_ok",
        "msg.guard.lock_title",
        "msg.guard.lock_body",
        "msg.guard.incomplete_title",
        "msg.guard.incomplete_body",
        "msg.guard.error_title",
        "msg.guard.error_body",
        "status.fetch_refs_running",
        "status.fetch_refs_failed",
        "status.output_writable",
        "status.run_running",
        "status.run_success",
        "status.run_stopped",
        "status.run_failed",
        "status.report_ready",
        "warning.fetch_refs_to_enable",
        "warning.save_first_validate",
        "info.incomplete_files",
        "warn.autopair_canonicalization",
        "warn.fix_issues_before_saving",
        "warn.fix_issues_enable_save",
        "warn.ref_fetch_custom_fallback",
        "warn.conflicting_conditions",
        "warn.fastq1_looks_like_read2",
        "error.no_fastq_files",
        "error.no_fasta",
        "error.no_gtf",
        "error.no_presets",
        "error.ref_fetch_http_403",
        "error.ref_fetch_failed_exit",
        "error.ref_not_selected",
        "error.reference_issues",
        "error.save_disabled",
        "error.run_disabled",
        "error.cannot_save_normalized",
        "error.save_failed_missing",
        "error.save_failed_generic",
        "error.output_mount_wrong",
        "error.output_not_writable",
        "error.recover_missing_config",
        "error.recover_failed",
        "error.cleanup_failed",
        "error.selfcontained_failed",
        "error.species_missing",
        "error.species_invalid",
        "ref_error.not_ready",
        "ref_error.missing_key",
        "ref_error.file_not_found",
        "ref_error.missing_ref_preset",
        "invalid.samples_missing",
        "invalid.engine_need_two_conditions",
        "invalid.engine_invalid",
        "invalid.ref_preset_species_mismatch",
        "invalid.contrast_ref",
        "invalid.contrast_pair",
        "invalid.contrast_legacy",
        "run_blocker.missing_config",
        "run_blocker.missing_samples_tsv",
        "run_blocker.no_fastq",
        "run_blocker.output_not_writable",
        "run_blocker.species_missing",
        "run_blocker.species_mismatch",
        "row_issue.row_label",
        "row_issue.sample_missing",
        "row_issue.duplicate_sample",
        "row_issue.condition_missing",
        "row_issue.fastq1_missing",
        "row_issue.fastq1_not_found",
        "row_issue.fastq2_missing",
        "row_issue.fastq2_not_found",
        "info.using_cached_refs",
        "help.recover",
        "help.incomplete_recover",
        "help.rerun_incomplete",
        "help.auto_recover",
    }

    en_keys = set(en)
    ja_keys = set(ja)

    missing_en = required_keys - en_keys
    missing_ja = required_keys - ja_keys
    if missing_en or missing_ja:
        raise SystemExit(
            "Missing required locale keys. en="
            + ", ".join(sorted(missing_en))
            + " ja="
            + ", ".join(sorted(missing_ja))
        )

    if en_keys != ja_keys:
        extra_en = en_keys - ja_keys
        extra_ja = ja_keys - en_keys
        raise SystemExit(
            "Locale keys mismatch. extra_en="
            + ", ".join(sorted(extra_en))
            + " extra_ja="
            + ", ".join(sorted(extra_ja))
        )


if __name__ == "__main__":
    main()
