---
name: harako-rnaseq-analysis
description: Safely coordinate local Harako-RNAseq planning, approval-controlled execution, run inspection, and isolated post-analysis by following the repository's canonical Agent Skill.
---

# Harako RNA-seq analysis

Read and follow the canonical repository contract at
`../../../.agents/skills/harako-rnaseq-analysis/SKILL.md`.

These rules are non-negotiable:

1. Obtain explicit sample-to-condition assignments; never infer conditions.
2. Obtain an explicit `full_length` or `three_prime_tag` library protocol;
   never infer it.
3. Treat dry run as validation only, not approval.
4. Execute only after the user confirms the exact current approval hash.
5. Treat the frozen Harako run and all core outputs as read-only; put additional
   work only in a workspace created by `post-analysis-init`.
