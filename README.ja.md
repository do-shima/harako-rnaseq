# rnaseq_pipeline

言語:
- English: `README.md`
- 日本語: `README.ja.md`

Snakemake ベースの、Docker 対応 RNA-seq パイプラインです。単一のエントリポイント
`python -m app run ...` を提供し、ネットワーク不要で最後まで通る軽量 smoke test を含みます。

Harako-RNAseqは、ローカル・単一ユーザーでの学術・非商用RNA-seq解析を
対象とする、ソース公開型のパブリックベータ版アプリケーションです。
ホスト型の共有マルチユーザーサービスではありません。

## 概要

- ワークフロー実行エンジンは Snakemake のまま維持
- 主な出力は `out/` 配下に固定配置
- 静的 HTML レポートを `out/report/report.html` に出力
- Web UI は Streamlit ベース
- 参照データは pinned manifest に基づいて扱う

## 起源と謝辞

Harako-RNAseqは、Salmonを中心とするRNA-seqパイプライン
[ikra](https://github.com/yyoshiaki/ikra)から着想を得て、GUI、
クロスプラットフォームのDocker運用、再現可能なRun管理、
差次的発現解析・品質管理、自己完結型レポートなどを独自に追加した
プロジェクトです。Harako-RNAseqは、ikraの公式な後継または
承認済みプロジェクトではありません。

### AIを活用した開発支援

Harako-RNAseqの開発では、実装、リファクタリング、テスト作成、
ドキュメント作成、デバッグおよびコードレビューの支援に
OpenAI Codexを利用しました。

科学的解釈、アーキテクチャ上の判断、検証、ライセンス方針および
リリース判断は、すべてプロジェクトの管理者が行い、承認しています。
AIが生成した提案は、リポジトリへ取り込む前に内容を確認しています。

この謝辞は、OpenAIがHarako-RNAseqを承認、後援、認証または
科学的に検証したことを意味するものではありません。

## ライセンスと利用条件

Harako-RNAseqは、
[PolyForm Noncommercial License 1.0.0](LICENSE)に基づいて
ソースコードを公開しています。

本ライセンスの条件に従い、学術研究、教育、公共研究その他の
非商用目的で利用、改変、再配布できます。

商用利用、商用サービスへの組込み、再販売、または商用化を予定した
用途は本ライセンスでは許諾されず、別途書面による許可または
商用ライセンスが必要です。

Harako-RNAseqが利用または同梱する外部ツールおよびライブラリには、
それぞれのライセンスが適用されます。

商用利用に関する問い合わせは、リポジトリの
[GitHub Issues](https://github.com/do-shima/harako-rnaseq/issues)から
送信できます。

## クイックスタート

イメージをビルド:

```bash
just build
```

PowerShell:

```powershell
just build-if-needed-ps
```

smoke test:

```bash
just smoke
```

## Web UI の起動

Linux / macOS:

```bash
just app
```

Windows PowerShell:

```powershell
just app-ps
```

デフォルトでは `http://127.0.0.1:8501` を利用します。ブラウザで同アドレスを開いてください。

補足:
- `INPUT` / `OUT` を未指定で `just app` / `just app-ps` を実行した場合、repo 直下の `input` / `output` を自動利用します。
- 既に 8501 番ポートが使用中の場合、既存コンテナを停止してから再実行してください。
- UI のサイドバー `Language` で英語 / 日本語を切り替えられます。

## 基本的な実行フロー

1. UI で設定を保存
2. Validate
3. Dry-run
4. Run

推奨の実データ実行例:

Linux / macOS:

```bash
export INPUT=/path/to/data
export OUT=/path/to/out
just build-if-needed
just app
just validate-out
ENGINE=real THREADS=8 just run-out
just check
```

PowerShell:

```powershell
$env:INPUT="D:\path\to\data"
$env:OUT="D:\path\to\out"
just build-if-needed-ps
just app-ps
just validate-out
$env:ENGINE="real"
$env:THREADS="8"
just run-out-ps
just check
```

## UI / 実行まわりの現在の仕様

- プロジェクト名は UI で編集可能で、出力ディレクトリ名は `{project_slug}_{run_id}` 形式になります。
- UI 下書き状態はブラウザセッションごとに `/output/ui_sessions/<ui_session_id>/...` に分離保存されます。
- Run 開始時に、実行用の凍結済み設定を `/output/data_out/<run_id>/run/config_resolved.yaml` に保存します。
- Resume / Recover / Unlock は、必ずその run-local 設定を参照します。
- `Auto-fill condition from sample` は replicate suffix を正規化します。
  - 例: `STZ_1` / `STZ_2` -> `STZ`
  - 例: `Con_Hard_1_1.fastq.gz` から導かれた sample / condition は最終的に `Con_Hard` に正規化
  - `SRR14340927` のような accession は変更しません
- Enrichment は、少なくとも 2 条件かつ各条件 2 サンプル以上ある場合のみ有効化されます。

## UI 保存レイアウト

- `/output/ui_sessions/<ui_session_id>/config.yaml`
- `/output/ui_sessions/<ui_session_id>/metadata/samples.tsv`
- `/output/ui_sessions/<ui_session_id>/ui_state.json`
- `/output/ui_sessions/<ui_session_id>/ui_effective_config.json`
- `/output/ui_sessions/<ui_session_id>/logs/ui_events.log`

## Run 保存レイアウト

- `/output/data_out/<run_id>/run/config_resolved.yaml`
- `/output/data_out/<run_id>/run/manifest.json`
- `/output/data_out/<run_id>/run/metadata.json`
- `/output/data_out/<run_id>/run/metadata/samples.tsv`

## 参照データ

基本方針:
- human / mouse は GENCODE 系 preset
- rat は Ensembl 系 preset
- URL はコードに直書きせず、`workflow/ref_manifest.yaml` を source of truth とする
- ユーザー指定の FASTA + GTF もサポート

参照ファイルの選択や取得は Web UI から行えます。より詳細な preset / manifest の説明は英語版 `README.md` を参照してください。

## SRA / ENA 取り込み

推奨フロー:

```bash
RUN_TABLE=path/to/SraRunTable.txt just srr
```

または:

```bash
SRR_LIST=path/to/srr_list.txt just srr
```

または:

```bash
SRR="SRR123 ERR456 DRR789" just srr
```

PowerShell:

```powershell
$env:RUN_TABLE="path\\to\\SraRunTable.txt"
just srr-ps
```

取得後、表示された `run_id` を使って UI を開きます。

```powershell
$env:INPUT="<repo>\\data_in\\srr\\<run_id>"
$env:OUT="<repo>\\data_out\\<run_id>"
just app-ps
```

## よく使う just ターゲット

- `just build`
- `just build-if-needed`
- `just smoke`
- `just verify-smoke`
- `just app`
- `just app-ps`
- `just validate-out`
- `just run-out`
- `just run-out-ps`
- `just logs`
- `just check`
- `just doctor-ui`

## doctor-ui

公開前やローカル診断向けに、次を非破壊で確認できます。

- イメージ名
- repo パス
- 既定の input / output パス
- ロゴファイルの有無
- コンテナ内で `streamlit` を import できるか

実行:

```bash
just doctor-ui
```

## トラブルシュート

- UI が起動しない:
  - まず `just app` / `just app-ps` を使用
  - `8501` が使用中なら既存のコンテナまたはプロセスを停止
- Validate が失敗する:
  - `sample` / `condition` / `fastq1` の未入力を確認
  - 参照ファイルが選択済みか確認
- Run が失敗する:
  - `just logs` を確認
  - report だけを再生成したい場合は `just report-out`
  - 出力確認は `just verify-real`
- Windows で PowerShell を使う:
  - `*-ps` ターゲットを優先
  - `just init INPUT=...` のように引数で渡すより、`$env:INPUT=...` を設定してから実行

## 出力レイアウト

主な成果物:

- `out/fastp/{sample}.fastq`
- `out/fastp/{sample}_R1.fastq`
- `out/fastp/{sample}_R2.fastq`
- `out/salmon/{sample}/quant.sf`
- `out/tximport/txi.tsv`
- `out/deseq2/results.tsv`
- `out/report/report.html`
- `out/results/enrichment/contrast=<A>_vs_<B>/status.json`

`out/report/report.html` には Harako-RNAseq のブランド要素とロゴが埋め込まれ、単独 HTML として共有しやすい形になります。

## 設定

代表的な config キー:

- `engine`: `stub` または `real`
- `species`: `mouse | human | rat`
- `samples`
- `sample_table`
- `ref`
- `ref_preset`
- `ref_manifest`
- `threads`
- `contrast_mode`
- `contrast_ref`
- `contrast_pairs`
- `contrasts`（legacy）
- `enrichment`

canonical な設定リファレンスは `config/schema.md` を参照してください。

## 補足

- smoke test を小さく保つため、一部ツールは stub 実装を使います。
- 実運用では fastp, Salmon, tximport, DESeq2, static HTML report を利用します。
- より詳細なコマンド一覧、Snakemake 直接実行例、PowerShell 向けワンライナーは英語版 `README.md` を参照してください。
