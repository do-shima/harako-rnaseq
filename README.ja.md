# Harako-RNAseq

<p align="center">
  <img src="icon/Harako-logo.png" alt="Harako-RNAseqロゴ" width="220">
</p>

[English README](README.md) | [ドキュメント一覧](docs/index.md)

プロジェクト公式サイト: <https://do-shima.github.io/harako-rnaseq/>

Harako-RNAseqは、fastp、Salmon、tximport、DESeq2を用いた再現可能な
ローカルbulk RNA-seq解析と、自己完結型HTMLレポート作成を行う、
DockerベースのGUIワークフローです。

**Public beta | source-available（ソース公開型）| 学術・非商用利用向け**

小規模から中規模のbulk RNA-seq解析をローカルワークステーションで
実行する研究者・解析担当者を対象としています。ローカル・単一ユーザー
向けアプリケーションであり、ホスト型の共有マルチユーザーサービスでは
ありません。Windows + Docker DesktopおよびUbuntu/Linux + Dockerで
検証済みです。現在のイメージは`linux/amd64`で、macOSは本リリースでは
未検証です。

実験計画、生物学的独立性、参照データの選択、プライバシー保護、
科学的解釈は利用者の責任です。Harakoは専門家によるレビューの代替では
ありません。

## 概要

Streamlit GUIでサンプル表を整え、検証済みプリセットまたはカスタム参照を
選び、再現可能なRun設定を固定して、再開可能なSnakemakeワークフローを
実行します。シングルエンド／ペアエンドFASTQ、対応するSRA/ENA取得フロー、
human、mouse、ratを扱えます。

選択したSalmonインデックスを用いて転写産物レベルで定量した後、tximportで
遺伝子レベルのカウント値と、発現量の指標として遺伝子レベルTPMを出力します。
DESeq2はカウント値を使用し、TPMは使用しません。入力形式に問題がなくても、
各条件の最小サンプル数要件を満たさない場合はQC-onlyモードで処理を継続し、
p値および調整p値を算出・出力しません。

## 主な機能

- 選択サブディレクトリを対象としたFASTQ探索。
- 編集可能なサンプル表とペアエンドの自動ペアリング。
- 条件名の一貫した正規化と手動確認。
- SHA-256で固定・検証されたEnsembl参照プリセット（human、mouse、rat）。
- カスタムtranscript FASTA、genome FASTA、GTF。
- fastp前処理とSalmon転写産物定量。
- tximportによる遺伝子レベルのカウント値と、発現量の指標としての遺伝子レベルTPM。
- 最小サンプル数要件を満たす場合のDESeq2による遺伝子発現変動解析。
- 入力形式に問題がなくても最小サンプル数要件を満たさない場合のQC-onlyモード。
- 遺伝子発現変動解析の結果が利用可能な場合の任意エンリッチメント解析。
- セッション分離された下書きとRunごとの不変設定。
- Run ID、参照由来情報、ログ、ツールバージョンの記録。
- 英語・日本語に対応したStreamlit GUI。
- 外部Web資源を必要としない自己完結型HTMLレポート。

## クイックスタート

通常利用と再現可能な研究では、バージョンを固定した公開イメージを推奨します。
更新される`beta`イメージは、最新のベータ版を意図的に追跡する場合に利用できます。

### Ubuntu / Linux：バージョン固定イメージ

```bash
mkdir -p input output
docker pull ghcr.io/do-shima/harako-rnaseq:v0.3.0-beta.1
docker run --rm -p 127.0.0.1:8501:8501 \
  -e PYTHONPATH=/app -e "HOST_INPUT=$(pwd)/input" -e "HOST_OUT=$(pwd)/output" \
  --mount "type=bind,src=$(pwd)/input,dst=/input,readonly" \
  --mount "type=bind,src=$(pwd)/output,dst=/output" \
  ghcr.io/do-shima/harako-rnaseq:v0.3.0-beta.1 \
  streamlit run app/ui/app_ui.py --server.address 0.0.0.0 \
  --server.port 8501 --server.headless true --browser.gatherUsageStats false
```

