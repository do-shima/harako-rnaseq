"""Reference selection, cache discovery, and fetch presentation."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import streamlit as st

from app.adapters.process import PIPE, start_process
from app.ui import refs as ui_refs
from app.ui import state as ui_state
from app.ui.config_builder import normalize_species


@dataclass(frozen=True)
class ReferencePageContext:
    input_root: Path
    output_root: Path
    repository_root: Path
    manifest_path: Path
    timezone: tzinfo
    page_key: str
    translate: Callable[..., str]
    get_run_config: Callable[[], dict[str, Any]]
    update_run_config: Callable[[dict[str, Any]], None]
    cache_ref_paths: Callable[..., Any]
    human_bytes: Callable[..., Any]
    load_manifest: Callable[..., Any]
    normalize_reference: Callable[..., Any]
    pick_candidate: Callable[..., Any]
    preset_releases: Callable[..., Any]
    reference_cache_root: Callable[..., Any]
    fetch_error_message: Callable[..., Any]
    fetch_state_key: Callable[..., Any]
    reference_state_snapshot: Callable[..., Any]
    reference_status_table: Callable[..., Any]
    relative_path: Callable[..., Any]
    scan_fastq: Callable[..., Any]
    scan_references: Callable[..., Any]


def render_reference_page(context: ReferencePageContext) -> None:
    INPUT_ROOT = context.input_root
    OUTPUT_ROOT = context.output_root
    REPO_ROOT = context.repository_root
    REF_MANIFEST_PATH = context.manifest_path
    JST = context.timezone
    page_key = context.page_key
    t = context.translate
    _get_run_config = context.get_run_config
    updateRunConfig = context.update_run_config
    _cache_ref_paths = context.cache_ref_paths
    _human = context.human_bytes
    _load_ref_manifest = context.load_manifest
    _normalize_ref = context.normalize_reference
    _pick_ref_candidate = context.pick_candidate
    _preset_releases = context.preset_releases
    _ref_cache_root = context.reference_cache_root
    _ref_fetch_error_message = context.fetch_error_message
    _ref_fetch_state_key = context.fetch_state_key
    _ref_state_snapshot = context.reference_state_snapshot
    _ref_status_table = context.reference_status_table
    _rel = context.relative_path
    _scan_fastq_selected = context.scan_fastq
    _scan_refs = context.scan_references
    st.subheader(t("label.reference_files"))
    st.caption(t("step_desc.reference"))
    manifest = _load_ref_manifest()
    refs_rel = st.session_state.refs_rel
    fasta_rel = refs_rel.get("fasta", [])
    gtf_rel = refs_rel.get("gtf", [])

    run_config = _get_run_config()
    ref_fetch_state = st.session_state.setdefault("ref_fetch_state", {})
    ref_state_key = _ref_fetch_state_key(run_config)
    use_custom_refs_key = f"{page_key}:use_custom_refs"
    use_custom_refs_value = st.checkbox(
        t("label.use_custom_refs"),
        value=bool(run_config.get("use_custom_refs", False)),
        key=use_custom_refs_key,
    )
    if use_custom_refs_value != bool(run_config.get("use_custom_refs", False)):
        updateRunConfig({"use_custom_refs": use_custom_refs_value})
        run_config = _get_run_config()
        ref_state_key = _ref_fetch_state_key(run_config)
    use_custom_refs = bool(run_config.get("use_custom_refs", False))

    ref_cache_root = _ref_cache_root()
    species_choices = []
    for preset in (
        "mouse_ensembl_grcm38",
        "mouse_ensembl_grcm39",
        "human_ensembl_grch38",
        "rat_ensembl_mratbn7_2",
    ):
        metadata = ui_refs.get_preset_metadata(manifest, preset)
        species_choices.append(
            {
                "label": metadata["display_name"],
                "species": metadata["species"],
                "preset": preset,
            }
        )
    labels = [choice["label"] for choice in species_choices]
    run_config = _get_run_config()
    migration_notice = run_config.get("_ref_migration_notice")
    notice_key = json.dumps(migration_notice, sort_keys=True) if migration_notice else ""
    if migration_notice and st.session_state.get("_shown_ref_migration_notice") != notice_key:
        st.warning(t("warn.ref_preset_migrated", **migration_notice))
        st.session_state["_shown_ref_migration_notice"] = notice_key
    preset_value = run_config.get("ref_preset", "")
    species_value = normalize_species(run_config.get("species"))
    selected_index = 0
    for idx, choice in enumerate(species_choices):
        if preset_value and choice["preset"] == preset_value:
            selected_index = idx
            break
        if not preset_value and choice["species"] == species_value:
            selected_index = idx
    species_label = st.selectbox(
        t("label.species_build"),
        labels,
        index=selected_index,
        key=f"{page_key}:species_build",
    )
    selected = species_choices[labels.index(species_label)]
    if selected["species"] != species_value:
        updateRunConfig({"species": selected["species"]})
        run_config = _get_run_config()
        species_value = normalize_species(run_config.get("species"))
        preset_value = run_config.get("ref_preset", "")
    if not use_custom_refs and selected["preset"] and selected["preset"] != preset_value:
        updateRunConfig({"ref_preset": selected["preset"]})
        run_config = _get_run_config()
        preset_value = run_config.get("ref_preset", "")

    if not use_custom_refs:
        presets_all = manifest.get("presets") or {}
        preset_available = preset_value in presets_all
        if not preset_available:
            st.warning(t("warn.preset_unavailable", preset=preset_value))
        release_options = _preset_releases(manifest, preset_value) if preset_available else ["pinned"]
        if not release_options:
            release_options = ["pinned"]
        run_config = _get_run_config()
        release_value = run_config.get("ref_release") or "pinned"
        if release_value not in release_options:
            release_value = release_options[0]
            updateRunConfig({"ref_release": release_value})
        release_index = release_options.index(release_value) if release_value in release_options else 0
        release_choice = st.selectbox(
            t("label.release"),
            release_options,
            index=release_index,
            help=t("help.ref_release"),
            disabled=not preset_available,
            key=f"{page_key}:ref_release",
        )
        if release_choice != release_value:
            updateRunConfig({"ref_release": release_choice})
            release_value = release_choice
        run_config = _get_run_config()
        ref_state_key = _ref_fetch_state_key(run_config)

        preset = preset_value
        release = release_value
        if not preset:
            st.warning(t("ref_error.missing_ref_preset"))
            cache_ok = False
            rows = []
        else:
            cache_ok, rows = _ref_status_table("preset_cache", {}, preset, release)
            cache_resolution = ui_refs.resolve_existing_cache_paths(
                manifest, ref_cache_root, preset, release
            )
            if cache_resolution and cache_resolution["cache_source"] == "legacy_alias":
                st.info(
                    t(
                        "info.legacy_ref_cache_reused",
                        preset=cache_resolution["preset"],
                        release=cache_resolution["release"],
                    )
                )
            _, _, release_entry = ui_refs.get_release_entry(
                manifest, preset, release
            )
            hashes = release_entry.get("sha256", {})
            hashes_complete = all(hashes.get(key) for key in ui_refs.REFERENCE_FILES)
            if not hashes_complete:
                st.warning(t("warn.reference_unverified"))
            cache_dir = _cache_ref_paths(preset, release, ref_cache_root)["gtf"].parent
            try:
                display_cache_dir = cache_dir.relative_to(OUTPUT_ROOT)
            except ValueError:
                display_cache_dir = cache_dir
            st.write(t("label.cache_directory", path=display_cache_dir))
            df_rows = pd.DataFrame(rows)
            if not df_rows.empty:
                df_rows["status"] = df_rows["status"].map(
                    {"present": t("status.present"), "missing": t("status.missing"), "invalid": t("status.invalid")}
                )
            st.dataframe(df_rows, width="stretch", hide_index=True)
            if not cache_ok:
                st.caption(t("msg.refs_download_needed"))

            overwrite_refs = st.checkbox(
                t("label.ref_download_overwrite"),
                value=False,
                key=f"{page_key}:ref_download_overwrite",
            )
            fetch_disabled = (
                (cache_ok and not overwrite_refs)
                or (not preset_available)
                or (not hashes_complete)
            )
            locate_disabled = not preset_available
            st.caption(t("desc.locate_refs_local"))
            st.caption(
                t(
                    "label.locate_scan_dirs",
                    ref_cache_dir=str(ref_cache_root),
                    preset_cache_dir=str(cache_dir),
                )
            )
            if st.button(t("btn.download_refs"), disabled=locate_disabled):
                locate_ok, locate_rows = _ref_status_table("preset_cache", {}, preset, release)
                locate_df = pd.DataFrame(locate_rows)
                if not locate_df.empty:
                    locate_df["status"] = locate_df["status"].map(
                        {"present": t("status.present"), "missing": t("status.missing"), "invalid": t("status.invalid")}
                    )
                st.dataframe(locate_df, width="stretch", hide_index=True)
                ref_fetch_state[ref_state_key] = {
                    "status": "success" if locate_ok else "error",
                    "updated_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S %Z"),
                    "message": t("status.present") if locate_ok else t("status.missing"),
                }

            st.caption(t("desc.download_refs_url"))
            if st.button(t("btn.download_refs_url"), disabled=fetch_disabled):
                ref_fetch_state[ref_state_key] = {
                    "status": "running",
                    "updated_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S %Z"),
                    "message": "fetch started",
                }
                cmd = [
                    "python",
                    str(REPO_ROOT / "scripts" / "fetch_reference_preset.py"),
                    "--preset",
                    preset,
                    "--release",
                    release,
                    "--cache-dir",
                    str(ref_cache_root),
                    "--manifest",
                    str(REF_MANIFEST_PATH),
                    "--progress-jsonl",
                ]
                if overwrite_refs:
                    cmd.append("--overwrite")
                pinned_dir = _cache_ref_paths(preset, release, ref_cache_root)["gtf"].parent
                paths = {
                    "transcripts": pinned_dir / "transcripts.fa.gz",
                    "genome": pinned_dir / "genome.fa.gz",
                    "gtf": pinned_dir / "annotation.gtf.gz",
                }
                file_state = {
                    key: {"downloaded": 0, "total": None, "done": False}
                    for key in paths
                }
                stdout_extra = []
                with st.status(t("status.fetch_refs_running"), state="running") as status:
                    prog = st.progress(0.0)
                    lines = st.empty()
                    proc = start_process(
                        cmd,
                        stdout=PIPE,
                        stderr=PIPE,
                        text=True,
                        bufsize=1,
                    )
                    if proc.stdout is not None:
                        for raw in proc.stdout:
                            line = raw.strip()
                            if not line:
                                continue
                            try:
                                event = json.loads(line)
                            except json.JSONDecodeError:
                                stdout_extra.append(line)
                                continue
                            event_type = event.get("event")
                            label = event.get("file")
                            if label in file_state:
                                if event_type == "start":
                                    file_state[label]["total"] = event.get("total")
                                elif event_type == "chunk":
                                    file_state[label]["downloaded"] = event.get("downloaded", 0)
                                    if event.get("total") is not None:
                                        file_state[label]["total"] = event.get("total")
                                elif event_type == "done":
                                    file_state[label]["done"] = True
                                    dest = event.get("dest")
                                    if dest and os.path.exists(dest):
                                        file_state[label]["downloaded"] = os.path.getsize(dest)
                            done = sum(1 for s in file_state.values() if s["done"])
                            prog.progress(done / 3.0)
                            status_lines = []
                            for key, state in file_state.items():
                                if state["done"]:
                                    status_lines.append(f"{key}: done ({_human(state['downloaded'])})")
                                elif state["downloaded"]:
                                    if state["total"]:
                                        pct = state["downloaded"] * 100.0 / state["total"]
                                        status_lines.append(
                                            f"{key}: {_human(state['downloaded'])}/{_human(state['total'])} ({pct:.1f}%)"
                                        )
                                    else:
                                        status_lines.append(f"{key}: {_human(state['downloaded'])}")
                                else:
                                    status_lines.append(f"{key}: (not started)")
                            lines.text("\n".join(status_lines))
                    rc = proc.wait()
                    stderr = (proc.stderr.read() if proc.stderr else "").strip()
                    done = sum(1 for s in file_state.values() if s["done"])
                    prog.progress(done / 3.0)
                    if rc == 0 and done == 3:
                        updateRunConfig(
                            {
                                "use_custom_refs": False,
                                "ref_mode": "preset_cache",
                                "ref_transcripts": "",
                                "ref_genome": "",
                                "ref_gtf": "",
                            }
                        )
                        selected_subdirs = list(_get_run_config().get("selected_subdirs") or [])
                        st.session_state.fastq_rel = [_rel(p) for p in _scan_fastq_selected(INPUT_ROOT, selected_subdirs)]
                        fasta, gtf = _scan_refs(INPUT_ROOT)
                        st.session_state.refs_rel = {
                            "fasta": [_rel(p) for p in fasta],
                            "gtf": [_rel(p) for p in gtf],
                        }
                        ref_fetch_state[ref_state_key] = {
                            "status": "success",
                            "updated_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S %Z"),
                            "message": t("success.ref_fetch_completed"),
                        }
                        status.update(label=t("success.ref_fetch_completed"), state="complete")
                        with st.expander(t("label.details")):
                            if stdout_extra:
                                st.text_area("Fetch refs (URL) stdout", "\n".join(stdout_extra), height=140)
                            if stderr:
                                st.text_area("Fetch refs (URL) stderr", stderr, height=140)
                        st.rerun()
                    else:
                        ref_fetch_state[ref_state_key] = {
                            "status": "error",
                            "updated_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S %Z"),
                            "message": _ref_fetch_error_message(rc, stderr or "\n".join(stdout_extra)),
                        }
                        status.update(label=t("status.fetch_refs_failed"), state="error")
                        st.error(_ref_fetch_error_message(rc, stderr or "\n".join(stdout_extra)))
                        st.warning(t("warn.ref_fetch_custom_fallback"))
                        st.code(
                            "refs/transcripts.fa.gz\n"
                            "refs/genome.fa.gz\n"
                            "refs/annotation.gtf.gz"
                        )
                        if stdout_extra:
                            st.text_area("Fetch refs (URL) stdout", "\n".join(stdout_extra), height=140)

        if cache_ok:
            st.caption(t("info.using_cached_refs"))
        else:
            st.warning(t("warning.fetch_refs_to_enable"))
        latest = ref_fetch_state.get(ref_state_key)
        if latest:
            st.caption(f"[fetch:{latest.get('status')}] {latest.get('updated_at')} - {latest.get('message')}")
    else:
        mode_options = ["fasta_gtf", "transcripts_only"]
        mode_value = run_config.get("ref_mode", "fasta_gtf")
        if mode_value not in mode_options:
            mode_value = "fasta_gtf"
        mode = st.selectbox(
            t("label.reference_mode"),
            mode_options,
            index=mode_options.index(mode_value),
            key=f"{page_key}:ref_mode",
        )
        if mode != run_config.get("ref_mode"):
            updateRunConfig({"ref_mode": mode})
        if mode in ("fasta_gtf", "transcripts_only") and not fasta_rel:
            st.error(t("error.no_fasta"))
            st.stop()
        if mode == "fasta_gtf" and not gtf_rel:
            st.error(t("error.no_gtf"))
            st.stop()

        transcript_options = fasta_rel or [""]
        genome_options = fasta_rel or [""]
        gtf_options = gtf_rel or [""]
        ref_transcripts_value = _normalize_ref(run_config.get("ref_transcripts", "")) or _pick_ref_candidate(fasta_rel, ["transcript", "cdna"])
        ref_genome_value = _normalize_ref(run_config.get("ref_genome", "")) or _pick_ref_candidate(fasta_rel, ["genome"])
        ref_gtf_value = _normalize_ref(run_config.get("ref_gtf", "")) or _pick_ref_candidate(gtf_rel, ["gtf"])
        if ref_transcripts_value and ref_transcripts_value not in transcript_options:
            transcript_options = [ref_transcripts_value] + transcript_options
        if ref_genome_value and ref_genome_value not in genome_options:
            genome_options = [ref_genome_value] + genome_options
        if ref_gtf_value and ref_gtf_value not in gtf_options:
            gtf_options = [ref_gtf_value] + gtf_options

        if mode == "transcripts_only":
            transcripts_choice = st.selectbox(
                t("label.transcripts_fasta"),
                transcript_options,
                index=transcript_options.index(ref_transcripts_value) if ref_transcripts_value in transcript_options else 0,
                key=f"{page_key}:ref_transcripts",
            )
            updateRunConfig(
                {
                    "use_custom_refs": True,
                    "ref_mode": "transcripts_only",
                    "ref_transcripts": _normalize_ref(transcripts_choice),
                    "ref_genome": "",
                    "ref_gtf": "",
                }
            )
        else:
            transcripts_choice = st.selectbox(
                t("label.transcripts_fasta"),
                transcript_options,
                index=transcript_options.index(ref_transcripts_value) if ref_transcripts_value in transcript_options else 0,
                key=f"{page_key}:ref_transcripts",
            )
            genome_choice = st.selectbox(
                t("label.genome_fasta"),
                genome_options,
                index=genome_options.index(ref_genome_value) if ref_genome_value in genome_options else 0,
                key=f"{page_key}:ref_genome",
            )
            gtf_choice = st.selectbox(
                t("label.gtf"),
                gtf_options,
                index=gtf_options.index(ref_gtf_value) if ref_gtf_value in gtf_options else 0,
                key=f"{page_key}:ref_gtf",
            )
            updateRunConfig(
                {
                    "use_custom_refs": True,
                    "ref_mode": "fasta_gtf",
                    "ref_transcripts": _normalize_ref(transcripts_choice),
                    "ref_genome": _normalize_ref(genome_choice),
                    "ref_gtf": _normalize_ref(gtf_choice),
                }
            )

        ref_block = {
            "transcripts_fasta": _normalize_ref(_get_run_config().get("ref_transcripts", "")),
            "genome_fasta": _normalize_ref(_get_run_config().get("ref_genome", "")),
            "gtf": _normalize_ref(_get_run_config().get("ref_gtf", "")),
        }
        custom_ok, rows = _ref_status_table(mode, ref_block, "", "")
        df_rows = pd.DataFrame(rows)
        if not df_rows.empty:
            df_rows["status"] = df_rows["status"].map(
                {"present": t("status.present"), "missing": t("status.missing"), "invalid": t("status.invalid")}
            )
        st.dataframe(df_rows, width="stretch", hide_index=True)
        if not custom_ok:
            st.caption(t("msg.refs_download_needed"))

    current_ref_state = _ref_state_snapshot()
    prev_ref_state = st.session_state.get("last_ref_state")
    if prev_ref_state is not None and prev_ref_state != current_ref_state:
        ui_state.mark_user_edit()
    st.session_state.last_ref_state = current_ref_state
