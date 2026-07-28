from scripts import review_sbom_license_assertions as review


def _package(name, version, purl, license_name="NOASSERTION"):
    return {
        "name": name,
        "versionInfo": version,
        "licenseDeclared": license_name,
        "externalRefs": [
            {
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceType": "purl",
                "referenceLocator": purl,
            }
        ],
    }


def test_classifies_all_noassertion_categories():
    document = {
        "packages": [
            _package("image", "phase4", "pkg:oci/image@sha256:abc"),
            _package("demo", "1", "pkg:pypi/demo@1"),
            _package("copy", "1", "pkg:pypi/copy@1"),
            _package("copy", "1", "pkg:pypi/copy@1", "MIT"),
            _package("libc", "1", "pkg:deb/debian/libc@1"),
            _package("gplr", "1", "pkg:cran/gplr@1"),
            _package("missing", "1", "pkg:pypi/missing@1"),
        ]
    }
    evidence = {
        "python": {"demo": {"license": "MIT", "source_reference": "https://example.invalid"}},
        "r": {"gplr": {"license": "GPL-3", "repository": "CRAN", "url": ""}},
        "debian": {
            "libc": {
                "license": "BSD-3-Clause",
                "copyright_file": "/usr/share/doc/libc/copyright",
                "source_reference": "https://snapshot.debian.org/",
            }
        },
        "npm": {},
        "r_sources": {},
    }
    rows = review.classify_packages(document, evidence)
    categories = {row["name"]: row["category"] for row in rows}
    assert categories["image"] == "aggregate_or_virtual"
    assert categories["demo"] == "installed_package_metadata"
    assert categories["copy"] == "duplicate_representation"
    assert categories["libc"] == "debian_copyright_data"
    assert categories["gplr"] == "copyleft_source_availability"
    assert categories["missing"] == "genuinely_unresolved"


def test_npm_metadata_resolves_bundled_payload():
    document = {
        "packages": [
            _package(
                "bootstrap-accessibility-plugin",
                "1.0.6",
                "pkg:npm/bootstrap-accessibility-plugin@1.0.6",
            )
        ]
    }
    evidence = {
        "python": {},
        "r": {},
        "debian": {},
        "npm": {
            "bootstrap-accessibility-plugin": {
                "license": "BSD",
                "source_reference": "https://github.com/paypal/bootstrap-accessibility-plugin",
                "metadata_file": "/installed/package.json",
            }
        },
        "r_sources": {},
    }
    row = review.classify_packages(document, evidence)[0]
    assert row["category"] == "installed_package_metadata"
    assert row["license"] == "BSD"


def test_core_r_package_is_runtime_duplicate():
    document = {"packages": [_package("base", "4.5.0", "pkg:cran/base@4.5.0")]}
    row = review.classify_packages(
        document, {"python": {}, "r": {}, "debian": {}, "npm": {}}
    )[0]
    assert row["category"] == "duplicate_representation"


def test_bundled_r_source_addresses_exact_copyleft_package():
    document = {"packages": [_package("tximport", "1.36.1", "pkg:cran/tximport@1.36.1")]}
    evidence = {
        "python": {},
        "r": {"tximport": {"license": "LGPL (>=2)", "repository": "", "url": ""}},
        "debian": {},
        "npm": {},
        "r_sources": {
            "tximport": {
                "archive": "tximport_1.36.1.tar.gz",
                "sha256": "a" * 64,
                "source_url": "https://bioconductor.org/source.tar.gz",
                "version": "1.36.1",
            }
        },
    }
    row = review.classify_packages(document, evidence)[0]
    assert row["category"] == "copyleft_source_availability"
    assert row["source_obligation_addressed"] is True
    assert "exact source archive bundled" in row["evidence"]


def test_known_rpm_representation_uses_installed_debian_evidence():
    document = {"packages": [_package("libXau", "1.0.9", "pkg:rpm/almalinux/libXau@1.0.9")]}
    evidence = {
        "python": {},
        "r": {},
        "debian": {
            "libxau6": {
                "license": "MIT",
                "copyright_file": "/usr/share/doc/libxau6/copyright",
                "source_reference": "https://snapshot.debian.org/",
            }
        },
        "npm": {},
        "r_sources": {},
    }
    row = review.classify_packages(document, evidence)[0]
    assert row["category"] == "duplicate_representation"
    assert "libxau6" in row["evidence"]
