# Public-beta launch runbook

This runbook contains manual actions. Do not run publication steps until every
blocking audit is resolved.

## A. Before visibility change

- [ ] Approve author/committer identity inventory.
- [x] Institutional commit identity disclosure approved without reproducing
  the address in tracked release records.
- [x] Reject disclosure of the reviewed historical local path and verify its
  removal from the rewritten public candidate.
- [ ] Verify the ignored history-rewrite evidence hash, rewritten base,
  current history audit, and zero-occurrence report.
- [ ] Approve the reachable-history scan and its generated-file findings.
- [ ] Complete the explicit branch/tag decisions in
  [the ref disposition record](releases/v0.2.0-beta.1-ref-disposition.md).
- [ ] Approve the reachable large-blob inventory.
- [ ] Approve direct and transitive license reviews.
- [x] Resolve the verified vulnerability scan and Critical/High dispositions.
- [x] Verify all ten corresponding R source archives in the candidate image.
- [ ] Confirm `python-tests`, `windows-path-tests`, `governance-docs`, and
  `docker-tests` are green on `main`.
- [ ] Confirm a repository backup.
- [ ] Confirm institutional approval if required.

Recommended ref review:

| Ref | Recommendation |
| --- | --- |
| Rewritten `main` | Publish as the only initial ref |
| Existing tags, including `v0.1.0` | Keep only in the private archive |
| Merged Codex/development branches | Omit from the new repository |
| Unique local branches | Keep private pending separate review |
| Pull Request and remote-tracking refs | Omit from the new repository |

## B. Create and verify the sanitized repository

- [ ] Keep the existing repository private and rename it as a private archive.
- [ ] Create a new, empty private `do-shima/harako-rnaseq` repository.
- [ ] Push only the final sanitized `refs/heads/main`.
- [ ] Fresh-clone the new private repository and confirm the local branch is
  `main`, the only remote is the expected `origin`, the only remote-tracking
  branch is `origin/main` (with optional symbolic `origin/HEAD`), and there are
  no tags, development branches, or Pull Request refs.
- [ ] Independently run `git ls-remote --heads origin` and
  `git ls-remote --tags origin`; confirm the server advertises only `main` and
  no tags.
- [ ] Repeat the zero-occurrence history audit and full CI in that fresh clone.
- [ ] Configure repository rules, Issues, Actions, and GHCR linkage.
- [ ] Open GitHub **Settings → General → Danger Zone** only after those checks.
- [ ] Change only the new sanitized repository to public.
- [ ] Immediately inspect README, LICENSE, Security, Issues, Actions, branches,
  and tags as an unauthenticated visitor.
- [ ] Confirm no Actions secret is exposed.
- [ ] Confirm secret scanning and dependency graph settings as applicable.

The private archive must not be made public or used as a redirect target.
Rewriting cannot guarantee removal from independent third-party clones, but
the new-repository approach keeps old GitHub Pull Request refs and cached
commit views confined to the private archive.

The offline candidate checker accepts either an isolated candidate with no
remote or a fresh verification clone with exactly the expected `origin`.
It does not contact the network, and a configured remote alone does not prove
that the server has no additional refs.

## C. Configure repository rules

- [ ] Require `python-tests`.
- [ ] Require `windows-path-tests`.
- [ ] Require `governance-docs`.
- [ ] Require `docker-tests`.
- [ ] Require branches to be up to date.
- [ ] Prevent force pushes and deletion of `main` where appropriate.
- [ ] Record whether administrator bypass remains enabled.

## D. Prepare the release commit

- [ ] Confirm `main` is clean.
- [ ] Add a release date only when known.
- [ ] Run `just ci-all`.
- [ ] Run the strict build-only release-readiness check.
- [ ] Confirm documentation still does not claim GHCR availability.

## E. Create and push the annotated beta tag

Run manually only after approval:

```bash
git switch main
git pull --ff-only
git status --short
git tag -a v0.2.0-beta.1 -m "Harako-RNAseq v0.2.0-beta.1 public beta"
git show v0.2.0-beta.1
git push origin v0.2.0-beta.1
```

## F. Monitor image publication

- [ ] Verify the `publish-image` workflow succeeds.
- [ ] Verify exact `v0.2.0-beta.1` and floating `beta` tags.
- [ ] Verify there is no `latest` tag.
- [ ] Record the immutable image digest.
- [ ] Verify `linux/amd64`.
- [ ] Inspect the attached SBOM and BuildKit provenance.
- [ ] Verify the GitHub attestation against the pushed digest.
- [ ] Inspect `/usr/share/licenses/harako-rnaseq/` inside the image.
- [ ] Pull and run the exact digest.

## G. GHCR package settings

- [ ] Make the package public.
- [ ] Link it to the repository.
- [ ] Verify inherited permissions.
- [ ] Verify anonymous pull by exact digest.

## H. Create GitHub prerelease

- [ ] Select tag `v0.2.0-beta.1`.
- [ ] Mark the release as a prerelease.
- [ ] Use the prepared release notes.
- [ ] Add image digest and verification commands.
- [ ] Do not attach biological data or generated run reports.

## I. Post-publication documentation

Only after a successful anonymous image pull:

- [ ] Update README files to state image availability.
- [ ] Add the exact pull command and prefer the exact version tag.
- [ ] Retain local source-build instructions.
- [ ] Commit this as a separate post-release documentation change.

## J. Beta rollout

- [ ] Invite 5–10 users directly.
- [ ] Include Windows and Ubuntu/Linux users.
- [ ] Include novice and experienced RNA-seq users.
- [ ] Obtain at least three unaided report completions before broad promotion.
- [ ] Collect feedback through the public-beta issue form.
- [ ] Do not begin broad advertising immediately.
