from __future__ import annotations

import json

from scripts import collect_runtime_license_inventory as inventory


def test_inventory_is_deterministic_and_direct(monkeypatch):
    monkeypatch.setattr(
        inventory,
        "_python_records",
        lambda: [
            inventory._record(
                "Snakemake", "9.13.4", "python", "MIT", "installed metadata"
            )
        ],
    )
    monkeypatch.setattr(
        inventory,
        "_r_records",
        lambda: [
            inventory._record(
                "DESeq2", "1.48.2", "R", "LGPL-3.0-or-later", "DESCRIPTION"
            )
        ],
    )
    monkeypatch.setattr(inventory, "_command_version", lambda command: "1.0")
    rows = inventory.collect_inventory()
    assert rows == sorted(
        rows, key=lambda item: (item["ecosystem"].lower(), item["component"].lower())
    )
    assert all(row["direct_dependency"] for row in rows)
    unresolved = [row for row in rows if row["unresolved"]]
    assert all(row["ecosystem"] == "operating-system" for row in unresolved)
    json.dumps(rows)


def test_expected_direct_component_sets_are_complete():
    assert set(inventory.PYTHON_PACKAGES) == {
        "snakemake",
        "streamlit",
        "pandas",
        "PyYAML",
        "typer",
    }
    assert {
        "DESeq2",
        "tximport",
        "clusterProfiler",
        "org.Hs.eg.db",
        "org.Mm.eg.db",
        "org.Rn.eg.db",
    } <= set(inventory.R_PACKAGES)
