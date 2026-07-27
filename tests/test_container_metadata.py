from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_declares_release_metadata_without_relicensing_image():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    for label in (
        "org.opencontainers.image.title",
        "org.opencontainers.image.description",
        "org.opencontainers.image.source",
        "org.opencontainers.image.revision",
        "org.opencontainers.image.version",
        "org.opencontainers.image.created",
        "org.opencontainers.image.documentation",
    ):
        assert label in text
    assert "org.opencontainers.image.licenses" not in text
    assert "PolyForm-Noncommercial-1.0.0 applies to Harako-RNAseq source only" in text


def test_dockerfile_installs_required_notices_and_salmon_source():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    for name in (
        "LICENSE",
        "COMMERCIAL_LICENSE.md",
        "THIRD_PARTY_NOTICES.md",
        "CITATION.cff",
        "provenance.md",
        "fastp-LICENSE",
        "Salmon-GPL-3.0",
        "Salmon-SOURCE.md",
    ):
        assert name in text
    install = (ROOT / "scripts" / "install_tools.sh").read_text(encoding="utf-8")
    assert "SALMON_SOURCE_SHA256" in install
    assert "/usr/src/salmon-${SALMON_VERSION}.tar.gz" in install


@pytest.mark.skipif(not os.environ.get("HARAKO_TEST_IMAGE"), reason="container image not supplied")
def test_built_container_release_metadata():
    image = os.environ["HARAKO_TEST_IMAGE"]
    completed = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            image,
            "bash",
            "-lc",
            "test -f /usr/share/licenses/harako-rnaseq/THIRD_PARTY_NOTICES.md "
            "&& test -f /usr/src/salmon-1.10.0.tar.gz",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