### Windows PowerShell：バージョン固定イメージ

```powershell
$InputDir = "D:\rna\input"
$OutputDir = "D:\rna\output"
New-Item -ItemType Directory -Force $InputDir, $OutputDir | Out-Null
docker pull ghcr.io/do-shima/harako-rnaseq:v0.3.0-beta.1
docker run --rm -p 127.0.0.1:8501:8501 `
  -e PYTHONPATH=/app -e "HOST_INPUT=$InputDir" -e "HOST_OUT=$OutputDir" `
  --mount "type=bind,src=$InputDir,dst=/input,readonly" `
  --mount "type=bind,src=$OutputDir,dst=/output" `
  ghcr.io/do-shima/harako-rnaseq:v0.3.0-beta.1 `
  streamlit run app/ui/app_ui.py --server.address 0.0.0.0 `
  --server.port 8501 --server.headless true --browser.gatherUsageStats false
```

DockerまたはDocker Desktopを起動してから、ブラウザで
`http://127.0.0.1:8501`を開きます。入力は`/input`へ読み取り専用、出力は
`/output`へ読み書き可能としてマウントします。更新されるベータチャンネルを使う
場合は、固定タグを`ghcr.io/do-shima/harako-rnaseq:beta`へ置き換えます。

開発またはソース変更を行う場合はリポジトリをクローンし、Linuxでは
`just app`、PowerShellでは`just app-ps`を使用します。これらはソースを
チェックアウトしてローカルでビルドする経路です。

明示的なマウント、必要リソース、ポート転送、プラットフォーム状況は
[インストール](docs/installation.md)を参照してください。

## 基本的な流れ

1. **プロジェクト:** プロジェクト名と探索対象サブディレクトリを設定します。
2. **サンプル:** FASTQ、ペア、サンプルID、条件を確認します。
3. **参照ファイル:** Ensemblプリセットまたはカスタム参照を選びます。
4. **詳細設定:** 適用可能なコントラストとエンリッチメントを設定します。
5. **まとめ:** 保存、検証、ドライラン、実行の順に進めます。

ブラウザセッションごとに下書きは分離されます。Run開始時に、正規化済み
サンプル表、実行設定、解析計画、参照データの来歴情報をRun内へ固定します。
Resume / Recoverは、後から変更したUI状態ではなく、この固定設定を使います。

詳細は[GUIとRunの使い方](docs/usage.md)、アクセッション取得は
[SRA/ENA入力](docs/sra-ena.md)を参照してください。

## 制御されたエージェント対応インターフェース

**v0.3.0-beta.1**では、Codexなどのローカル自動化ツール向けに、制御された
機械可読CLIを提供します。生物学的条件は推測せず、サンプルへの条件割り当てを
明示し、承認ハッシュの完全一致を確認してから実行する必要があります。
対応している解析処理の検証と実行はHarakoが担います。自動化ツールは確認手順を
調整できますが、解析の適格性を決定したり、Harakoの実行経路を置き換えたりは
しません。

Harakoはエージェントなしでも使用でき、OpenAI client、model call、API key、
cloud AI依存関係を含みません。詳細は
[エージェント用ワークフローと安全契約](docs/agent-workflow.md)および
[Codex支援解析の実例](docs/agent-assisted-analysis.md)を参照してください。

## 解析モード

### 遺伝子発現変動解析

DESeq2による遺伝子発現変動解析（differential expression analysis）には、
次の最小サンプル数要件があります。

- 異なる条件が2種類以上。
- すべての条件に有効なサンプルが2つ以上。

最小サンプル数要件を満たすRunでは既存のコントラスト設定を適用します。
エンリッチメントは、遺伝子発現変動解析の結果が利用可能で、固有の
前提条件も満たす場合に限り実行できます。

### QC-only解析

