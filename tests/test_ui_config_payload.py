from app.ui.config_builder import build_config_payload


def _build_payload(**kwargs):
    defaults = {
        "project_name": "Project250101",
        "engine": "real",
        "species": "mouse",
        "samples": ["s1"],
        "input_root": "/input",
        "output_root": "/output",
        "sample_table": "/output/metadata/samples.tsv",
        "threads": 1,
        "ref_mode": "preset_cache",
        "ref_block": {},
        "ref_preset": "mouse_ensembl_grcm39",
        "ref_release": "pinned",
        "ref_cache_dir": "/output/refs_cache",
        "use_custom_refs": False,
        "contrast_mode": "",
        "contrast_ref": "",
        "contrast_pairs": [],
        "contrasts": [],
        "enrichment": None,
    }
    defaults.update(kwargs)
    return build_config_payload(**defaults)


def main():
    rat_payload = _build_payload(species="rat", ref_preset="rat_ensembl_mratbn7_2")
    if rat_payload.get("species") != "rat":
        raise SystemExit(f"species should be rat, got: {rat_payload.get('species')}")
    if rat_payload.get("ref_preset") != "rat_ensembl_mratbn7_2":
        raise SystemExit(f"ref_preset should be canonical, got: {rat_payload.get('ref_preset')}")
    if "ref" in rat_payload:
        raise SystemExit("ref should not be present when ref_preset is used")

    unverified = _build_payload(
        reference_provenance={
            "canonical_preset": "mouse_ensembl_grcm39",
            "checksums": {
                "transcripts_fasta": "a" * 64,
                "genome_fasta": "b" * 64,
                "gtf": "c" * 64,
            },
            "checksum_verified": False,
        }
    )
    if unverified["reference_provenance"].get("checksum_verified") is not False:
        raise SystemExit("reference_provenance must retain checksum_verified=false")
    if len(unverified["reference_provenance"]["checksums"]["gtf"]) != 64:
        raise SystemExit("reference_provenance checksums must be retained")

    manual_payload = _build_payload(
        project_name="StudyA",
        species="human",
        ref_mode="fasta_gtf",
        ref_preset="",
        ref_release="",
        ref_cache_dir="",
        ref_block={
            "transcripts_fasta": "refs/human/transcripts.fa.gz",
            "genome_fasta": "refs/human/genome.fa.gz",
            "gtf": "refs/human/annotation.gtf.gz",
        },
        use_custom_refs=True,
    )
    ref_block = manual_payload.get("ref", {}).get("human", {})
    if not ref_block:
        raise SystemExit("manual ref block should be nested under species")
    if ref_block.get("transcripts_fasta") != "refs/human/transcripts.fa.gz":
        raise SystemExit("manual ref transcripts_fasta missing or incorrect")
    if manual_payload.get("project_name") != "StudyA":
        raise SystemExit("project_name should be preserved in config payload")

    qc_plan = {
        "schema_version": 1,
        "policy_version": 1,
        "mode": "qc_only",
        "structurally_valid": True,
        "eligible_for_de": False,
        "reason_code": "single_condition",
        "condition_counts": {"A": 1},
        "total_samples": 1,
        "contrast_allowed": False,
        "enrichment_allowed": False,
    }
    qc_payload = _build_payload(
        analysis_plan=qc_plan,
        requested_analysis_options={
            "contrast_mode": "ref",
            "enrichment": {"enable": True},
        },
    )
    if qc_payload.get("analysis_plan") != qc_plan:
        raise SystemExit("analysis_plan must be preserved in config payload")
    if qc_payload.get("requested_analysis_options", {}).get("enrichment", {}).get("enable") is not True:
        raise SystemExit("requested QC-only settings must be retained separately")


def test_ui_config_payload():
    main()


if __name__ == "__main__":
    main()
