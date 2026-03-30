from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ui import run as ui_run
from app.ui import refs as ui_refs
from app.ui import samples_table as ui_samples
from app.ui import scan as ui_scan
from app.ui import state as ui_state
from app.ui import i18n as ui_i18n


def test_split_read_suffix_and_read_side():
    prefix, read, has_r, sep = ui_scan.split_read_suffix("sample_R1")
    assert prefix == "sample"
    assert read == "1"
    assert has_r is True
    assert sep == "_"

    assert ui_scan.read_side("x/sample_R2.fastq.gz") == "2"
    assert ui_scan.read_side("x/sample.fastq.gz") == ""


def test_infer_pair_candidates_basic():
    cands = ui_scan.infer_pair_candidates("dir/sample_R1.fastq.gz")
    assert "dir/sample_R2.fastq.gz" in cands


def test_normalize_rows_and_autopair():
    fastq_rel = ["a_R1.fastq.gz", "a_R2.fastq.gz", "b_R1.fastq.gz", "b_R2.fastq.gz"]
    rows = [
        {"sample": "", "condition": "", "fastq1": "a_R1.fastq.gz", "fastq2": ""},
        {"sample": "", "condition": "", "fastq1": "b_R1.fastq.gz", "fastq2": ""},
    ]

    norm = ui_samples.normalize_rows(rows, paired=True, fastq_rel=fastq_rel, autofill_conditions=True)
    assert norm[0]["sample"] == "a"
    assert norm[0]["condition"] == "a"
    assert norm[0]["fastq2"] == "a_R2.fastq.gz"

    paired = ui_samples.auto_pair(rows, fastq_rel)
    assert paired[0]["fastq2"] == "a_R2.fastq.gz"
    assert paired[1]["fastq2"] == "b_R2.fastq.gz"


def test_manifest_run_id_is_deterministic():
    payload = ui_run.build_manifest_payload(
        payload={"threads": 2},
        rows_raw=[{"sample": "s1", "condition": "A", "fastq1": "s1_R1.fastq.gz", "fastq2": ""}],
        fastq_rel=[],
        coerce_rows_raw=ui_samples.coerce_rows_raw,
        git_rev="abc",
        input_root=Path("/input"),
    )
    rid1 = ui_run.manifest_run_id(payload)
    rid2 = ui_run.manifest_run_id(payload)
    assert rid1 == rid2
    assert len(rid1) == 64


def test_refs_release_resolution():
    manifest = {"presets": {"mouse_gencode": {"pinned": {"a": 1}, "vM36": {"a": 2}}}}
    rels = ui_refs.preset_releases(manifest, "mouse_gencode")
    assert "pinned" in rels
    assert "vM36" in rels


def test_mark_user_edit_transition_for_samples_edit(monkeypatch):
    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(ui_state, "st", fake_st)
    monkeypatch.setattr(ui_samples, "st", fake_st)
    fake_st.session_state.update(
        {
            "rows_raw": [{"sample": "s1", "condition": "A", "fastq1": "a_R1.fastq.gz", "fastq2": ""}],
            "samples_editor": {"edited_rows": {0: {"condition": "B"}}},
            "run_config_touched": False,
            "validation_ok": True,
            "saved": True,
        }
    )

    changed = ui_samples.sync_rows_raw_from_editor("samples_editor")
    assert changed is True
    ui_state.mark_user_edit()

    assert fake_st.session_state["rows_raw"][0]["condition"] == "B"
    assert fake_st.session_state["run_config_touched"] is True
    assert fake_st.session_state["validation_ok"] is False
    assert fake_st.session_state["saved"] is False


def test_mark_user_edit_transition_after_auto_pair(monkeypatch):
    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(ui_state, "st", fake_st)
    monkeypatch.setattr(ui_samples, "st", fake_st)
    fake_st.session_state.update(
        {
            "run_config_touched": False,
            "validation_ok": True,
            "saved": True,
        }
    )

    rows = [{"sample": "x", "condition": "c", "fastq1": "x_R1.fastq.gz", "fastq2": ""}]
    available = ["x_R1.fastq.gz", "x_R2.fastq.gz"]
    out = ui_samples.auto_pair(rows, available)
    assert out[0]["fastq2"] == "x_R2.fastq.gz"

    ui_state.mark_user_edit()
    assert fake_st.session_state["run_config_touched"] is True
    assert fake_st.session_state["validation_ok"] is False
    assert fake_st.session_state["saved"] is False


