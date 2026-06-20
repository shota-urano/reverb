---
name: frontend-linear-task
description: Reverb のフロントエンド（SwiftUI/macOS・担当 Opus4.8）担当として、Linear の Todo issue を1件選び「develop最新化→ブランチ作成→In Progress→実装→subagentレビュー→commit/push/PR→PR Review」まで一気通貫で行うワークフロー。「フロントタスク実装して」「USL実装して」「Linearのフロント実装進めて」「次のフロントissueやって」等でトリガー。引数で issue id（例: USL-79）を渡すとその issue を対象にする。
---

# フロントエンド Linear タスク実装ワークフロー

Reverb の **フロントエンド（SwiftUI + AVKit / macOS）** 担当として、Linear の Todo issue を1件、実装から PR 作成・ステータス更新まで完遂する。対象は **Frontend issue のみ**（ラベル `Claude Code` / タイトル接頭辞 `[Frontend]` / 担当 Opus4.8）。Backend（ラベル `codex`）は対象外。

引数（`$ARGUMENTS`）に issue id（例: `USL-79`）があればそれを対象にする。無ければ Frontend の Todo から**優先度最上位（Urgent→High→…）かつ依存の少ない土台寄り**を1件選ぶ。

前提・規約は必ず `AGENTS.md` と `docs/specs` / `docs/design` を一次情報源とする。

## 手順

### 1. develop を最新化してブランチを作成（最初に必ず行う）

リモート develop をローカル develop に取り込んでから、そこを base にブランチを切る。

```sh
# 未コミット変更があれば退避を促す（特に自分が作っていない AGENTS.md 等は触らない）
git status --short
git checkout develop
git pull origin develop
```

ブランチ名は git 運用ルール（AGENTS.md）に従う。
- 機能追加: `feature/<issue-id>`（例 `feature/USL-79`）
- バグ対応: `bug/<issue-id>`

```sh
git checkout -b feature/USL-79   # develop から切り出す
```

> develop に未コミットの変更（例: 既存の `AGENTS.md` 修正）が残っている場合、それは**自分の作業対象外**。commit に含めず、そのまま working tree に残す。

### 2. 対象 issue を確定し、内容を把握

- Linear MCP（`list_issues` project=reverb state=Todo / `get_issue`）で Frontend issue を取得。
- issue 記載の仕様（`docs/specs/08-playback-ui.md`、`docs/design/screens.md`・`design-system.md` 等）を読み、受け入れ基準・確定初期値・API 契約を確認する。

### 3. Linear ステータスを In Progress に

`save_issue` で `state: "In Progress"`。

### 4. 実装

設計・規約（AGENTS.md）を厳守する。**外科的変更**（隣接コードに触れない）。

- アーキテクチャ: MVVM + Repository（薄め）。`View → ViewModel(@Observable) → Repository(protocol) → BackendClient`。**View に処理ロジックを置かない**。
- 配置: `Sources/ReverbKit/{App,Features,Core/{API,Repository,Models},Components}`、エントリは `Sources/Reverb`。テスト可能なロジックは `ReverbKit` に置き、Swift Testing で `Tests/ReverbKitTests` にテストを書く。
- **絶対ルール**（破ったら作り直し）:
  - ローカル完結を破らない（クラウド送信コード禁止）。
  - baseURL/ポート・翻訳モデル名・話者 ID を**ハードコードしない**（ハンドシェイク／`/models`／`/speakers` から取得、設定値化）。
  - 確定初期値を勝手に変えない（音量 日本語100%/元音声8%、字幕 全角20字前後/最大2行/最低1.5秒、speedScale 0.8〜1.3）。
  - macOS / Apple Silicon 固定。依存を勝手に増やさない。
  - スコープ外（複数話者打ち分け・リップシンク・ファイル書き出し・リアルタイム処理・動画DL）を実装しない。
  - アクセシビリティ（キーボード操作・VoiceOver・SF Symbols のみ）を満たす。
- DTO は API 契約（`docs/specs/01-architecture.md §4`）と 1:1。spec の実 JSON でデコードするゴールデンテストを添える。

### 5. ビルド & テスト（推測で「動いた」と言わない）

```sh
make build
make test     # Command Line Tools 環境では framework パスを Makefile が自動補完
```

両方グリーンを確認してから次へ。落ちたら出力ごと直す。

### 6. レビュー用 subagent によるレビュー → バグ/障害のみ修正

`general-purpose`（または `Explore`）の subagent に、対象差分を Swift6 並行性・ライフサイクル・SSE/プロセス・API 契約整合の観点でレビューさせる。

- 報告のうち **バグ・実行時障害・契約不整合のみ**修正する。スタイル/好みの指摘は採用しない。
- 修正後は再度 `make test` でグリーン確認。

### 7. commit → push → PR 作成（PR にコメント必須）

- **自分が変更したファイルのみ** stage する（`git add` で個別指定。`AGENTS.md` 等の他者変更を巻き込まない）。
- commit メッセージ末尾に必須トレーラ:
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  ```
- push 後、`gh pr create --base develop` で PR 作成。PR body 末尾に:
  ```
  🤖 Generated with [Claude Code](https://claude.com/claude-code)
  ```
- PR body には: 概要 / Linear リンク / 実装内容 / 制約遵守 / レビュー対応 / テスト結果 を書く。
- **PR にコメントを付ける**（`gh pr comment`）: レビュアー向けの重点箇所・バックエンド連携で要確認な点・スコープ外で含めていない点。

### 8. Linear ステータスを PR Review に

`save_issue` で `state: "PR Review"`。`links` に作成した PR の URL を添付する。

## 完了時

変更点を日本語で簡潔に要約して報告する（結論から先に）。テストがあれば結果を示す。スキップした手順は「スキップした」と明示する。
