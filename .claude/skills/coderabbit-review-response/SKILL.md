---
name: coderabbit-review-response
description: Reverb の PR に付いた CodeRabbit のレビュー指摘へ対応するワークフロー。指摘を取得→現行コードに照らし検証→担当別に修正委譲（backend=Codex / frontend=Claude）→テスト・lint 検証→commit/push→各指摘へ日本語で返信、まで行う。スキップする指摘は理由を残す。「coderabbitの指摘直して」「PRのレビュー対応して」「coderabbitコメント対応」「レビュー指摘に対応して」等でトリガー。引数で PR 番号（例: 3）やブランチを渡すとそれを対象にする。
---

# CodeRabbit レビュー対応ワークフロー

Reverb の PR に付いた **CodeRabbit（`coderabbitai`）のレビュー指摘**を、検証・修正・日本語返信まで完遂する。

**役割分担（AGENTS.md 準拠）**: 修正実装は担当に委譲する。**backend（Python / `[Backend]`・ラベル `codex`）= Codex に委譲**、**frontend（SwiftUI / `[Frontend]`・ラベル `Claude Code`）= Claude（Opus）自身が実装**。Claude は常にオーケストレーション（指摘の取得・検証・委譲・テスト/lint 検証・commit/push・返信）を担う。

**基本姿勢**: CodeRabbit の指摘を鵜呑みにしない。**各指摘を現行コードに照らして検証し、まだ妥当なものだけ最小修正**する。妥当でない／構造上問題にならないものは**スキップし、理由を残す**（コメントに明記）。推測で「直した」と言わず、テスト・lint を実際に実行して確認する。

引数（`$ARGUMENTS`）に PR 番号があればそれを、無ければ現在ブランチの PR を対象にする。

## 手順

### 1. 対象 PR と CodeRabbit 指摘を取得

```sh
git branch --show-current
# サマリ本文（レビュー author は coderabbitai）:
gh pr view <PR#> --json number,headRefName,reviews \
  --jq '.reviews[] | select(.author.login | startswith("coderabbitai")) | .body'
# インラインのレビューコメント本体を取得（返信に使う comment id を必ず含める）:
#   ※ インラインコメントの user.login は "coderabbitai[bot]"（サマリの "coderabbitai" と異なる）。
#     どちらも startswith("coderabbitai") で拾う。
gh api repos/{owner}/{repo}/pulls/<PR#>/comments --paginate \
  --jq '.[] | select(.user.login | startswith("coderabbitai")) | {id, path, line, body}'
```

- CodeRabbit のサマリには「Actionable comments」「Nitpick comments」「Prompt for AI Agents」が含まれる。各指摘の **id・ファイル・行・種別（actionable / nitpick）・要旨**を整理する（`id` は手順6の返信先になるので必ず控える）。
- 「🪄 Autofix」チェックボックスや CodeRabbit のプロンプトをそのまま実行しない。**Claude が指摘を読み、現行コードを確認してから**判断する。

### 2. 各指摘をトリアージ（現行コードに照らして検証）

指摘ごとに、該当ファイルを **Claude 自身が読み**、次を判定する:

- **妥当なバグ・契約不整合 → 修正する**（actionable は基本対応）。
- **構造上発生しない／既存方針と一貫していて問題ない → スキップ**。理由を一言で言語化する（例:「project_dir は単一ジョブ占有・ステージ逐次実行で並行書込は起きない」）。
- **スタイルのみの好み → 原則不採用**（AGENTS.md: バグ・実行時障害・契約不整合のみ修正）。ただし軽微で安全なら採用可。

担当を判定する（変更ファイルのパスで分類）:

- `backend/**`（Python）→ **Codex 委譲**。
- `Reverb/**` 等の Swift / フロント → **Claude 自身が実装**。
- 両方にまたがる場合は分割して扱う。

### 3. 修正を実施

**backend の場合（Codex 委譲）**: `Agent` ツールで `subagent_type: "codex:codex-rescue"` を使い、次を渡す:

