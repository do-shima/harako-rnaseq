# Container release publishing

This is maintainer guidance. Publication is tag-driven and disabled for pull
requests and ordinary branch pushes.

## Automated gates

The release workflow validates source metadata, tests host and container
behavior, runs smoke and report checks, audits direct runtime licenses, checks
image metadata, and refuses publication while the repository is private. A
successful public push requests BuildKit provenance and SBOM, then attests the
actual pushed digest through GitHub.

`workflow_dispatch` defaults to build/test only. Manual publication requires
`publish=true`; a pushed `v*` tag requests publication.

## Tag policy

`v0.2.0-beta.1` publishes its exact tag and `beta`. It does not publish
`latest`, `0.2`, or `0`. A stable `v0.2.0` may publish its exact tag and
`latest`. Tags are never derived from branch names.

## Manual GitHub procedure

1. Make the repository public after source and licensing review.
2. Set default Actions permissions to read repository contents.
3. Add a `main` ruleset requiring `python-tests`, `windows-path-tests`,
   `governance-docs`, and `docker-tests`.
4. Create and push an annotated release tag manually after readiness passes.
5. Monitor the `release-readiness` and `publish-image` jobs.
6. Set the GHCR package public if necessary and confirm repository linkage.
7. Verify the exact digest, SBOM, provenance, and GitHub attestation.
8. Create a GitHub prerelease manually with the immutable image reference.
9. Pull by digest from an unauthenticated environment.
10. Only then update landing pages to claim image availability.

Dependency graph and dependency review may be enabled separately. Dependabot
is limited to monthly Actions and Docker updates and cannot merge or publish.

## Build-only rehearsal

Run the workflow manually with `publish=false`. This validates the candidate
without logging in to GHCR or pushing. A private repository can use this path;
public registry attestation is not attempted.

