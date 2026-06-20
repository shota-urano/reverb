---
name: backend-linear-task
description: Reverb のバックエンド（Python サイドカー / FastAPI）担当の Linear Todo issue を1件選び、「develop最新化→ブランチ作成→In Progress→Codexに実装委譲→検証→レビュー→commit/push/PR→PR Review」まで進めるワークフロー。実装そのものは Codex に依頼し、Claude はオーケストレーション（仕様整理・委譲・検証・PR）を担う。「バックエンドタスク実装して」「backend issueやって」「Codexにbackend実装させて」「次のbackendやって」等でトリガー。引数で issue id（例: USL-69）を渡すとその issue を対象にする。
---

# バックエンド Linear タスク実装ワークフロー（Codex 委譲型）

Reverb の **バックエンド（Python サイドカー / FastAPI + Uvicorn + Pydantic）** の Linear Todo issue を1件、PR 作成・ステータス更新まで完遂する。

**役割分担**: 実装（プログラム作成）は **Codex に委譲**する。Claude は「仕様の読み込み・整理 → Codex への委譲 → 成果の検証 → レビュー → commit/push/PR → Linear 更新」というオーケストレーションを担う。

対象は **Backend issue のみ**（ラベル `codex` / タイトル接頭辞 `[Backend]`）。Frontend（ラベル `Claude Code`）は対象外。引数（`$ARGUMENTS`）に issue id があればそれを、無ければ Backend の Todo から**優先度最上位かつ依存の少ない土台寄り**（例: サイドカー基盤 → データモデル → 各ステージ）を1件選ぶ。

前提・規約は `AGENTS.md` と `docs/specs`（特に `01-architecture.md`〜`09-data-model.md`）を一次情報源とする。

## 手順

### 1. develop を最新化してブランチを作成（最初に必ず行う）

```sh
git status --short            # 自分が作っていない未コミット変更（AGENTS.md 等）は触らない
git checkout develop
git pull origin develop
git checkout -b feature/USL-69   # バグ対応は bug/USL-69
```

> develop に他者の未コミット変更が残っている場合、それは作業対象外。commit に含めない。

### 2. 対象 issue を確定し、仕様を読み込む（委譲のための準備）

- Linear MCP（`list_issues` project=reverb state=Todo / `get_issue`）で Backend issue を取得。
- issue が参照する仕様（`docs/specs/0X-*.md`）と関連スキーマ（`09-data-model.md`）を**Claude 自身が読む**。Codex に渡すコンテキスト（受け入れ基準・入出力 JSON・確定値・ステージ責務）を把握しておく。
- 既存コード（`backend/` があれば）の構成・既存の adapter/サービス境界を確認。

### 3. Linear ステータスを In Progress に

`save_issue` で `state: "In Progress"`。

### 4. Codex に実装を委譲

`Agent` ツールで `subagent_type: "codex:codex-rescue"` を使い、**実装タスクを丸ごと Codex に渡す**（substantial coding task の委譲）。プロンプトには次を必ず含める:

- **対象 issue**: id・タイトル・やること・受け入れ基準（Linear 本文を貼る）。
- **一次情報源**: 読むべき仕様ファイルのパス（`docs/specs/0X-*.md`, `09-data-model.md`, `01-architecture.md`）。
- **配置と構成**（AGENTS.md 確定）:
  ```
  backend/
  ├── main.py     サイドカー起動・ハンドシェイク（127.0.0.1＋一時ポート）
  ├── api/        FastAPI router（/health /models /jobs … 01 と1:1）
  ├── schemas/    Pydantic（API DTO＝契約の単一情報源）
  ├── services/   JobService, PipelineRunner（extract→…→mix 統括）
  ├── pipeline/   各ステージ実装（1ステージ＝1モジュール）
  ├── adapters/   外部エンジンラッパ ★最重要（ffmpeg/whisper_mlx/ollama/voicevox）
  └── core/       config, errors, job store（永続化・再開）
  ```
- **絶対ルール（厳守させる）**:
  - ローカル完結（クラウドAPI・外部送信を書かない）。STT=mlx-whisper / 翻訳=Ollama(HTTP) / TTS=VOICEVOX(ローカルHTTP) / 抽出・ミックス=ffmpeg(サブプロセス)。
  - **モデル名・タグ・話者IDをハードコードしない**（設定値化・「導入時に最新タグ確認」コメント）。翻訳モデルは切替可能に保つ。
  - 品質優先（STT既定 large-v3 full、turbo化しない）。尺合わせ順序 speedScale(0.8〜1.3)→無音区間吸収→残差許容。確定初期値（音量100%/8%、字幕 全角20字/最大2行/最低1.5秒）を変えない。
  - macOS / Apple Silicon 固定。依存を勝手に増やさない（ffmpeg/Ollama/VOICEVOX を第一手段）。
  - adapters は **protocol(Protocol/ABC)** で境界化し、service はモック差し替え可能にする。Pydantic schema を API 契約の単一情報源にする。
  - スコープ外（複数話者打ち分け・リップシンク・ファイル書き出し・リアルタイム処理・動画DL）を実装しない。
  - **テスト/lint を用意**（pytest／ruff・black 等）。ビルド・テストコマンドが未確立なら確立し、実行手順を残す。
- **成果物**: 変更したファイル一覧と、テスト/起動コマンド、設計判断の要約を返すよう指示。

> 同じ失敗を2回以上繰り返す／難バグの場合は、`codex:rescue` に第二診断を委譲する（グローバル規律）。重要な設計判断は Codex の結論と Claude の見立てを突き合わせてから採用する。

### 5. 成果を検証（推測で「動いた」と言わない）

- Codex が変更したファイルを **Claude 自身が読み**、ルール違反（外部送信・ハードコード・スコープ外・尺合わせ順序の崩れ）が無いか確認。
- テスト・lint を実行してグリーンを確認する（Codex が確立したコマンドを使う。例）:
  ```sh
  cd backend && python -m pytest -q
  ruff check backend
  ```
- 可能なら起動・ハンドシェイク・主要エンドポイント（`/health` 等）を実際に叩いて確認。落ちたら出力ごと Codex に差し戻して直す。

### 6. レビュー → バグ/障害のみ修正

`general-purpose` subagent もしくは Codex の第二診断で、API 契約整合（`docs/specs/01 §4` の JSON と Pydantic schema）・並行性・サブプロセス制御・再開処理の観点でレビューさせる。**バグ・実行時障害・契約不整合のみ**修正（スタイルは不採用）。修正後にテスト再実行。

### 7. commit → push → PR 作成（PR にコメント必須）

- **このタスクで変更したファイルのみ** stage する（`AGENTS.md` 等の他者変更を巻き込まない）。
- commit メッセージ末尾に必須トレーラ:
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  ```
  本文に「実装: Codex（委譲）」と明記する。
- push 後 `gh pr create --base develop`。PR body 末尾に:
  ```
  🤖 Generated with [Claude Code](https://claude.com/claude-code)
  ```
- PR body: 概要 / Linear リンク / 実装内容 / 制約遵守 / Codex 委譲メモ / テスト結果。
- **PR にコメント**（`gh pr comment`）: レビュアー向けの重点箇所・フロントエンド連携で要確認な点（API 契約・SSE・成果物パス）・スコープ外で含めていない点。

### 8. Linear ステータスを PR Review に

`save_issue` で `state: "PR Review"`、`links` に PR URL を添付。

## 完了時

変更点を日本語で簡潔に要約（結論から）。Codex に委譲した範囲と Claude が検証・修正した範囲を分けて報告する。テスト結果を示し、スキップした手順は明示する。
