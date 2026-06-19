# 09. データモデル・中間成果物・プロジェクト/ジョブ管理 仕様

**親**: [`00-overview.md`](./00-overview.md) ｜ **担当**: backend / frontend
**範囲**: プロジェクトのディレクトリ構成、各工程の中間成果物 JSON スキーマ、ジョブの永続化・再開

> 本書は全工程が共有するデータ契約の一次情報源。各ステージ仕様（02〜07）は本書のスキーマを参照する。

---

## 1. プロジェクトとジョブ

- **プロジェクト (project)**: 動画1本分の作業単位。中間成果物一式を1ディレクトリに保持する。
- **ジョブ (job)**: 1プロジェクトに対する1回のパイプライン実行。再処理すると新しいジョブになるが、プロジェクトは同一。

### 1.1 プロジェクトディレクトリ構成

保存先既定: `~/Library/Application Support/Reverb/projects/<projectId>/`

```
<projectId>/
├── project.json          # プロジェクト/ジョブのマニフェスト（メタ・設定・状態）
├── audio.wav             # ① 音声抽出の出力        → 02-audio-extraction.md
├── transcript.json       # ② STT の出力            → 03-transcription-stt.md
├── translation.json      # ③ 翻訳の出力            → 04-translation.md
├── subtitles.json        # ④ 字幕整形の出力         → 05-subtitle.md
├── tts/
│   ├── cue_0000.wav      # ⑤ キュー単位の TTS 音声  → 06-tts.md
│   └── cue_0001.wav
└── voiceover.wav         # ⑥ 尺合わせ・ミックス出力  → 07-mix-sync.md
```

- 元動画はコピーせず、`project.json` に絶対パスを記録（移動・削除された場合は UI で再選択を促す）。
- すべて UTF-8 / JSON は `version` フィールドでスキーマ版を持つ。
- 時刻は **秒（float）**、音声は **WAV（PCM）** を中間形式とする。

---

## 2. 共通の時間単位

- `start` / `end`: 動画先頭からの秒数（float, 秒）。
- 区間は半開区間 `[start, end)` とみなす。
- すべての工程で同じ時間軸（元動画基準）を保持する。

---

## 3. スキーマ定義

### 3.1 `project.json`（マニフェスト）

```json
{
  "version": 1,
  "projectId": "p_01H...",
  "videoPath": "/Users/me/Movies/lecture.mp4",
  "createdAt": "2026-06-19T12:00:00Z",
  "duration": 3600.0,
  "settings": {
    "stt":       { "model": "large-v3", "language": null },
    "translate": { "model": "qwen3:30b" },
    "tts":       { "speakerId": 13, "styleId": 0 },
    "mix":       { "jaVolume": 1.0, "originalVolume": 0.08 }
  },
  "job": {
    "jobId": "j_01H...",
    "status": "running",
    "stages": {
      "extract":    { "status": "done",    "artifact": "audio.wav" },
      "transcribe": { "status": "done",    "artifact": "transcript.json" },
      "translate":  { "status": "running", "artifact": null },
      "subtitle":   { "status": "pending", "artifact": null },
      "tts":        { "status": "pending", "artifact": null },
      "mix":        { "status": "pending", "artifact": null }
    }
  }
}
```

ステージ `status`: `pending | running | done | failed | canceled`。

### 3.2 `transcript.json`（STT 出力）→ [03](./03-transcription-stt.md)

```json
{
  "version": 1,
  "engine": "mlx-whisper",
  "model": "large-v3",
  "language": "en",          // Whisper 自動判定 or 指定値
  "duration": 3600.0,
  "segments": [
    { "id": 0, "start": 0.0,  "end": 4.2,  "text": "Welcome to the lecture." },
    { "id": 1, "start": 4.2,  "end": 9.8,  "text": "Today we will discuss..." }
  ]
}
```

- `id`: セグメント連番（0 始まり、昇順・連続）。
- `text`: 元言語の文字列（トリム済み）。

### 3.3 `translation.json`（翻訳出力）→ [04](./04-translation.md)

`transcript.json` のセグメント構造を維持し、訳文を付与する（id で対応）。

```json
{
  "version": 1,
  "model": "qwen3:30b",
  "sourceLanguage": "en",
  "targetLanguage": "ja",
  "segments": [
    { "id": 0, "start": 0.0, "end": 4.2, "source": "Welcome to the lecture.",
      "target": "講義へようこそ。" },
    { "id": 1, "start": 4.2, "end": 9.8, "source": "Today we will discuss...",
      "target": "本日は〜について解説します。" }
  ]
}
```

### 3.4 `subtitles.json`（字幕整形出力）→ [05](./05-subtitle.md)

翻訳セグメントを **表示単位（cue）** に再分割／結合したもの。TTS もこの cue 単位で生成する。

```json
{
  "version": 1,
  "cues": [
    { "id": 0, "start": 0.0,  "end": 4.2,  "lines": ["講義へようこそ。"],
      "segmentIds": [0] },
    { "id": 1, "start": 4.2,  "end": 9.8,  "lines": ["本日は字幕整形について", "解説します。"],
      "segmentIds": [1] }
  ]
}
```

- `id`: cue 連番（0 始まり）。`tts/cue_%04d.wav` のインデックスと一致させる。
- `lines`: 表示行（最大2行 / 各行 全角20字前後）。
- `segmentIds`: 由来となった翻訳セグメント id（トレーサビリティ用）。
- `start`/`end`: 元動画時間軸上の表示区間。

### 3.5 TTS 音声（`tts/cue_%04d.wav`）→ [06](./06-tts.md)

- cue ごとに1ファイル。ファイル名インデックス = `cue.id`。
- 生成時の `speedScale` 等の付随情報は `project.json` または別 `tts/manifest.json`（任意）に記録してよい（尺合わせの実値は [07](./07-mix-sync.md) が決定）。

### 3.6 `voiceover.wav`（最終ミックス）→ [07](./07-mix-sync.md)

- 日本語 TTS（主）＋ 元音声（小音量）をミックスした全長音声。
- 再生時は動画の映像とこの音声を同期再生する（[08](./08-playback-ui.md)）。
- 音量バランスは再生時に UI 側で動的調整するため、**初期値での合成物**として保持する方式を基本とする（実装方式の最終判断は [07](./07-mix-sync.md) §音量制御）。

---

## 4. ジョブの永続化・再開

- 各ステージ完了時に成果物を書き出し、`project.json` の `job.stages[*].status` を更新する。
- 途中失敗・中断時、`done` のステージは再利用し、`failed`/`pending` から再開できる（再処理は冪等：同一入力なら同一成果物を上書き）。
- 設定（モデル・話者等）を変更して再処理する場合、影響を受ける下流ステージのみ `pending` に戻す。
  - 例: 翻訳モデル変更 → `translate` 以降を再実行（`extract`/`transcribe` は再利用）。

---

## 5. 関連仕様

- 全体像: [`00-overview.md`](./00-overview.md)
- API（ジョブ作成・進捗・結果）: [`01-architecture.md`](./01-architecture.md)
- 各成果物の生成仕様: [02](./02-audio-extraction.md)〜[07](./07-mix-sync.md)
- 成果物の利用（再生）: [08](./08-playback-ui.md)
