from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePath
from typing import Any, Iterable


REFERENCE_FILES = {
    "transcripts_fasta_url": "transcripts.fa.gz",
    "genome_fasta_url": "genome.fa.gz",
    "gtf_url": "annotation.gtf.gz",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ReferencePresetError(ValueError):
    pass


def validate_builtin_manifest(manifest: dict) -> None:
    if int(manifest.get("schema_version", 1)) < 2:
        return
    presets = _presets(manifest)
    metadata = manifest.get("preset_metadata", {})
    errors = []
    for preset in sorted(presets):
        item_metadata = metadata.get(preset) if isinstance(metadata, dict) else None
        pinned = (
            str((item_metadata or {}).get("pinned_release", "")).strip()
            if isinstance(item_metadata, dict)
            else ""
        )
        if not pinned:
            errors.append(f"{preset}: missing pinned_release")
            continue
        release_entry = presets[preset].get(pinned)
        if not _is_release_block(release_entry):
            errors.append(f"{preset}/{pinned}: missing release block")
            continue
        hashes = release_entry.get("sha256", {})
        for key in REFERENCE_FILES:
            value = str((hashes or {}).get(key, "")).lower()
            if not SHA256_RE.fullmatch(value):
                errors.append(f"{preset}/{pinned}/{key}: missing or invalid SHA256")
    if errors:
        raise ReferencePresetError(
            "Built-in reference manifest checksum validation failed: "
            + "; ".join(errors)
        )


def _presets(manifest: dict) -> dict:
    value = manifest.get("presets", {})
    return value if isinstance(value, dict) else {}


def _aliases(manifest: dict) -> dict:
    value = manifest.get("aliases", {})
    return value if isinstance(value, dict) else {}


def _alias_entry(manifest: dict, preset: str) -> dict | None:
    value = _aliases(manifest).get(preset)
    if isinstance(value, str):
        return {"canonical_preset": value}
    return value if isinstance(value, dict) else None


def resolve_preset_id(manifest: dict, requested_preset: str) -> str:
    current = str(requested_preset or "").strip()
    if not current:
        raise ReferencePresetError("Reference preset is required.")
    seen: list[str] = []
    while current not in _presets(manifest):
        if current in seen:
            chain = " -> ".join([*seen, current])
            raise ReferencePresetError(f"Reference preset alias cycle: {chain}")
        seen.append(current)
        entry = _alias_entry(manifest, current)
        target = str((entry or {}).get("canonical_preset", "")).strip()
        if not target:
            raise ReferencePresetError(f"Unknown reference preset: {requested_preset}")
        current = target
    return current


def get_preset_metadata(manifest: dict, preset: str) -> dict:
    canonical = resolve_preset_id(manifest, preset)
    metadata = manifest.get("preset_metadata", {})
    if isinstance(metadata, dict) and isinstance(metadata.get(canonical), dict):
        return dict(metadata[canonical])
    # Legacy schema fallback: retain readability without inventing provenance.
    species = canonical.split("_", 1)[0] if "_" in canonical else ""
    return {
        "provider": "unknown",
        "species": species or "unknown",
        "assembly": "unknown",
        "annotation_release": "unknown",
        "display_name": canonical,
    }


def resolve_preset_release(
    manifest: dict, requested_preset: str, requested_release: str | None
) -> tuple[str, str]:
    canonical = resolve_preset_id(manifest, requested_preset)
    release = str(requested_release or "pinned").strip() or "pinned"
    entry = _alias_entry(manifest, requested_preset)
    release_map = (entry or {}).get("release_map", {})
    if isinstance(release_map, dict):
        release = str(release_map.get(release, release))
    if release == "pinned":
        pinned = get_preset_metadata(manifest, canonical).get("pinned_release")
        if pinned:
            release = str(pinned)
        elif "pinned" in (_presets(manifest).get(canonical) or {}):
            release = "pinned"
    releases = get_preset_releases(manifest, canonical, include_pinned=False)
    if release == "pinned" and _is_release_block(
        (_presets(manifest).get(canonical) or {}).get("pinned")
    ):
        releases.insert(0, "pinned")
    if release not in releases:
        raise ReferencePresetError(
            f"Unknown release '{requested_release or 'pinned'}' for preset "
            f"'{requested_preset}' (resolved to {canonical})."
        )
    return canonical, release


def _is_release_block(value: Any) -> bool:
    return isinstance(value, dict) and any(key in value for key in REFERENCE_FILES)


def get_preset_releases(
    manifest: dict, preset: str, *, include_pinned: bool = True
) -> list[str]:
    canonical = resolve_preset_id(manifest, preset)
    entry = _presets(manifest).get(canonical, {})
    releases = [
        key
        for key, value in entry.items()
        if key != "pinned" and _is_release_block(value)
    ]
    if include_pinned:
        metadata = get_preset_metadata(manifest, canonical)
        if metadata.get("pinned_release") or _is_release_block(entry.get("pinned")):
            releases.insert(0, "pinned")
    return list(dict.fromkeys(releases))


def get_legacy_aliases_for_preset(manifest: dict, canonical_preset: str) -> list[str]:
    canonical = resolve_preset_id(manifest, canonical_preset)
    result = []
    for alias in _aliases(manifest):
        try:
            if resolve_preset_id(manifest, alias) == canonical:
                result.append(alias)
        except ReferencePresetError:
            continue
    return sorted(result)


def get_release_entry(manifest: dict, preset: str, release: str | None) -> tuple[str, str, dict]:
    canonical, canonical_release = resolve_preset_release(manifest, preset, release)
    entry = (_presets(manifest).get(canonical) or {}).get(canonical_release)
    if not _is_release_block(entry):
        raise ReferencePresetError(
            f"Manifest entry missing for {canonical}/{canonical_release}."
        )
    return canonical, canonical_release, entry


def expected_reference_paths(directory: Path | PurePath) -> dict[str, Path | PurePath]:
    return {key: directory / name for key, name in REFERENCE_FILES.items()}


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _bundle_status(directory: Path, release_entry: dict, require_checksums: bool) -> dict:
    paths = expected_reference_paths(directory)
    if not all(Path(path).is_file() and Path(path).stat().st_size > 0 for path in paths.values()):
        return {"exists": False, "verified": False, "paths": paths}
    expected = release_entry.get("sha256", {})
    complete_hashes = isinstance(expected, dict) and all(
        isinstance(expected.get(key), str) and len(expected[key]) == 64
        for key in REFERENCE_FILES
    )
    if require_checksums and not complete_hashes:
        return {"exists": True, "verified": False, "paths": paths}
    if complete_hashes:
        verified = all(
            file_sha256(Path(paths[key])) == expected[key].lower()
            for key in REFERENCE_FILES
        )
        return {
            "exists": True,
            "verified": verified,
            "checksum_available": True,
            "paths": paths,
        }
    return {
        "exists": True,
        "verified": False,
        "checksum_available": False,
        "paths": paths,
    }


def iter_cache_candidates(
    manifest: dict,
    cache_dir: Path | PurePath,
    requested_preset: str,
    requested_release: str | None,
) -> Iterable[dict]:
    canonical, canonical_release = resolve_preset_release(
        manifest, requested_preset, requested_release
    )
    yield {
        "preset": canonical,
        "release": canonical_release,
        "directory": cache_dir / canonical / canonical_release,
        "cache_source": "canonical",
        "strict_checksum": False,
    }
    aliases = get_legacy_aliases_for_preset(manifest, canonical)
    for alias in aliases:
        yield {
            "preset": alias,
            "release": canonical_release,
            "directory": cache_dir / alias / canonical_release,
            "cache_source": "legacy_alias",
            "strict_checksum": False,
        }
    for alias in aliases:
        release_map = (_alias_entry(manifest, alias) or {}).get("release_map", {})
        if not isinstance(release_map, dict):
            continue
        for legacy_release, mapped_release in release_map.items():
            if legacy_release == "pinned":
                continue
            mapped = str(mapped_release)
            if mapped == "pinned":
                mapped = str(
                    get_preset_metadata(manifest, canonical).get(
                        "pinned_release", "pinned"
                    )
                )
            if mapped != canonical_release or legacy_release == canonical_release:
                continue
            yield {
                "preset": alias,
                "release": str(legacy_release),
                "directory": cache_dir / alias / str(legacy_release),
                "cache_source": "legacy_alias",
                "strict_checksum": True,
            }


def resolve_existing_cache_paths(
    manifest: dict,
    cache_dir: Path | PurePath,
    requested_preset: str,
    requested_release: str | None,
) -> dict | None:
    canonical, canonical_release, release_entry = get_release_entry(
        manifest, requested_preset, requested_release
    )
    for candidate in iter_cache_candidates(
        manifest, cache_dir, requested_preset, requested_release
    ):
        status = _bundle_status(
            Path(candidate["directory"]),
            release_entry,
            require_checksums=bool(candidate["strict_checksum"]),
        )
        if not status["exists"]:
            continue
        if status.get("checksum_available") and not status["verified"]:
            continue
        if candidate["strict_checksum"] and not status["verified"]:
            continue
        return {
            **candidate,
            **status,
            "requested_preset": requested_preset,
            "requested_release": str(requested_release or "pinned"),
            "canonical_preset": canonical,
            "manifest_release": canonical_release,
        }
    return None


def build_reference_provenance(
    manifest: dict,
    requested_preset: str,
    requested_release: str | None,
    *,
    paths: dict[str, str] | None = None,
    checksum_verified: bool = False,
    cache_source: str = "canonical",
) -> dict:
    canonical, canonical_release = resolve_preset_release(
        manifest, requested_preset, requested_release
    )
    metadata = get_preset_metadata(manifest, canonical)
    _, _, release_entry = get_release_entry(
        manifest, requested_preset, requested_release
    )
    manifest_hashes = release_entry.get("sha256", {})
    checksums = {
        "transcripts_fasta": manifest_hashes.get("transcripts_fasta_url", ""),
        "genome_fasta": manifest_hashes.get("genome_fasta_url", ""),
        "gtf": manifest_hashes.get("gtf_url", ""),
    }
    result = {
        "requested_preset": requested_preset,
        "canonical_preset": canonical,
        "provider": metadata.get("provider", "unknown"),
        "species": metadata.get("species", "unknown"),
        "assembly": metadata.get("assembly", "unknown"),
        "annotation_release": str(metadata.get("annotation_release", "unknown")),
        "manifest_release": canonical_release,
        "checksum_verified": bool(checksum_verified),
        "cache_source": cache_source,
        "checksums": checksums,
    }
    if paths:
        result.update(paths)
    return result


def build_custom_reference_provenance(species: str, paths: dict[str, str]) -> dict:
    checksums = {}
    for key in ("transcripts_fasta", "genome_fasta", "gtf"):
        value = paths.get(key)
        if not value:
            continue
        path = Path(value)
        if path.is_file() and path.stat().st_size > 0:
            checksums[key] = file_sha256(path)
    result = {
        "provider": "custom",
        "species": species or "unknown",
        "assembly": "unknown",
        "annotation_release": "unknown",
        "manifest_release": "custom",
        "canonical_preset": "custom",
        "checksum_verified": False,
        "local_checksums_calculated": bool(checksums),
        "cache_source": "custom",
    }
    if checksums:
        result["checksums"] = checksums
    result.update(paths)
    return result