1条件のみ、またはいずれかの条件が2サンプル未満で、入力形式には問題がない
場合はQC-onlyモードになります。前処理、定量、遺伝子レベルのカウント値、発現量の
指標としての遺伝子レベルTPM、技術的に可能なDESeq2正規化、適用可能な
PCA・サンプル間距離QC、レポートは引き続き作成します。

QC-onlyモードでは統計的推論に用いるコントラストを無効化し、p値および調整p値を
算出・出力しません。遺伝子発現変動解析用プロットとエンリッチメント解析も
実行しません。`deseq2/results.tsv`はヘッダーのみで、`deseq2/status.json`に
モードと実際の成果物の有無を記録します。

各条件2サンプルはソフトウェアが適用する最小サンプル数要件にすぎず、統計的検出力の計算、
生物学的独立性、実験計画の妥当性を保証しません。

## 主な出力

各Runには、次の安定した成果物が含まれます。

- `fastp/`: 前処理済みリードとfastp JSON/HTML QC。
- `salmon/<sample>/quant.sf`: 転写産物定量。
- `tximport/txi.tsv`: 遺伝子レベルのカウント行列。
- `tximport/gene_tpm.tsv`: 利用可能な場合の、発現量の指標としての遺伝子レベルTPM。
- `deseq2/status.json`: 解析モードと成果物の有無。
- `deseq2/results.tsv`: DE結果、QC-onlyではヘッダーのみ。
- `deseq2/normalized_counts.tsv`: 利用可能な場合のDESeq2正規化カウント値。
- `report/report.html`: 自己完結型解析レポート。
- `run/`: 固定設定、サンプル情報、manifest、ログ、バージョン。

正確なパスとモード別の扱いは
[出力リファレンス](docs/output-reference.md)を参照してください。

## ドキュメント

[ドキュメント一覧](docs/index.md)から目的別に参照できます。

- [インストールと必要リソース](docs/installation.md)
- [GUI、Resume、Recover](docs/usage.md)
- [SRA/ENA取得](docs/sra-ena.md)
- [科学的方法](docs/scientific-methods.md)
- [参照プリセット](docs/reference-presets.md)
- [出力](docs/output-reference.md)
- [トラブルシュート](docs/troubleshooting.md)
- [高度な利用](docs/advanced-usage.md)
- [エージェント対応ワークフロー](docs/agent-workflow.md)
- [アーキテクチャ](docs/architecture.md)
- [サポートマトリクス](docs/support-matrix.md)
- [制限事項](docs/limitations.md)

## システム要件

### 公開イメージを利用する場合

- Linuxコンテナを実行できるDocker。
- ローカルポート8501へ接続できるWebブラウザ。
- 現行イメージを実行できるamd64環境。
- FASTQ、非圧縮fastp中間ファイル、参照キャッシュ、Salmonインデックス、
  定量結果、レポートに必要なメモリとディスク容量。

### ソースからビルドする場合

- Git、Linuxコンテナを実行できるDocker、`just`。
- 公開イメージと同じブラウザ、アーキテクチャ、メモリ、ディスク要件。

Dockerを使わないnative実行と、ホスト型マルチユーザー運用は非対応です。
IntelベースのmacOSは未検証で、現行イメージはApple Silicon/arm64ネイティブでは
ありません。[サポートマトリクス](docs/support-matrix.md)を参照してください。

## 科学的な制限

- 現在の標準モデルは条件ベースで、バッチ、ペアリング、反復測定、
  その他の共変量を自動では扱いません。
- 最小サンプル数要件を満たしても、十分な統計的検出力、生物学的独立性、
  実験計画の妥当性は保証されません。
- Salmonは転写産物を定量し、tximportが遺伝子単位に集約します。
- DESeq2は遺伝子レベルのカウント値を使用し、TPMは入力にしません。
- 組込み参照のSHA-256チェックサムは同一ファイルを示しますが、研究への適合性は保証しません。
- カスタム参照の整合性は利用者が確認する必要があります。

解釈前に[科学的方法](docs/scientific-methods.md)と
[制限事項](docs/limitations.md)を確認してください。

## ライセンスと利用条件

