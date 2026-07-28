# Public-beta launch runbook

This runbook contains manual actions. Do not run publication steps until every
blocking audit is resolved.

## A. Before visibility change

- [ ] Approve author/committer identity inventory.
- [x] Institutional commit identity disclosure approved without reproducing
  the address in tracked release records.
- [ ] Approve disclosure of the reviewed historical local-path blob.
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
| `main` | Retain |
| `codex/public-beta-release-audit` | Merge first after review |
| `origin/codex/public-beta-docs` | Delete before visibility change; already merged |
| `origin/codex/rna-seq-processing-pipeline-dev` | Manual review, then delete if obsolete |
| local `codex-gpcblb`, `codex_test`, `fix/tximport-files-type`, `release/0.1` | Local-only review; archive or delete if obsolete |
| `v0.1.0` | Retain only after confirming it is an intentional historical release |

After review, examples of manual cleanup commands are:

```bash
git push origin --delete codex/public-beta-docs
git push origin --delete codex/rna-seq-processing-pipeline-dev
git branch -d codex/public-beta-docs
git branch -d codex-gpcblb codex_test fix/tximport-files-type release/0.1
```

Do not use `-D` or delete a tag without separately confirming reachability and
backup.

## B. Make repository public

- [ ] Open GitHub **Settings → General → Danger Zone**.
- [ ] Confirm that reachable history and commit metadata will become public.
- [ ] Change visibility manually.
- [ ] Immediately inspect README, LICENSE, Security, Issues, Actions, branches,
  and tags as an unauthenticated visitor.
- [ ] Confirm no Actions secret is exposed.
- [ ] Confirm secret scanning and dependency graph settings as applicable.

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
