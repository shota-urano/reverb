# プロジェクト概要

Reverb（リバーブ）— 外国語の動画を**ローカル環境だけ**で「日本語吹き替え音声（ボイスオーバー）＋日本語字幕」付きで視聴できる Mac アプリ。**品質優先**（処理が多少遅くても訳・音声の質を取る）。
処理は事前一括型：音声抽出 → 文字起こし → 日本語翻訳 → 字幕整形 → 音声合成 → 尺合わせ・ミックス → アプリ内同期再生。

##  タスク管理
https://linear.app/uslab/project/reverb-6677e63bbf85/issues?layout=list&ordering=priority&grouping=workflowState&subGrouping=none&showCompletedIssues=all&showSubIssues=true&showTriageIssues=true
のissueを確認する

## lenear
- LabelsのModelsについて
    - 対象モデルが実装すること
    - 空の場合は人間が行う
- 実装が完了したらstatusをPR Reviewにすること

## 仕様の関連
docsを確認する
詳細な仕様書はdocs/specsを確認

## 実装担当者
Frontend・・・Opus4.8
backend・・・codex

## git運用ルール
develop：　baseとなるbranchなる | 全てのbranchはここから切り出す
feature：　機能追加
bug：　　　 バグ対応

ex) feature/USL-79
USL-79はlinearのid

## 技術スタック / 構成

**アーキテクチャ（確定・2層サイドカー）**: UI層＝SwiftUI+AVKit のネイティブMacアプリ。処理層＝Pythonバックエンドを Swift が裏でプロセス起動し、ローカルHTTP等で連携する。

| 工程 | 採用 | 呼び出し方 |
|------|------|-----------|
| UI | SwiftUI + AVKit | ネイティブMacアプリ |
| 処理基盤 | Python バックエンド | Swift からサイドカー起動・ローカルHTTP |
| 音声抽出・ミックス | ffmpeg | Python からサブプロセス |
| 文字起こし(STT) | mlx-whisper / **large-v3 full（既定）** | turbo は速度が要るとき切替 |
| 翻訳(LLM) | **複数モデル切替**（既定候補 Qwen3 30B級） | Ollama の HTTP API |
| 音声合成(TTS) | VOICEVOX / 落ち着いた男性の声 | ローカル HTTP API（speedScale で尺調整） |

- 動作環境: macOS / Apple Silicon、統合メモリ64GB前提（Whisper+翻訳LLM+VOICEVOX を同時常駐）。
- 現状リポジトリは `docs/requirements.md` のみ。**ビルド/テストコマンドは未確立**（コード未着手）。
- 詳細仕様・採用根拠・確定値は `docs/requirements.md`（v0.6・確定版）が一次情報源。

## コード設計（アーキテクチャ・確定）

両層とも **「画面/ルータ → ロジック → 外部I/Oをprotocolで隔離」** の同じ思想。フルClean Architecture（UseCase全クラス化）は4画面＋直線パイプラインに過剰なため、**Clean寄りのレイヤード（＝ヘキサゴナル軽量版）** を採用する。

### Frontend（SwiftUI / macOS）— MVVM + Repository（薄め）

状態は `@Observable` ベースの ViewModel が **Repository 経由**で取得。View は描画とユーザー操作通知のみ。境界は **protocol** で切る（テスト・モック用）。DI は `init` 注入 or `@Environment`。

```
Reverb/ (Swift)
├── App/                 AppShell, ナビゲーション
├── Features/
│   ├── Library/         LibraryView + LibraryViewModel
│   ├── Processing/      ProcessingView + ViewModel（進捗ポーリング/SSE）
│   ├── Player/          PlayerView + ViewModel
│   └── Settings/        SettingsView + ViewModel
├── Core/
│   ├── API/             BackendClient（HTTP/SSE）, SidecarLauncher
│   ├── Repository/      JobRepository, ModelRepository（protocol＋impl）
│   └── Models/          DTO（Codable, API契約と1:1）
└── Components/          共通部品（StageProgressList 等）
```

### Backend（Python サイドカー）— FastAPI + レイヤード

`FastAPI + Uvicorn + Pydantic`。内部は **router → service → adapter**。Pydantic schema を API契約の単一情報源とし、FastAPI の OpenAPI 出力で Swift 側 DTO とのズレを検出する。

```
backend/
├── main.py              サイドカー起動・ハンドシェイク（127.0.0.1＋一時ポート）
├── api/                 FastAPI router（/health /models /jobs ... 01-architecture と1:1）
├── schemas/             Pydantic（API DTO＝契約の単一情報源）
├── services/            JobService, PipelineRunner（ステージ統括 extract→…→mix）
├── pipeline/            各ステージ実装（1ステージ＝1モジュール）
├── adapters/            外部エンジンラッパ ★ここが肝
│   ├── ffmpeg.py
│   ├── whisper_mlx.py
│   ├── ollama.py        モデル名は引数＝設定値（ハードコード禁止・ルール5,6）
│   └── voicevox.py      話者IDも設定値
└── core/                config, errors, job store（永続化・再開 / 09-data-model）
```

