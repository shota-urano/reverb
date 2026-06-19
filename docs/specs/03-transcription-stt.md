# 03. 文字起こし（STT） 仕様

**親**: [`00-overview.md`](./00-overview.md) ｜ **工程**: ② 文字起こし ｜ **担当**: backend
**ステージ名**: `transcribe`

---

## 1. 目的

抽出済み音声から、**タイムスタンプ付き** の元言語テキスト（セグメント列）を生成する。品質優先。

---

## 2. 入出力

| | 内容 |
|---|---|
| 入力 | `audio.wav`（16kHz / mono、[`02`](./02-audio-extraction.md)） |
| 出力 | `transcript.json`（[`09-data-model.md`](./09-data-model.md) §3.2） |
| エンジン | **mlx-whisper**（Apple Silicon 最適化） |

---

## 3. モデル（確定）

| 設定 | 既定 | 切替 |
|------|------|------|
| STT モデル | **large-v3（full）** | turbo は速度が要るときのみ、**明示承認** で切替 |

- **品質優先**: 速度目的で既定を turbo 化しない（ルール7）。
- 精度はエンジンではなくモデルで決まる。既定 full を維持する。
- モデル名・タグはハードコードせず設定値に切り出し、「導入時に最新タグ確認」コメントを残す。

---

## 4. 言語判定（確定）

- 元言語は **英語ベース ＋ Whisper 自動判定** で多言語も受ける。
- API の `settings.stt.language`:
  - `null`（既定）: Whisper 自動判定。
  - 明示指定（例 `"en"`, `"ja"`）: 指定言語で固定。
- 判定結果は `transcript.json.language` に記録する。

---

## 5. 出力（セグメント）

- Whisper のセグメント単位でタイムスタンプ（`start`/`end`）と `text` を出力。
- `id` は 0 始まりの連番・昇順・連続（[`09`](./09-data-model.md) §3.2）。
- `text` はトリム。明らかな無音・無発話区間はセグメント化しない。

> セグメントは「翻訳の入力単位」。字幕表示単位（cue）への再分割は [`05-subtitle.md`](./05-subtitle.md) が行う。STT は意味分割を担わない。

---

## 6. 処理詳細

1. `audio.wav` を mlx-whisper（large-v3）で処理。`word_timestamps` は必要に応じ取得（cue 分割の精度向上に利用可。最終判断は 05）。
2. 進捗は処理済み時間 / 総時間で 0.0〜1.0 を算出し `transcribe` 進捗として通知。
3. `transcript.json` を書き出し、`project.json` のステージを `done` に。

---

## 7. エラー処理

| 事象 | 対応 |
|------|------|
| モデル未取得 | `failed`（code: `STT_MODEL_MISSING`）。導入手順を message に |
| 推論失敗 | `failed`（code: `STT_FAILED`） |
| 全編無発話 | 空セグメントで `done`。下流は字幕・音声なしとして扱う |

---

## 8. スコープ外

- 話者分離（単一話者前提・MVP）。
- 手動の文字起こし修正 UI（将来拡張）。

---

## 9. 関連仕様

- 前工程: [`02-audio-extraction.md`](./02-audio-extraction.md)
- 次工程: [`04-translation.md`](./04-translation.md)
- セグメント→cue 分割: [`05-subtitle.md`](./05-subtitle.md)
- スキーマ: [`09-data-model.md`](./09-data-model.md)
