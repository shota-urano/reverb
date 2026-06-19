# 02. 音声抽出 仕様

**親**: [`00-overview.md`](./00-overview.md) ｜ **工程**: ① 音声抽出 ｜ **担当**: backend
**ステージ名**: `extract`

---

## 1. 目的

入力動画から、後続の文字起こし（STT）に適した音声トラックを抽出する。

---

## 2. 入出力

| | 内容 |
|---|---|
| 入力 | 動画ファイル（mp4 主対象、将来 mov / mkv 等） |
| 出力 | `audio.wav`（[`09-data-model.md`](./09-data-model.md) §3 参照） |
| ツール | **ffmpeg**（Python からサブプロセス呼び出し） |

---

## 3. 出力フォーマット（既定）

STT（mlx-whisper）入力に合わせる。

| 項目 | 値 | 理由 |
|------|----|------|
| コーデック | PCM 16bit（`pcm_s16le`） | 可逆・後段で扱いやすい |
| サンプリングレート | 16 kHz | Whisper 系の標準入力 |
| チャンネル | モノラル（1ch） | STT は単一話者ナレーション前提 |

> 元音声ミックス用（[`07-mix-sync.md`](./07-mix-sync.md)）には、必要に応じて別途フルレート音声を抽出する。本ステージの 16kHz/mono は **STT 用**。ミックスで元音声を使う際の取り回しは 07 が決定する（再抽出 or 元動画から直接）。

### 参考: ffmpeg 呼び出し（実装イメージ）

```
ffmpeg -i <videoPath> -vn -ac 1 -ar 16000 -c:a pcm_s16le -y audio.wav
```

> オプションは設定値に切り出し、ハードコードを避ける。

---

## 4. 処理詳細

1. 入力動画に音声トラックが存在するか確認（無ければ `failed`）。
2. ffmpeg で抽出。動画長（`duration`）を取得し `project.json` に記録。
3. 進捗は ffmpeg の出力時間から 0.0〜1.0 で算出し、`extract` ステージ進捗として通知。

---

## 5. エラー処理

| 事象 | 対応 |
|------|------|
| 音声トラック無し | `failed`（code: `NO_AUDIO_TRACK`）。UI に明示通知 |
| 非対応コンテナ/破損 | `failed`（code: `EXTRACT_FAILED`、ffmpeg stderr を message に） |
| ffmpeg 不在 | `failed`（code: `FFMPEG_UNAVAILABLE`）。`GET /health` でも検出 |

失敗は黙ってスキップしない。

---

## 6. スコープ外

- 音声ノイズ除去・音量正規化等の前処理（MVP では行わない。必要性は実測後に検討）。
- 複数音声トラックの選択 UI（既定トラックを使用）。

---

## 7. 関連仕様

- 次工程: [`03-transcription-stt.md`](./03-transcription-stt.md)
- 元音声の利用（ミックス）: [`07-mix-sync.md`](./07-mix-sync.md)
- 成果物スキーマ: [`09-data-model.md`](./09-data-model.md)
