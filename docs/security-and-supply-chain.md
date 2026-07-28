# Security and supply chain

Security reporting follows [SECURITY.md](../SECURITY.md). This page describes
build evidence, not vulnerability-report handling or a guarantee that an
image is defect-free.

## Dependency controls

- The Python base image is pinned by digest.
- Debian packages use a dated snapshot and pinned versions.
- Runtime and test Python dependencies use separate exact hash locks.
- Build-only Debian dependencies are removed after compilation.
- Salmon and fastp archives are verified by SHA256.
- Required R packages are asserted after installation.
- Twelve biological-reference hashes are enforced; references are not bundled.

## License evidence

[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) summarizes direct runtime
licenses. The offline inventory collector reads installed Python and R
metadata and checks binary notices. Salmon's GPL text and exact corresponding
source are included in the image. Ten exact R source packages and deterministic
manifests are included at
`/usr/share/licenses/harako-rnaseq/sources/r/`.

Transitive dependencies keep their own licenses and appear in the generated
SBOM. Neither the inventory nor SBOM is a legal opinion.

The transitive review and resolved source evidence are recorded in
[transitive-license-review.md](transitive-license-review.md).

## CI trust boundary

Pull-request workflows have read-only repository permissions, never use
`pull_request_target`, and receive no package-write permission. External
actions are pinned to full commit SHAs. Only the publication job receives
package and attestation write permissions.

## Provenance and SBOM

Published images request BuildKit provenance and an attached SBOM. GitHub also
attests the digest returned by the registry push. These records describe image
identity and build history; they do not validate biological suitability or
scientific conclusions.

## Vulnerability policy

The release candidate must be scanned as the exact local `linux/amd64` image.
A compatible-fix Critical vulnerability is blocking unless the component is
demonstrably absent from the runtime path. A remotely exploitable Critical
issue in the normal local UI is blocking. High findings require documented
component, version, reachability, fix availability, and disposition.

The verified 2026-07-28 scan is documented in
[vulnerability-review-v0.2.0-beta.1.md](vulnerability-review-v0.2.0-beta.1.md).
Trivy 0.70.0 is acquired from its immutable official release and verified
against the official checksum manifest. Releases 0.69.4 through 0.69.6 and
mutable `latest` references are rejected because of the March 2026 scanner
supply-chain incident. CI uses the full-SHA-pinned Trivy action and evaluates
the exact reviewed package/advisory/version policy.

The current candidate has explicit dispositions for every Critical and High
finding and no compatible-fix Critical finding. Accepted beta risk does not
mean the image is secure; a fresh scan remains mandatory before publication.