def test_scan_fastqs_with_empty_include_subdirs_returns_zero(tmp_path):
    p = tmp_path / "projA"
    p.mkdir(parents=True, exist_ok=True)
    (p / "a_R1.fastq.gz").write_text("x", encoding="utf-8")
    out = ui_scan.scan_fastqs(tmp_path, include_subdirs=[])
    assert out == []


@pytest.fixture
def scan_tree(tmp_path):
    (tmp_path / "root.fastq.gz").write_text("x", encoding="utf-8")

    proj_a = tmp_path / "projA"
    proj_b = tmp_path / "projB"
    nested = proj_a / "nested"
    proj_a.mkdir(parents=True, exist_ok=True)
    proj_b.mkdir(parents=True, exist_ok=True)
    nested.mkdir(parents=True, exist_ok=True)

    (proj_a / "a_R1.fastq.gz").write_text("x", encoding="utf-8")
    (proj_a / "a_R2.fastq.gz").write_text("x", encoding="utf-8")
    (proj_b / "b_R1.fastq.gz").write_text("x", encoding="utf-8")
    (nested / "a_nested_R1.fastq.gz").write_text("x", encoding="utf-8")
    (nested / "notes.nd2").write_text("x", encoding="utf-8")
    return tmp_path


def test_scan_fastqs_selected_subdirs_excludes_root_fastq(scan_tree):
    out = ui_scan.scan_fastqs(scan_tree, include_subdirs=["projA"])
    rels = sorted([ui_scan.rel(path, scan_tree) for path in out])
    assert "root.fastq.gz" not in rels


def test_scan_fastqs_selected_subdirs_only_targets_requested(scan_tree):
    out = ui_scan.scan_fastqs(scan_tree, include_subdirs=["projA", "missing"])
    rels = sorted([ui_scan.rel(path, scan_tree) for path in out])
    assert rels == ["projA/a_R1.fastq.gz", "projA/a_R2.fastq.gz", "projA/nested/a_nested_R1.fastq.gz"]


def test_scan_fastqs_selected_subdirs_collects_nested_fastq(scan_tree):
    out = ui_scan.scan_fastqs(scan_tree, include_subdirs=["projA/nested"])
    rels = sorted([ui_scan.rel(path, scan_tree) for path in out])
    assert rels == ["projA/nested/a_nested_R1.fastq.gz"]


def test_selected_subdirs_change_marks_user_edit(monkeypatch):
    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(ui_state, "st", fake_st)
    monkeypatch.setattr(ui_samples, "st", fake_st)
    fake_st.session_state.update(
        {
            "run_config_touched": False,
            "validation_ok": True,
            "saved": True,
            "selected_subdirs": ["projA"],
        }
    )
    fake_st.session_state["selected_subdirs"] = ["projA", "projB"]
    ui_state.mark_user_edit()
    assert fake_st.session_state["run_config_touched"] is True
    assert fake_st.session_state["validation_ok"] is False
    assert fake_st.session_state["saved"] is False


def test_condition_normalization_stz_replicates():
    rows = [
        {"sample": "STZ_1", "condition": "", "fastq1": "STZ_1_R1.fastq.gz", "fastq2": ""},
        {"sample": "STZ_2", "condition": "", "fastq1": "STZ_2_R1.fastq.gz", "fastq2": ""},
    ]
    out = ui_samples.normalize_rows(rows, paired=False, fastq_rel=["STZ_1_R1.fastq.gz", "STZ_2_R1.fastq.gz"], autofill_conditions=True)
    assert out[0]["condition"] == "STZ"
    assert out[1]["condition"] == "STZ"


def test_condition_normalization_repeated_suffixes():
    assert ui_samples.normalize_condition_from_sample("Con_Hard_1") == "Con_Hard"
    assert ui_samples.normalize_condition_from_sample("Con_Hard_2") == "Con_Hard"
    assert ui_samples.normalize_condition_from_sample("Con_Hard_1_1") == "Con_Hard"


