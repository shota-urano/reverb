# 01. アーキテクチャ・サイドカー・バックエンド API 仕様

**親**: [`00-overview.md`](./00-overview.md) ｜ **担当**: backend
**範囲**: 2層サイドカー構成、Python バックエンドのプロセス起動・ライフサイクル、UI↔バックエンドのローカル HTTP API

---

## 1. 目的

UI（SwiftUI）と処理（Python）を分離した 2層サイドカー構成を定義する。UI 層に処理ロジックを置かず、別 IPC 方式を勝手に採用しないための取り決めをここに集約する。

---

## 2. 構成と責務

| 層 | 実装 | 責務 | 持たないもの |
|----|------|------|-------------|
| UI 層 | SwiftUI + AVKit | 動画選択、再生・字幕表示、設定、進捗表示、API 呼び出し | STT/翻訳/TTS/ミックス等の処理ロジック |
| バックエンド層 | Python（サイドカー） | ジョブ管理、パイプライン統括、外部エンジン制御、進捗通知 | 画面描画 |
| 外部エンジン | ffmpeg / mlx-whisper / Ollama / VOICEVOX | 各処理の実行 | — |

**原則**: UI ↔ バックエンドの連携手段は **ローカル HTTP のみ**。他の IPC（XPC, gRPC, ソケット直叩き等）を勝手に追加しない。

---

## 3. サイドカーのライフサイクル

### 3.1 起動

1. Swift アプリ起動時、バンドル同梱の Python バックエンドを子プロセスとして起動する。
2. バックエンドは **`127.0.0.1` のみ** で待ち受ける（外部公開しない）。ポートは **OS 割当の一時ポート（ephemeral）** を使用。
3. バックエンドは listen 開始後、待受 URL を **標準出力に1行 JSON でハンドシェイク出力** する。Swift はこれを読んで baseURL を確定する。

   ```json
   {"event": "ready", "baseURL": "http://127.0.0.1:53412", "pid": 12345, "version": "0.6.0"}
   ```

4. Swift は `GET /health` の成功を確認してから UI を有効化する。

> ポート番号・ホストをハードコードしない（一時ポート＋ハンドシェイクで受け渡す）。

### 3.2 監視・終了

- Swift はバックエンド子プロセスの生存を監視。異常終了時は再起動を試み、UI にエラー表示する。
- アプリ終了時、Swift は `POST /shutdown` を送ってから子プロセスを終了（タイムアウト時は強制終了）。
- バックエンドは親プロセス（Swift）の消失を検知したら自死する（ゾンビ化防止）。

### 3.3 外部エンジンの前提

- **Ollama**: ローカルで起動済みであることを前提（HTTP API）。未起動時は `GET /health` の `dependencies` で `ollama: false` を返す。
- **VOICEVOX**: ローカル HTTP API。起動状態を同様に `dependencies` で返す。
- **ffmpeg / mlx-whisper**: バックエンドからサブプロセス／ライブラリ呼び出し。
- 依存エンジンの導入・起動手順は別途運用ドキュメント化（本書スコープ外）。

---

## 4. バックエンド HTTP API

`Content-Type: application/json`。すべて `127.0.0.1` ローカル限定。認証は行わない（ローカル専用のため）。

### 4.1 ヘルス / メタ

#### `GET /health`
依存エンジンの可用性を返す。

```json
{
  "status": "ok",
  "version": "0.6.0",
  "dependencies": {
    "ffmpeg": true,
    "mlx_whisper": true,
    "ollama": true,
    "voicevox": true
  }
}
```

#### `GET /models`
翻訳に使える Ollama モデル一覧（[`04-translation.md`](./04-translation.md)）。

```json
{ "default": "qwen3:30b", "models": ["qwen3:30b", "gemma3:27b", "elyza:jp8b"] }
```

#### `GET /speakers`
VOICEVOX の話者一覧（[`06-tts.md`](./06-tts.md)）。

