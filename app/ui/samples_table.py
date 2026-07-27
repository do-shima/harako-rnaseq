from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pandas as pd
import re

from app.ui import scan as scan_utils
from app.analysis_eligibility import evaluate_analysis_eligibility

st = None


def clean_cell(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value)


def coerce_rows_raw(rows: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for row in rows or []:
        normalized.append(
            {
                "sample": clean_cell(row.get("sample", "")),
                "condition": clean_cell(row.get("condition", "")),
                "fastq1": scan_utils.normalize_input_value(clean_cell(row.get("fastq1", ""))),
                "fastq2": scan_utils.normalize_input_value(clean_cell(row.get("fastq2", ""))),
            }
        )
    return normalized


def normalize_rows(
    rows_raw: list[dict[str, Any]],
    paired: bool,
    fastq_rel: list[str],
    autofill_conditions: bool,
) -> list[dict[str, str]]:
    available_set = set(fastq_rel)
    rows_norm: list[dict[str, str]] = []
    for row in coerce_rows_raw(rows_raw):
        fastq1 = row.get("fastq1", "")
        fastq2 = row.get("fastq2", "")
        sample = row.get("sample", "")
        condition = row.get("condition", "")

        if not sample and fastq1:
            sample = scan_utils.sample_base(fastq1)
        if autofill_conditions and sample and (not condition or condition == sample):
            condition = normalize_condition_from_sample(sample)

        if paired and not fastq2 and fastq1:
            for candidate in scan_utils.infer_pair_candidates(fastq1):
                if candidate in available_set:
                    fastq2 = candidate
                    break
        if not paired:
            fastq2 = ""

        rows_norm.append({"sample": sample, "condition": condition, "fastq1": fastq1, "fastq2": fastq2})
    return rows_norm


def normalize_condition_from_sample(sample: str) -> str:
    value = clean_cell(sample).strip()
    if not value:
        return value
    if re.match(r"^(SRR|ERR|DRR|GSM|SRS|SRX|SAMN|PRJ)\d+$", value, re.IGNORECASE):
        return value

    out = value
    while True:
        trimmed = re.sub(r"(?i)(?:[_.-](?:rep)?\d+)$", "", out).strip(" _-.")
        if trimmed == out or not trimmed:
            break
        out = trimmed
    out = out.strip(" _-.")
    if not out or not re.search(r"[A-Za-z0-9]", out):
        return value
    return out


def apply_condition_autofill(rows: list[dict[str, Any]] | None, overwrite: bool = False) -> list[dict[str, str]]:
    updated: list[dict[str, str]] = []
    for row in coerce_rows_raw(rows or []):
        sample = clean_cell(row.get("sample", "")).strip()
        condition = clean_cell(row.get("condition", "")).strip()
        if sample and (overwrite or not condition or condition == sample):
            condition = normalize_condition_from_sample(sample)
        updated.append(
            {
                "sample": sample,
                "condition": condition,
                "fastq1": scan_utils.normalize_input_value(clean_cell(row.get("fastq1", ""))),
                "fastq2": scan_utils.normalize_input_value(clean_cell(row.get("fastq2", ""))),
            }
        )
    return updated


def _guess_expected_r1(sample: str, row: dict[str, Any]) -> str:
    sample_name = clean_cell(sample).strip()
    if sample_name:
        return f"{sample_name}_R1.fastq.gz"
    fq2 = scan_utils.normalize_input_value(clean_cell(row.get("fastq2", "")))
    if fq2:
        candidates = scan_utils.infer_pair_candidates(fq2)
        for cand in candidates:
            if scan_utils.read_side(cand) == "1":
                return cand
    return "<sample>_R1.fastq.gz"


def _row_sample_key(row: dict[str, str]) -> str:
    sample = clean_cell(row.get("sample", "")).strip()
    if sample:
        return f"sample:{sample}"
    fq_seed = scan_utils.normalize_input_value(clean_cell(row.get("fastq1", ""))) or scan_utils.normalize_input_value(
        clean_cell(row.get("fastq2", ""))
    )
    if fq_seed:
        return f"derived:{scan_utils.sample_base(fq_seed)}"
    return "derived:"


def auto_pair(rows: list[dict[str, Any]], available: list[str]) -> list[dict[str, str]]:
    available_set = set(available)
    rows_out = coerce_rows_raw(rows)
    used_fastq2: set[str] = set()
    paired_sample_keys: set[str] = set()
    for row in rows_out:
        fq2 = scan_utils.normalize_input_value(clean_cell(row.get("fastq2", "")))
        if fq2:
            used_fastq2.add(fq2)
        fq1 = scan_utils.normalize_input_value(clean_cell(row.get("fastq1", "")))
        if fq1 and fq2:
            paired_sample_keys.add(_row_sample_key(row))

    for row in rows_out:
        fq1 = scan_utils.normalize_input_value(clean_cell(row.get("fastq1", "")))
        fq2 = scan_utils.normalize_input_value(clean_cell(row.get("fastq2", "")))
        if not fq1 or fq2:
            continue
        if scan_utils.read_side(fq1) == "2":
            continue

        sample_key = _row_sample_key(row)
        if sample_key in paired_sample_keys:
            continue

        for candidate in scan_utils.infer_pair_candidates(fq1):
            if candidate not in available_set or candidate == fq1 or candidate in used_fastq2:
                continue
            row["fastq2"] = candidate
            used_fastq2.add(candidate)
            paired_sample_keys.add(sample_key)
            break
    return rows_out


def _normalized_sample_key(value: str) -> str:
    return clean_cell(value).strip()


def _derive_sample_from_fastq(path_value: str, fastq_pool: set[str]) -> str:
    fq = scan_utils.normalize_input_value(path_value)
    if not fq:
        return ""
    _, stem, _ = scan_utils.split_fastq_name(fq)
    read_side = scan_utils.read_side(fq)
    if not read_side:
        return stem
    for mate in scan_utils.infer_pair_candidates(fq):
        if mate in fastq_pool:
            return scan_utils.split_read_suffix(stem)[0]
    return stem


def _row_fastq_candidates(rows: list[dict[str, str]]) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in ("fastq1", "fastq2"):
            fq = scan_utils.normalize_input_value(clean_cell(row.get(key, "")))
            if not fq or fq in seen:
                continue
            seen.add(fq)
            candidates.append(fq)
    return candidates


def _pick_preferred_fastq(candidates: list[str], preferred_read: str) -> str:
    preferred, neutral, other = [], [], []
    for fq in candidates:
        side = scan_utils.read_side(fq)
        if side == preferred_read:
            preferred.append(fq)
        elif side == "":
            neutral.append(fq)
        else:
            other.append(fq)
    for bucket in (preferred, neutral, other):
        if bucket:
            return bucket[0]
    return ""


def canonicalize_rows_after_autopair(rows: list[dict[str, Any]], available: list[str] | None = None, autofill_conditions: bool = True, translate: Callable[..., str] | None = None) -> tuple[list[dict[str, str]], list[str]]:
    t = translate or (lambda key, **kwargs: key)
    grouped: dict[str, list[dict[str, str]]] = {}
    order: list[str] = []
    warnings: list[str] = []
    fastq_pool = set(available or [])
    for row in coerce_rows_raw(rows):
        fq1 = scan_utils.normalize_input_value(clean_cell(row.get("fastq1", "")))
        fq2 = scan_utils.normalize_input_value(clean_cell(row.get("fastq2", "")))
        if fq1:
            fastq_pool.add(fq1)
        if fq2:
            fastq_pool.add(fq2)

    for idx, row in enumerate(coerce_rows_raw(rows), start=1):
        sample_key = _normalized_sample_key(row.get("sample", ""))
        if not sample_key:
            seed = row.get("fastq1", "") or row.get("fastq2", "")
            sample_key = _derive_sample_from_fastq(seed, fastq_pool) if seed else f"__row_{idx}"
        if sample_key not in grouped:
            grouped[sample_key] = []
            order.append(sample_key)
        grouped[sample_key].append(row)

    canonical: list[dict[str, str]] = []
    for sample_key in order:
        members = grouped[sample_key]
        first_with_pair = next((row for row in members if row.get("fastq1") and row.get("fastq2")), None)
        baseline = first_with_pair or members[0]
        fastq_candidates = _row_fastq_candidates(members)

        conditions = [clean_cell(row.get("condition", "")).strip() for row in members if clean_cell(row.get("condition", "")).strip()]
        condition = conditions[0] if conditions else ""
        explicit_samples = [clean_cell(row.get("sample", "")).strip() for row in members if clean_cell(row.get("sample", "")).strip()]
        sample_out = explicit_samples[0] if explicit_samples else ""
        unique_conditions: list[str] = []
        for cond in conditions:
            if cond not in unique_conditions:
                unique_conditions.append(cond)
        if len(unique_conditions) > 1:
            warnings.append(t("warn.conflicting_conditions", sample=sample_out or sample_key, conditions=", ".join(unique_conditions), chosen=condition))

        if first_with_pair:
            fastq1 = scan_utils.normalize_input_value(first_with_pair.get("fastq1", ""))
            fastq2 = scan_utils.normalize_input_value(first_with_pair.get("fastq2", ""))
            if not fastq1:
                fastq1 = _pick_preferred_fastq(fastq_candidates, "1")
            if not fastq2:
                fastq2 = _pick_preferred_fastq([fq for fq in fastq_candidates if fq != fastq1], "2")
        else:
            fastq1 = _pick_preferred_fastq(fastq_candidates, "1")
            if not fastq1 and fastq_candidates:
                fastq1 = fastq_candidates[0]
            fastq2 = _pick_preferred_fastq([fq for fq in fastq_candidates if fq != fastq1], "2")

        if not sample_out:
            seed = scan_utils.normalize_input_value(clean_cell(baseline.get("fastq1", ""))) or scan_utils.normalize_input_value(clean_cell(baseline.get("fastq2", ""))) or fastq1
            sample_out = _derive_sample_from_fastq(seed, fastq_pool) if seed else ""

        if fastq1 and autofill_conditions and (not condition or condition == sample_out):
            condition_seed = sample_out or scan_utils.sample_base(fastq1)
            condition = normalize_condition_from_sample(condition_seed)

        canonical.append({"sample": sample_out, "condition": condition, "fastq1": fastq1, "fastq2": "" if fastq2 == fastq1 else fastq2})

    return canonical, warnings


def validate_rows_report(
    rows: list[dict[str, Any]],
    fastq_rel: list[str],
    paired: bool,
    ref_exists: Callable[[str], bool],
    translate: Callable[..., str],
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    searched = "*.fastq.gz, *.fq.gz, *.fastq, *.fq"
    for idx, row in enumerate(rows, start=1):
        try:
            sample = clean_cell(row.get("sample", ""))
            cond = clean_cell(row.get("condition", ""))
            fq1 = scan_utils.normalize_input_value(clean_cell(row.get("fastq1", "")))
            fq2 = scan_utils.normalize_input_value(clean_cell(row.get("fastq2", "")))
            if not sample:
                errors.append(translate("row_issue.sample_missing", row=idx))
            if sample in seen:
                errors.append(translate("row_issue.duplicate_sample", row=idx, sample=sample))
            seen.add(sample)
            if not cond:
                errors.append(translate("row_issue.condition_missing", row=idx))
            if not fq1:
                expected = _guess_expected_r1(sample, row)
                display_sample = sample or f"row{idx}"
                errors.append(f"R1 missing: sample='{display_sample}' expected='{expected}' searched: {searched}")
            elif fq1 not in fastq_rel and not ref_exists(fq1):
                display_sample = sample or f"row{idx}"
                errors.append(f"R1 missing: sample='{display_sample}' expected='{fq1}' searched: {searched}")
            if paired:
                if not fq2:
                    errors.append(translate("row_issue.fastq2_missing", row=idx))
                elif fq2 not in fastq_rel and not ref_exists(fq2):
                    errors.append(translate("row_issue.fastq2_not_found", row=idx, fastq=fq2))
        except Exception as exc:
            errors.append(f"Internal error: {exc.__class__.__name__}: {exc}")
    return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings}


def validate_rows(rows: list[dict[str, Any]], fastq_rel: list[str], paired: bool, ref_exists: Callable[[str], bool], translate: Callable[..., str]) -> list[str]:
    report = validate_rows_report(rows, fastq_rel, paired, ref_exists, translate)
    return list(report.get("errors") or [])


def condition_counts(rows: list[dict[str, Any]] | None) -> dict[str, int]:
    eligibility = evaluate_analysis_eligibility(coerce_rows_raw(rows or []))
    return dict(eligibility.condition_counts)


def format_condition_counts(counts: dict[str, int] | None) -> str:
    items = counts or {}
    return ", ".join(f"{condition}={count}" for condition, count in items.items())


def enrichment_eligibility(
    rows: list[dict[str, Any]] | None,
    *,
    min_conditions: int = 2,
    min_replicates_per_condition: int = 2,
) -> dict[str, Any]:
    eligibility = evaluate_analysis_eligibility(coerce_rows_raw(rows or []))
    counts = dict(eligibility.condition_counts)
    found_conditions = len(counts)
    if eligibility.reason_code in {
        "no_samples",
        "missing_sample",
        "missing_condition",
        "duplicate_sample",
        "single_condition",
    }:
        return {
            "ok": False,
            "reason_code": "min_conditions",
            "condition_counts": counts,
            "found_conditions": found_conditions,
            "min_conditions": min_conditions,
            "min_replicates_per_condition": min_replicates_per_condition,
        }

    insufficient = {
        condition: count
        for condition, count in counts.items()
        if count < min_replicates_per_condition
    }
    if insufficient:
        return {
            "ok": False,
            "reason_code": "min_replicates",
            "condition_counts": counts,
            "insufficient_conditions": insufficient,
            "found_conditions": found_conditions,
            "min_conditions": min_conditions,
            "min_replicates_per_condition": min_replicates_per_condition,
        }

    return {
        "ok": True,
        "reason_code": "",
        "condition_counts": counts,
        "found_conditions": found_conditions,
        "min_conditions": min_conditions,
        "min_replicates_per_condition": min_replicates_per_condition,
    }


def can_run_enrichment(
    rows: list[dict[str, Any]] | None,
    *,
    min_conditions: int = 2,
    min_replicates_per_condition: int = 2,
) -> tuple[bool, str]:
    status = enrichment_eligibility(
        rows,
        min_conditions=min_conditions,
        min_replicates_per_condition=min_replicates_per_condition,
    )
    if status["ok"]:
        return True, ""

    counts_text = format_condition_counts(status.get("condition_counts"))
    if status.get("reason_code") == "min_conditions":
        found = int(status.get("found_conditions") or 0)
        summary = counts_text or "none"
        return False, f"Enrichment requires at least {min_conditions} conditions; found {found} ({summary})."

    return (
        False,
        f"Enrichment requires at least {min_replicates_per_condition} samples per condition; current counts: {counts_text}.",
    )


def sanitize_disable_reasons(
    raw_reasons: list[Any] | None,
    rows: list[dict[str, Any]] | None,
    paired: bool,
    translate: Callable[..., str],
) -> list[str]:
    reasons: list[str] = []
    seen: set[str] = set()

    for item in raw_reasons or []:
        text = clean_cell(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        reasons.append(text)

    if reasons:
        return reasons

    for idx, row in enumerate(rows or [], start=1):
        fastq1_raw = clean_cell(row.get("fastq1", ""))
        fastq2_raw = clean_cell(row.get("fastq2", ""))
        fastq1 = scan_utils.normalize_input_value(fastq1_raw)
        fastq2 = scan_utils.normalize_input_value(fastq2_raw)

        if fastq1_raw.strip() and not fastq1:
            text = f"invalid_path: row {idx} fastq1='{fastq1_raw}'"
            if text not in seen:
                seen.add(text)
                reasons.append(text)
            continue
        if fastq2_raw.strip() and not fastq2:
            text = f"invalid_path: row {idx} fastq2='{fastq2_raw}'"
            if text not in seen:
                seen.add(text)
                reasons.append(text)
            continue
        if not fastq1:
            text = translate("row_issue.fastq1_missing", row=idx)
            if text not in seen:
                seen.add(text)
                reasons.append(text)
            continue
        if paired and not fastq2:
            text = translate("row_issue.fastq2_missing", row=idx)
            if text not in seen:
                seen.add(text)
                reasons.append(text)

    if reasons:
        return reasons
    return ["Validation failed (no detail). Check logs."]


def write_samples(output_root: Path, rows: list[dict[str, Any]], paired: bool) -> Path:
    output_dir = output_root / "metadata"
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "samples.tsv"
    header = ["sample", "condition", "fastq1"]
    if paired:
        header.append("fastq2")
    with out_path.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(header) + "\n")
        for row in rows:
            values = [
                row.get("sample", ""),
                row.get("condition", ""),
                scan_utils.normalize_input_value(row.get("fastq1", "")),
            ]
            if paired:
                values.append(scan_utils.normalize_input_value(row.get("fastq2", "")))
            handle.write("\t".join(values) + "\n")
    return out_path


def sync_rows_raw_from_editor(editor_key: str = "samples_editor") -> bool:
    global st
    if st is None:
        import streamlit as st  # type: ignore[no-redef]

    state = st.session_state.get(editor_key)
    previous_rows = coerce_rows_raw(st.session_state.get("rows_raw", []))

    if isinstance(state, pd.DataFrame):
        st.session_state["rows_raw"] = coerce_rows_raw(state.to_dict("records"))
        return True
    if isinstance(state, list):
        st.session_state["rows_raw"] = coerce_rows_raw(state)
        return True
    if not isinstance(state, dict):
        return False

    rows = [dict(row) for row in previous_rows]
    for idx in sorted(state.get("deleted_rows", []), reverse=True):
        try:
            rows.pop(int(idx))
        except (ValueError, IndexError, TypeError):
            continue

    edited_rows = state.get("edited_rows", {})
    if isinstance(edited_rows, dict):
        for idx, delta in edited_rows.items():
            try:
                row_idx = int(idx)
            except (ValueError, TypeError):
                continue
            if row_idx < 0 or row_idx >= len(rows) or not isinstance(delta, dict):
                continue
            rows[row_idx].update(delta)

    for added in state.get("added_rows", []):
        if isinstance(added, dict):
            rows.append(added)

    st.session_state["rows_raw"] = coerce_rows_raw(rows)
    return True