def test_apply_condition_autofill_overwrites_existing_auto_conditions():
    rows = [
        {"sample": "Con_Hard_1", "condition": "Con_Hard_1", "fastq1": "Con_Hard_1_1.fastq.gz", "fastq2": ""},
        {"sample": "SRR14340927", "condition": "SRR14340927", "fastq1": "SRR14340927.fastq.gz", "fastq2": ""},
    ]

    out = ui_samples.apply_condition_autofill(rows, overwrite=True)

    assert out[0]["condition"] == "Con_Hard"
    assert out[1]["condition"] == "SRR14340927"


@pytest.mark.parametrize(
    ("sample", "expected"),
    [
        ("Con_1", "Con"),
        ("Con-2", "Con"),
        ("Con_10", "Con"),
        ("Con.3", "Con"),
        ("Sample_A_1", "Sample_A"),
    ],
)
def test_condition_normalization_suffix_rules(sample, expected):
    assert ui_samples.normalize_condition_from_sample(sample) == expected


def test_condition_normalization_keeps_run_accession():
    assert ui_samples.normalize_condition_from_sample("SRR14340927") == "SRR14340927"


def test_new_row_autofill_uses_normalized_condition():
    import app.ui.app_ui as app_ui

    row = app_ui._new_row("Con_Hard_1_1.fastq.gz", condition_from_sample=True)

    assert row["sample"] == "Con_Hard_1"
    assert row["condition"] == "Con_Hard"


def test_initialize_advanced_state_persists_across_step_navigation():
    session_state = {}

    initial = ui_state.initialize_advanced_state(session_state)
    assert initial["contrast_mode"] == "ref"

    ui_state.update_advanced_state(
        session_state,
        contrast_mode="select",
        contrast_pairs=[["A", "B"]],
        contrast_legacy="A_vs_B",
        enrich_enable=True,
        enrich_methods=["ORA"],
        enrich_alpha=0.1,
        enrich_lfc=1.5,
        enrich_top=25,
        enrich_rank="stat",
    )

    session_state.pop("page:3:99:contrast_mode", None)
    restored = ui_state.initialize_advanced_state(session_state)

    assert restored["contrast_mode"] == "select"
    assert restored["contrast_pairs"] == [["A", "B"]]
    assert restored["contrast_legacy"] == "A_vs_B"
    assert restored["enrich_enable"] is True
    assert restored["enrich_methods"] == ["ORA"]
    assert restored["enrich_alpha"] == 0.1
    assert restored["enrich_lfc"] == 1.5
    assert restored["enrich_top"] == 25
    assert restored["enrich_rank"] == "stat"


def test_memory_limit_display_helper_handles_detected_approximate_and_unlimited():
    import app.ui.app_ui as app_ui

    exact = app_ui._memory_limit_display_info(8 * 1024**3)
    approx = app_ui._memory_limit_display_info(8192)
    unlimited = app_ui._memory_limit_display_info(2**63 - 1)
    unknown = app_ui._memory_limit_display_info(None)

    assert exact["display"] == "detected 8.0 GiB"
    assert exact["approximate"] is False
    assert approx["display"] == "detected 8.0 GiB (approx.)"
    assert approx["approximate"] is True
    assert unlimited["display"] == "unlimited"
    assert unknown["display"] == "-"


def test_validate_rows_report_r1_missing_has_sample_and_expected_path():
    rows = [{"sample": "Con_1", "condition": "Con", "fastq1": "", "fastq2": ""}]
    report = ui_samples.validate_rows_report(
        rows=rows,
        fastq_rel=[],
        paired=False,
        ref_exists=lambda _p: False,
        translate=lambda key, **kwargs: f"{key}:{kwargs}",
    )
    assert report["ok"] is False
    joined = "\n".join(report["errors"])
    assert "R1 missing" in joined
    assert "Con_1" in joined
    assert "Con_1_R1.fastq.gz" in joined


def test_validate_rows_report_internal_error_is_reported():
    class BrokenRow:
        def get(self, key, default=None):
            raise RuntimeError("boom")

    report = ui_samples.validate_rows_report(
        rows=[BrokenRow()],
        fastq_rel=[],
        paired=False,
        ref_exists=lambda _p: False,
        translate=lambda key, **kwargs: f"{key}:{kwargs}",
    )
    assert report["ok"] is False
    assert any("Internal error:" in msg for msg in report["errors"])


