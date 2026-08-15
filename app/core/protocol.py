"""Explicit library-protocol policy."""

from __future__ import annotations

from pathlib import Path


FULL_LENGTH = "full_length"
THREE_PRIME_TAG = "three_prime_tag"
LEGACY_UNSPECIFIED = "legacy_unspecified"
NEW_LIBRARY_PROTOCOLS = (FULL_LENGTH, THREE_PRIME_TAG)


def is_frozen_run_config(path: str | Path | None) -> bool:
    if not path:
        return False
    config_path = Path(path)
    return config_path.name == "config_resolved.yaml" and config_path.parent.name == "run"


def resolve_library_protocol(value: object, *, legacy_frozen: bool = False) -> str:
    protocol = str(value or "").strip().lower()
    if not protocol and legacy_frozen:
        return LEGACY_UNSPECIFIED
    if protocol in NEW_LIBRARY_PROTOCOLS:
        return protocol
    if protocol == LEGACY_UNSPECIFIED and legacy_frozen:
        return protocol
    allowed = ", ".join(NEW_LIBRARY_PROTOCOLS)
    if not protocol:
        raise ValueError(f"library_protocol is required for new runs ({allowed}).")
    raise ValueError(f"Invalid library_protocol '{protocol}' (allowed for new runs: {allowed}).")
