# Terminology guide

This maintainer-facing guide keeps current public documentation and UI copy
consistent. It is a writing guide, not a scientific ontology, schema, or
machine-readable contract. Literal CLI commands, options, JSON/YAML keys,
filenames, paths, schema values, and error codes remain unchanged.

## English

Prefer:

- differential expression analysis;
- differential expression results;
- evidence of differential expression;
- QC-only mode;
- minimum sample-count requirements;
- minimum threshold enforced by the software;
- gene-level counts and count matrix;
- gene-level TPM as an abundance measure;
- analysis plan and approval hash;
- reference provenance;
- dry run;
- SHA-256 checksum in normal prose; and
- run in lowercase normal prose.

Avoid specification-like or rhetorical wording in ordinary-user prose,
including “differential-expression analysis,” “fabricated statistics,”
“minimum replicate gate,” “software minimum gate,” “scientific execution
authority,” “ordinary-user path,” and unexplained “typed artifacts.” Prefer
“saved and fixed for the run” to “frozen” unless the frozen-run engineering
contract itself is being discussed.

For the agent boundary, prefer:

> Harako validates and executes the supported scientific workflow. Automation
> tools may coordinate review steps, but they do not determine analysis
> eligibility or replace Harako’s execution path.

## 日本語

次の表現を基本とします。

- 遺伝子発現変動解析。必要な場合のみ初出を「遺伝子発現変動解析
  （differential expression analysis）」とし、以後は「発現変動解析」とする。
- QC-onlyモード。
- 各条件の最小サンプル数要件、または最小サンプル数要件。
- カウント値、カウント行列。
- 条件、サンプル。
- コントラスト（条件間比較）。
- 解析計画、承認ハッシュ。
- 出力ファイル、または文脈に応じて成果物。
- 参照データの来歴情報。
- ドライラン。
- SHA-256チェックサム。
- 解析実行、または実行。
- 後付けの頭字語（backronym）。

`Run ID`は技術的な識別子を示す必要がある場合に「実行ID（Run ID）」と
表記できます。`run/`、`analysis_plan`、`reason_code`、`ref_preset`、
`deseq2/status.json`などの技術識別子は翻訳しません。ファイル名に含まれる
`counts`もそのまま保持し、通常の説明文では「カウント値」を使います。

法的な分類である `source-available` は、ライセンス上の意味を変える訳語へ
置き換えません。必要な場合は短い日本語説明を添えます。

## Scope

Maintainer documentation may retain terms such as gate, artifact, freeze, and
Run when they name defined engineering contracts. Historical release notes,
security evidence, code examples, and machine-readable values are not rewritten
solely to follow this guide.