def test_sanitize_disable_reasons_fallback_reports_missing_r1():
    reasons = ui_samples.sanitize_disable_reasons(
        raw_reasons=["", "  "],
        rows=[{"sample": "Con_1", "condition": "Con", "fastq1": "", "fastq2": ""}],
        paired=False,
        translate=lambda key, **kwargs: f"{key}:{kwargs}",
    )
    assert reasons
    assert any("row_issue.fastq1_missing" in msg for msg in reasons)


def test_i18n_t_accepts_msgid_and_key_kwarg():
    text1 = ui_i18n.t("summary.title", lang="en")
    text2 = ui_i18n.t(key="summary.title", lang="en")
    assert isinstance(text1, str) and text1
    assert isinstance(text2, str) and text2


def test_initialize_project_name_preserves_user_edit():
    session_state = {}
    run_config = {"project_name": "Project250101"}

    initial = ui_state.initialize_project_name(session_state, run_config, "Project250101", touched=False)
    assert initial == "Project250101"
    assert session_state[ui_state.PROJECT_NAME_SESSION_KEY] == "Project250101"

    session_state[ui_state.PROJECT_NAME_SESSION_KEY] = "CustomStudy"
    run_config["project_name"] = "CustomStudy"

    restored = ui_state.initialize_project_name(session_state, run_config, "Project250101", touched=True)
    assert restored == "CustomStudy"
    assert session_state[ui_state.PROJECT_NAME_SESSION_KEY] == "CustomStudy"


def test_initialize_project_name_does_not_clobber_existing_session_value():
    session_state = {ui_state.PROJECT_NAME_SESSION_KEY: "UserEditedName"}
    run_config = {"project_name": "Project260225"}

    restored = ui_state.initialize_project_name(session_state, run_config, "Project260225", touched=False)

    assert restored == "UserEditedName"
    assert session_state[ui_state.PROJECT_NAME_SESSION_KEY] == "UserEditedName"


def test_can_run_enrichment_requires_two_conditions_and_two_replicates():
    ok, reason = ui_samples.can_run_enrichment(
        [{"sample": "S1", "condition": "A", "fastq1": "a.fastq.gz", "fastq2": ""}]
    )
    assert ok is False
    assert "at least 2 conditions" in reason

    ok, reason = ui_samples.can_run_enrichment(
        [
            {"sample": "S1", "condition": "A", "fastq1": "a1.fastq.gz", "fastq2": ""},
            {"sample": "S2", "condition": "B", "fastq1": "b1.fastq.gz", "fastq2": ""},
        ]
    )
    assert ok is False
    assert "at least 2 samples per condition" in reason

    ok, reason = ui_samples.can_run_enrichment(
        [
            {"sample": "S1", "condition": "A", "fastq1": "a1.fastq.gz", "fastq2": ""},
            {"sample": "S2", "condition": "A", "fastq1": "a2.fastq.gz", "fastq2": ""},
            {"sample": "S3", "condition": "B", "fastq1": "b1.fastq.gz", "fastq2": ""},
            {"sample": "S4", "condition": "B", "fastq1": "b2.fastq.gz", "fastq2": ""},
        ]
    )
    assert ok is True
    assert reason == ""


def test_app_ui_import_smoke():
    import app.ui.app_ui as app_ui  # noqa: F401


def test_validation_success_clears_validation_failed_blocker(monkeypatch):
    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(ui_state, "st", fake_st)
    fake_st.session_state.update(
        {
            "validation_ok": False,
            "blockers": ["validation_failed: no_detail", "other_blocker"],
            "validation_failed": "no_detail",
            "validation_failed_detail": "no_detail",
        }
    )

    ui_state.set_validation_state(False, detail=None)
    assert fake_st.session_state["validation"]["ok"] is False
    assert fake_st.session_state.get("validation_failed")

    ui_state.set_validation_state(True)
    assert fake_st.session_state["validation_ok"] is True
    assert fake_st.session_state["validation"]["ok"] is True
    assert all(not str(item).startswith("validation_failed:") for item in fake_st.session_state["blockers"])
    assert "validation_failed" not in fake_st.session_state
    assert "validation_failed_detail" not in fake_st.session_state