```json
{ "default": {"speakerId": 13, "name": "青山龍星", "styleId": 0},
  "speakers": [ {"speakerId": 13, "name": "...", "styleId": 0} ] }
```

> モデル名・話者 ID はハードコードしない。`/models` `/speakers` で動的取得し、既定は設定値とする。

### 4.2 ジョブ（パイプライン実行）

#### `POST /jobs`
動画1本の処理ジョブを作成。中間成果物・プロジェクト管理は [`09-data-model.md`](./09-data-model.md)。

リクエスト:
```json
{
  "videoPath": "/Users/me/Movies/lecture.mp4",
  "settings": {
    "stt":   { "model": "large-v3", "language": null },
    "translate": { "model": "qwen3:30b" },
    "tts":   { "speakerId": 13, "styleId": 0 },
    "mix":   { "jaVolume": 1.0, "originalVolume": 0.08 }
  }
}
```

- `settings` 省略時はバックエンド既定（確定初期値）を使用。
- `language: null` は Whisper 自動判定（[`03-transcription-stt.md`](./03-transcription-stt.md)）。

レスポンス:
```json
{ "jobId": "j_01H...", "projectId": "p_01H...", "status": "queued" }
```

#### `GET /jobs/{jobId}`
進捗・ステージ状態を返す。

```json
{
  "jobId": "j_01H...",
  "projectId": "p_01H...",
  "status": "running",          // queued | running | done | failed | canceled
  "currentStage": "translate",
  "progress": 0.42,              // 0.0〜1.0（全体）
  "stages": [
    {"name": "extract",   "status": "done",    "progress": 1.0},
    {"name": "transcribe","status": "done",    "progress": 1.0},
    {"name": "translate", "status": "running", "progress": 0.30},
    {"name": "subtitle",  "status": "pending", "progress": 0.0},
    {"name": "tts",       "status": "pending", "progress": 0.0},
    {"name": "mix",       "status": "pending", "progress": 0.0}
  ],
  "error": null
}
```

ステージ名（固定・全工程共通）: `extract` → `transcribe` → `translate` → `subtitle` → `tts` → `mix`。

#### `GET /jobs/{jobId}/events`（SSE）
進捗をサーバー送信イベントで配信（任意。ポーリングでも可）。

```
event: progress
data: {"currentStage":"tts","progress":0.66,"stages":[...]}

event: done
data: {"projectId":"p_01H...","result":{...}}
```

#### `POST /jobs/{jobId}/cancel`
処理を中断。実行中の外部サブプロセスも停止。`status: canceled` に遷移。

#### `GET /jobs/{jobId}/result`
完了ジョブの成果物パスを返す（再生に必要な情報）。

```json
{
  "projectId": "p_01H...",
  "videoPath": "/Users/me/Movies/lecture.mp4",
  "voiceoverPath": ".../voiceover.wav",
  "subtitlesPath": ".../subtitles.json",
  "duration": 3600.0
}
```

### 4.3 制御

#### `POST /shutdown`
バックエンドを安全停止（アプリ終了時に Swift が呼ぶ）。

---

## 5. エラー処理

- HTTP ステータス＋エラーボディを返す。失敗は黙ってスキップしない（必ず `error` に理由を載せる）。

  ```json
  { "error": { "code": "OLLAMA_UNAVAILABLE", "stage": "translate",
               "message": "Ollama に接続できません", "retryable": true } }
  ```

- ステージ失敗時は `GET /jobs/{id}` の `status: failed` ＋ `error` で UI に通知。
- 中間成果物が存在する工程までは保存され、再開可能とする（[`09-data-model.md`](./09-data-model.md) §再開）。

---

## 6. 関連仕様

- 前提・全体像: [`00-overview.md`](./00-overview.md)
- データ・成果物・ジョブ永続化: [`09-data-model.md`](./09-data-model.md)
- 各ステージ: [`02`](./02-audio-extraction.md)〜[`07`](./07-mix-sync.md)
- UI 側の API 利用: [`08-playback-ui.md`](./08-playback-ui.md)
