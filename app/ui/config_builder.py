from typing import Dict, Iterable, Optional


ALLOWED_ENGINES = ("real", "stub")


def normalize_engine(value: Optional[str]) -> str:
    normalized = str(value or "real").strip().lower()
    return normalized


def normalize_species(value: Optional[str]) -> str:
    return str(value or "").strip().lower()


def _prune_empty(obj):
    def is_empty(value):
        return value is None or value == "" or value == [] or value == {}

    if isinstance(obj, dict):
        cleaned = {}
        for key, value in obj.items():
            value = _prune_empty(value)
            if is_empty(value):
                continue
            cleaned[key] = value
        return cleaned
    if isinstance(obj, list):
        return [item for item in (_prune_empty(v) for v in obj) if not is_empty(item)]
    return obj


def build_ref_payload(
    *,
    species: str,
    ref_mode: str,
    ref_block: Dict[str, str],
    ref_preset: str,
    ref_release: str,
    ref_cache_dir: Optional[str],
    use_custom_refs: bool,
    reference_provenance: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    payload: Dict[str, object] = {}
    if ref_mode == "preset_cache" and ref_preset:
        payload["ref_preset"] = ref_preset
        payload["ref_release"] = ref_release or "pinned"
        if ref_cache_dir:
            payload["ref_cache_dir"] = ref_cache_dir
        if ref_block:
            payload["ref"] = {species: dict(ref_block)}
        if reference_provenance:
            payload["reference_provenance"] = dict(reference_provenance)
        return payload
    if ref_block:
        payload["ref"] = {species: dict(ref_block)}
    elif use_custom_refs:
        payload["ref"] = {species: {}}
    if reference_provenance:
        payload["reference_provenance"] = dict(reference_provenance)
    return payload


def build_config_payload(
    *,
    project_name: str = "",
    engine: str,
    species: str,
    samples: Iterable[str],
    input_root: str,
    output_root: str,
    sample_table: str,
    threads: int,
    ref_mode: str,
    ref_block: Dict[str, str],
    ref_preset: str,
    ref_release: str,
    ref_cache_dir: Optional[str],
    use_custom_refs: bool,
    contrast_mode: str = "",
    contrast_ref: str = "",
    contrast_pairs: Optional[Iterable[Iterable[str]]] = None,
    contrasts: Optional[Iterable[str]] = None,
    enrichment: Optional[Dict[str, object]] = None,
    reference_provenance: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    payload: Dict[str, object] = {
        "project_name": str(project_name or "").strip(),
        "engine": normalize_engine(engine),
        "samples": list(samples),
        "input": str(input_root),
        "output": str(output_root),
        "sample_table": str(sample_table),
        "threads": int(threads),
        "species": normalize_species(species),
    }
    payload.update(
        build_ref_payload(
            species=payload["species"],
            ref_mode=ref_mode,
            ref_block=ref_block,
            ref_preset=ref_preset,
            ref_release=ref_release,
            ref_cache_dir=ref_cache_dir,
            use_custom_refs=use_custom_refs,
            reference_provenance=reference_provenance,
        )
    )

    if contrast_mode:
        payload["contrast_mode"] = contrast_mode
    if contrast_mode == "ref" and contrast_ref:
        payload["contrast_ref"] = contrast_ref
    if contrast_mode == "select" and contrast_pairs:
        payload["contrast_pairs"] = list(contrast_pairs)
    if contrast_mode == "legacy" and contrasts:
        payload["contrasts"] = list(contrasts)
    if enrichment:
        payload["enrichment"] = enrichment

    return _prune_empty(payload)