- **adapters層が最重要**: 外部エンジンを差し替え可能な境界に隔離 → ルール5（翻訳モデル切替）・6（タグ非ハードコード）・11（依存固定）を構造で担保。
- service は adapter の **protocol（`Protocol`/ABC）** に依存させ、テスト時はモックに差し替える。

## 用語・前提

- **ボイスオーバー方式**: 日本語TTSを主、元音声を小音量で残す。**音量初期値＝日本語100% / 元音声8%**（再生中スライダーで調整可）。
- **事前一括処理型**: 再生前に全処理を完了させる。リアルタイム同時通訳ではない。
- **尺合わせ**: speedScale 0.8〜1.3 → 無音区間で吸収 → 残差は許容。リップシンクは目標にしない。
- **確定済みの初期値**: 字幕＝全角20字前後/最大2行/最低表示1.5秒/意味の切れ目で分割。元言語＝英語ベース＋Whisper自動判定で多言語も受ける。
- **対象コンテンツ**: 講義・解説・ドキュメンタリー等、単一話者・ナレーション主体。

## ルール

1. **ローカル完結を破らない**: STT=mlx-whisper、翻訳=Ollama(HTTP)、TTS=VOICEVOX(ローカルHTTP)。クラウドAPI呼び出し・外部送信を行うコードを書かない（本アプリの存在理由）。
2. **スコープ外を実装しない**（requirements §7）: 複数話者の声の打ち分け／リップシンク／ファイル書き出し／リアルタイム処理／動画ダウンロード。
3. **2層サイドカー構成を崩さない**: UI=SwiftUI+AVKit、処理=Pythonバックエンドをサイドカー起動しローカルHTTPで連携。UI層に処理ロジックを実装したり、別IPC方式を勝手に採用しない。
4. **確定済みの初期値を勝手に変えない**: 音量 日本語100%/元音声8%、speedScale 0.8〜1.3、字幕 全角20字前後/最大2行/最低1.5秒。変更は実測根拠＋承認のうえで行う。
5. **翻訳モデルは切替可能に保つ**: 単一モデルに固定実装しない。Ollama に複数 pull し、モデル名は設定値として API に渡す（既定候補 Qwen3 30B級）。
6. **モデル名/タグをハードコードしない**: バージョンは設定値に切り出し、「導入時に最新タグ確認」コメントを残す。
7. **品質優先を守る**: STT既定は large-v3 full。速度目的で既定を turbo 化したり、処理時間短縮のため品質を落とす最適化を勝手に入れない（turbo・高速化は明示承認の切替肢）。
8. **尺合わせの順序を守る**: speedScale(0.8〜1.3) → セグメント間の無音区間で吸収 → 残差は許容。独自の高度な時間伸縮を勝手に導入しない。
9. **単一話者・落ち着いた男性の声を既定にTTS**: 話者分離・複数ボイス制御を入れない（MVP）。話者は設定で変更可にする。
10. **macOS / Apple Silicon 固定**: Linux/CUDA/x86 前提の依存・分岐・命令を入れない。
11. **依存を勝手に増やさない**: 抽出・ミックス=ffmpeg(サブプロセス)、LLM=Ollama、TTS=VOICEVOX を第一手段にする。別SDK・重い依存の追加は提案して承認を取る。
12. **VOICEVOX 利用規約を順守**: クレジット表記等を壊す変更をしない（規約は未確認のため要確認に残す）。

## 振る舞い

- 範囲外の変更をしない。隣接コードに触れない（外科的変更）。
- 大きな変更・破壊的操作・本番影響の前に確認・明示承認を取る。
- 推測で進めず、不明点は質問する。
- 失敗を黙ってスキップせず必ず報告する。
- 作業後に変更点を要約する。

## 記憶 / 保守

- 決定と却下案は `MEMORY.md`、失敗→成功手順は `ERRORS.md` に記録する。
- 同じミスをしたら、このファイルに再発防止ルールを追記する（足すときは既存ルールの統合・削除をセットで、12ルール以内を維持）。
- 失敗の都度ここに追記し、コードが育ったら定期的に `/init` で再診断して差分をレビューのうえ適用する（無条件の自動適用はしない）。

## 役割分担（このプロジェクトの場合）

- **Hooks に逃がす候補**: Python のフォーマット/Lint（ruff・black 等）、Swift の `swift build`/フォーマット、外部URL送信を検知してブロックするガード。
- **Skills 化する候補**: 「動画1本を投入 → 抽出〜ミックスまで一括実行」する定型パイプライン実行手順。
- **Agents に委譲する候補**: 翻訳モデルの A/B 比較・選定（切替候補の評価、条件分岐が多い）、尺合わせ・字幕整形の許容範囲の実測チューニング。
