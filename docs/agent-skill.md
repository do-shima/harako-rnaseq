# Harako Agent Skill

The repository provides one canonical safety and workflow contract for local
coding agents. The Skill coordinates Harako's existing machine-readable CLI;
it does not replace Harako's validation or scientific execution authority.

## Architecture

```text
User
→ Codex or Claude Code
→ Harako Agent Skill
→ python -m app agent
→ human approval
→ Harako/Snakemake execution
```

There is no MCP server, embedded model, OpenAI SDK, Anthropic SDK, or provider
API call. Harako does not upload data to a cloud model. The agent coordinates
the existing local CLI, and execution still requires the exact current
approval hash.

The canonical contract is
[`../.agents/skills/harako-rnaseq-analysis/SKILL.md`](../.agents/skills/harako-rnaseq-analysis/SKILL.md).
Codex discovers it from `.agents/skills/`. Claude Code discovers the concise
project wrapper from `.claude/skills/`; that wrapper points back to the same
canonical contract rather than duplicating it.

The discovery layout follows the official
[Codex Skills documentation](https://developers.openai.com/codex/skills) and
[Claude Code Skills documentation](https://code.claude.com/docs/en/skills),
reviewed on 2026-08-15.

## Codex hands-on

First request:

```text
Use $harako-rnaseq-analysis.

Inspect:
D:/harako-demo/input

Use:
- explicit conditions from D:/harako-demo/conditions.tsv
- mouse
- mouse_ensembl_grcm39
- full_length
- pairwise contrasts
- 4 threads
- output D:/harako-demo/output

Run inspect-input, propose-samples, plan, validate-plan, and dry-run.
Show the complete plan and exact approval hash, then stop.
Do not execute yet.
```

After reviewing the unchanged plan, use a separate turn:

```text
I approve this exact Harako approval hash:

<EXACT_HASH>

Revalidate the unchanged plan, execute it, then show status, artifacts, and
the sanitized context.
```

## Claude Code hands-on

Start Claude Code from the repository root so it discovers the project Skill,
then use an equivalent natural-language request:

```text
Use the Harako RNA-seq Analysis project Skill. Inspect D:/harako-demo/input,
use the explicit conditions in D:/harako-demo/conditions.tsv, select mouse,
mouse_ensembl_grcm39, full_length, pairwise contrasts, 4 threads, and output
D:/harako-demo/output. Run inspection, sample proposal, planning, validation,
and dry run. Show the complete plan and exact approval hash, then stop without
executing.
```

After review, provide the exact hash in a second turn and ask Claude Code to
revalidate, execute, and inspect status, artifacts, and context.

## Public-data hands-on

Complete supported SRA/ENA acquisition first by following
[`sra-ena.md`](sra-ena.md). Keep its accession and download confirmation as a
separate user decision. After FASTQ files are local, ask the Agent Skill to
inspect that directory. Sample conditions and `full_length` versus
`three_prime_tag` must still be supplied explicitly; neither is inferred from
accessions or downloaded metadata.

## Expected stop point

The first session stops after `dry-run`, presents the complete current plan and
exact approval hash, and does not call `execute`. Dry run is not approval.
