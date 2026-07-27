from __future__ import annotations

from pathlib import Path

import yaml

from app.reference_presets import (
    REFERENCE_FILES,
    ReferencePresetError,
    build_custom_reference_provenance,
    build_reference_provenance,
    get_legacy_aliases_for_preset,
    get_release_entry,
    get_preset_metadata,
    get_preset_releases,
    resolve_existing_cache_paths,
    resolve_preset_id,
    resolve_preset_release,
    validate_builtin_manifest,
)


def load_ref_manifest(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        manifest = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    validate_builtin_manifest(manifest)
    return manifest


def species_presets(manifest: dict, species: str) -> list[str]:
    presets = sorted((manifest.get("presets") or {}).keys())
    species_lower = (species or "").strip().lower()
    result = []
    for preset in presets:
        try:
            metadata = get_preset_metadata(manifest, preset)
        except ReferencePresetError:
            continue
        if str(metadata.get("species", "")).lower() == species_lower:
            result.append(preset)
    return result


def preset_releases(manifest: dict, preset: str) -> list[str]:
    if not manifest or not preset:
        return ["pinned"]
    try:
        return get_preset_releases(manifest, preset) or ["pinned"]
    except ReferencePresetError:
        return ["pinned"]
