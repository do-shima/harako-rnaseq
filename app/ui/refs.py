from __future__ import annotations

from pathlib import Path

import yaml


def load_ref_manifest(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def species_presets(manifest: dict, species: str) -> list[str]:
    presets = sorted((manifest.get("presets") or {}).keys())
    species_lower = (species or "").strip().lower()
    return [preset for preset in presets if preset.lower().startswith(species_lower)]


def preset_releases(manifest: dict, preset: str) -> list[str]:
    if not manifest or not preset:
        return ["pinned"]
    presets = manifest.get("presets") or {}
    entry = presets.get(preset) if isinstance(presets, dict) else None
    releases = list((entry or {}).keys()) if isinstance(entry, dict) else []
    if "pinned" not in releases:
        releases.insert(0, "pinned")
    uniq: list[str] = []
    for rel in releases:
        if rel not in uniq:
            uniq.append(rel)
    return uniq or ["pinned"]