Harako-RNAseqは、
[PolyForm Noncommercial License 1.0.0](LICENSE)に基づいて
ソースコードを公開しています。

本ライセンスの条件に従い、学術研究、教育、公共研究その他の
非商用目的で利用、改変、再配布できます。

商用利用、商用サービスへの組込み、再販売、または商用化を予定した
用途は本ライセンスでは許諾されず、別途書面による許可または
商用ライセンスが必要です。[商用ライセンス](COMMERCIAL_LICENSE.md)を
参照してください。

Harako-RNAseqが利用または同梱する外部ツールおよびライブラリには、
それぞれのライセンスが適用されます。
[Third-Party Notices](THIRD_PARTY_NOTICES.md)も確認してください。

## 起源と謝辞

### 名称と設計思想

Harako-RNAseqの名称は、「はらこ（鮭の卵）」と、着想源となった
Salmon中心のRNA-seqパイプラインである
[ikra](https://github.com/yyoshiaki/ikra)に由来します。HARAKOは、次の
backronymとしても位置づけています。

**HARAKO: Human-Auditable, Reproducible Analysis Kit and Orchestrator**

これは、人による確認・監査が可能な、再現性重視の解析キット兼
オーケストレーターという現在の設計思想を表します。

- **Human-Auditable:** サンプルと条件の割り当て、解析計画、実行前の
  正確な承認、来歴情報、成果物を人が確認できます。
- **Reproducible:** Docker環境、固定されたRun設定、ツールバージョン、
  参照配列とアノテーションの由来情報、SHA-256で固定された参照を記録します。
- **Analysis Kit:** GUI、CLI、Snakemakeワークフロー、レポート、補助ツールを
  bulk RNA-seq解析用の一体的なキットとして提供します。
- **Orchestrator:** 検証、ドライラン、制御されたSnakemake実行、状態と
  成果物の確認、任意のエージェント連携を管理しますが、科学的な判断主体は
  利用者のままです。

「Human-Auditable」は、関連する入力、判断、解析計画、来歴情報、出力を人が
確認・監査できることを意味し、科学的妥当性を自動的に認定するものでは
ありません。このbackronymは既存の名称を説明するために後から採用した
解釈であり、英語の展開語が日本語名より先に決まっていたわけではありません。

Harako-RNAseqは、ikraから得た着想をもとに、GUI、クロスプラットフォームの
Docker運用、再現可能なRun管理、遺伝子発現変動解析・品質管理、自己完結型
レポートなどを独立して実装したプロジェクトです。Harako-RNAseqは、ikraの
公式な後継または承認済みプロジェクトではありません。

### AIを活用した開発支援

Harako-RNAseqの開発では、実装、リファクタリング、テスト作成、
ドキュメント作成、デバッグおよびコードレビューの支援に
OpenAI Codexを利用しました。

科学的解釈、アーキテクチャ上の判断、検証、ライセンス方針および
リリース判断は、すべてプロジェクトの管理者が行い、承認しています。
AIが生成した提案は、リポジトリへ取り込む前に内容を確認しています。

この謝辞は、OpenAIがHarako-RNAseqを承認、後援、認証または
科学的に検証したことを意味するものではありません。

開発由来の監査記録は
[docs/provenance.md](docs/provenance.md)にあります。

## 引用

Harako-RNAseqを利用した場合は、[CITATION.cff](CITATION.cff)に基づいて
ソフトウェアリリースを引用してください。現在のpublic beta versionは
`0.3.0-beta.1`です。

## サポートとIssue

公開Issueを作成する前に[SUPPORT.md](SUPPORT.md)を確認してください。
Harakoのversionまたはcommit、OS、Docker version、起動command、
失敗stage、期待結果と実際の結果、sanitized logまたはsupport bundleの
情報を添えてください。

FASTQ、患者情報、認証情報、機密パス、識別可能なサンプル情報を公開Issueへ
投稿しないでください。脆弱性は通常サポートではなく、
[SECURITY.md](SECURITY.md)に記載した非公開経路で報告してください。