- 対象 PR・ブランチ・作業ディレクトリ・venv とテスト/lint コマンド。
- **各指摘の原文要旨**（ファイル・行・種別）と、Claude のトリアージ結果（修正/スキップ＋理由）。
- 厳守事項: 「**各指摘を現行コードに照らして検証し、妥当なものだけ最小修正。スキップは理由を添える**」「外科的に・関係箇所のみ」「ローカル完結・新規依存を足さない・標準ライブラリのみ」「確定初期値・スキーマ契約を変えない」（AGENTS.md ルール）。
- バグ修正には**回帰テストを追加**させる。
- 戻り値として「変更ファイル一覧・各指摘への対応（修正/スキップ＋理由）・実行したテスト/lint コマンドと結果（pass 数）」を求める。

**frontend の場合（Claude 実装）**: Claude が該当 Swift を外科的に修正し、`swift build` 等で確認する。

> 同じ失敗を 2 回以上繰り返す／難バグなら `codex:codex-rescue` に第二診断を委譲する（グローバル規律）。

### 4. 成果を検証（推測で「直った」と言わない）

- 変更ファイルを **Claude 自身が読み**、指摘どおり直っているか・新たなルール違反（外部送信・ハードコード・スコープ外）が無いかを確認。
- テスト・lint を**自分の環境で実際に実行**してグリーンを確認する:
  ```sh
  cd backend && .venv/bin/python -m pytest -q
  .venv/bin/ruff check . && .venv/bin/black --check .
  ```
- Codex 実行環境のサンドボックス制約で落ちたテスト（例: `socket.bind` の `PermissionError` による `test_main`）は、**本環境で再現しないことを確認**し、環境依存である旨を区別して扱う（無条件に「無関係」と決めつけない）。

### 5. commit → push

- **この対応で変更したファイルのみ** stage する（他者変更を巻き込まない）。
- commit メッセージ例: `fix(USL-XX): CodeRabbit レビュー指摘に対応（要旨）`。本文に対応概要（修正/スキップ）とテスト結果。backend は「実装: Codex（委譲）／検証: Claude」を明記。末尾トレーラ必須:
  ```text
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  ```
- `git push`（既存 PR ブランチへ）。

### 6. 各 CodeRabbit 指摘へ日本語で返信（必須・各コメントのスレッドに返信する）

トップレベルの `gh pr comment` ではなく、**各 CodeRabbit インラインコメントのスレッドに直接返信する**（指摘と対応が1対1で紐づき、レビュアー/CodeRabbit が追いやすい）。手順1で控えた各コメントの `id` を返信先にする:

```sh
# <comment_id> は手順1で取得したインラインコメントの id。指摘ごとに1回ずつ実行する。
gh api repos/{owner}/{repo}/pulls/<PR#>/comments/<comment_id>/replies \
  -f body="$(cat <<'EOF'
@coderabbitai 対応しました（commit <sha>）。
[Fixed] …何をどう直したか。
[Test added] …追加した回帰テスト。
EOF
)"
```

- 返信は[[coderabbit-reply-japanese]] の方針に従い日本語。冒頭で `@coderabbitai` に宛て、対応 commit（sha）を示す。1スレッド = その指摘1件への対応のみを書く。
- 各指摘で次の形式を使う:
  - **[Fixed]** … 何をどう直したか。
  - **[Test added]** … 追加した回帰テスト。
  - **[Skipped]** … スキップ理由（構造上問題にならない等）。修正しない場合もスレッドに必ず返信して理由を残す。
- インラインに紐づかない**サマリ全体への総括**（検証結果＝`pytest` pass 数・`ruff`/`black` clean、Codex 委譲/Claude 検証の役割分担）だけは、補足として `gh pr comment <PR#>` でトップレベルに1件添えてよい。
- 返信先 `id` が取れない指摘（サマリ本文のみで対応するインラインが無い等）は、トップレベルコメントで該当箇所を引用して返す。

> スレッドの resolve はレビュアー判断に委ねる（Claude が勝手に resolve しない）。

## 完了時

変更点を日本語で簡潔に要約（結論から）。各指摘への対応（修正/スキップ＋理由）を表で示し、テスト・lint 結果を添える。Codex に委譲した範囲と Claude が検証・修正した範囲を分けて報告する。Linear のステータスは原則そのまま（PR Review）。
