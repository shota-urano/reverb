# 06. 音声合成（TTS） 仕様

**親**: [`00-overview.md`](./00-overview.md) ｜ **工程**: ⑤ 音声合成 ｜ **担当**: backend
**ステージ名**: `tts`

---

## 1. 目的

字幕キュー（cue）の日本語テキストを、**AivisSpeech / VOICEVOX 互換TTS** で音声合成する。落ち着いた男性の声を既定とする（単一話者・MVP）。

---

## 2. 入出力

| | 内容 |
|---|---|
| 入力 | `translation.json` の translation segment 列（[`04`](./04-translation.md)） |
| 出力 | `tts/seg_%04d.wav`（translation segment ごとに1ファイル。[`09-data-model.md`](./09-data-model.md) §3.5） |
| エンジン | **AivisSpeech 既定 / VOICEVOX 選択可**（ローカル HTTP API） |

---

## 3. 話者（確定）

| 設定 | 既定 | 切替 |
|------|------|------|
| 話者 | **落ち着いた男性の声** | 設定で変更可（`settings.tts.speakerId` / `styleId`） |

- 話者分離・複数ボイス制御は入れない（単一話者・MVP、ルール9）。
- 話者 ID・スタイル ID はハードコードしない。`GET /speakers`（[`01-architecture.md`](./01-architecture.md)）で動的取得し、既定は設定値。
- 具体的な既定話者名・ID は導入時に利用エンジン側を確認して設定値に記録する。

---

## 4. 合成方針

- translation segment 単位で1ファイル生成（`segment.id` = ファイルインデックス）。字幕表示のために分割された cue 単位では合成しない。
- VOICEVOX 互換APIのフロー: テキスト → `audio_query` → 必要なら `speedScale` 等を設定 → `synthesis`。
- AivisSpeech では `intonationScale` の意味が VOICEVOX と異なるため、`audio_query` の既定値を尊重し、尺合わせに必要な `speedScale` のみ上書きする。
- **`speedScale` は尺合わせ（[`07-mix-sync.md`](./07-mix-sync.md)）で決定する値を用いる**。本ステージ単体では等速（1.0）で生成し、尺合わせで再合成 or speedScale 指定再生成する方式を基本とする（最終的な責務分担は 07 §尺合わせ手順に従う）。
- 出力フォーマットはエンジン既定（WAV）。後段ミックスで扱える PCM/WAV を維持。

> **尺合わせの順序を守る**（ルール8）: speedScale(0.8〜1.3) → 無音区間で吸収 → 残差許容。独自の高度な時間伸縮は入れない。speedScale の決定ロジックは 07 が持ち、TTS は指定された speedScale で合成する役割。

---

## 5. 処理詳細

1. translation segment を順に TTS エンジンへ送り合成。進捗は segment 処理数 / 総 segment 数で 0.0〜1.0。
2. `tts/seg_%04d.wav` を書き出し（空 target の segment はファイルを作らずスキップ）。
3. 全 segment 完了でステージ `done`。

---

## 6. エラー処理

| 事象 | 対応 |
|------|------|
| TTS 未起動/接続不可 | `failed`（code: `TTS_UNAVAILABLE`、retryable）。`/health` でも検出 |
| 指定話者 ID 不正 | `failed`（code: `SPEAKER_INVALID`） |
| 個別 cue の合成失敗 | 再試行。継続失敗で当該 cue を無音扱いにし warning（全体は継続） |

---

## 7. ライセンス

- **VOICEVOX 利用規約を順守**（ルール12）。クレジット表記等を壊さない（VOICEVOX 併用時）。
- **AivisSpeech（既定エンジン）**: エンジン本体は LGPL-3.0。採用音声モデル **「阿井田 茂 / ノーマル」**
  は **ACML 1.0**（2026-06-23 確認）。**クレジット表記は任意**、義務はモデル再配布時のライセンス同梱のみで、
  ローカル生成のみの本アプリには該当しない。個人/非商用・ローカル完結で要件充足（ルール12）。
- 音声モデルを変更する場合は、そのモデルの ACML / ACML-NC / CC0 区分を `GET /speaker_info` の `policy`
  等で都度確認する。任意で付けるクレジットは [`08-playback-ui.md`](./08-playback-ui.md) のUI（アバウト/クレジット）に組み込む。

---

## 8. スコープ外

- 複数話者の打ち分け（将来拡張）。
- 複数TTSの同時併用や話者自動選択（将来拡張）。

---

## 9. 関連仕様

- 前工程（cue）: [`05-subtitle.md`](./05-subtitle.md)
- 次工程（尺合わせ・speedScale 決定）: [`07-mix-sync.md`](./07-mix-sync.md)
- 話者一覧 API: [`01-architecture.md`](./01-architecture.md)
- スキーマ: [`09-data-model.md`](./09-data-model.md)
