# Reverb Backend

Python sidecar backend for the Reverb macOS app.

## Setup

```bash
cd backend
python3 -m pip install -r requirements.txt
```

## Run

```bash
cd backend
python3 main.py
```

After Uvicorn starts listening on `127.0.0.1` with an OS-assigned ephemeral port, the
process writes one JSON handshake line to stdout:

```json
{"event":"ready","baseURL":"http://127.0.0.1:<port>","pid":12345,"version":"0.6.0"}
```

## Test and Format

```bash
cd backend
python3 -m pytest -q
python3 -m ruff check .
python3 -m black --check .
```

## Pipeline Stages

The production pipeline is **fully implemented**. `services/job_service.py:build_pipeline_stages`
wires the real stages behind the common `Stage` ABC, in order:

`extract -> transcribe -> translate -> subtitle -> tts -> mix`

| Stage | 実装 | 外部エンジン | 担当 issue |
|-------|------|-------------|-----------|
| `ExtractStage` | `pipeline/extract.py` | ffmpeg（サブプロセス） | USL-69 |
| `TranscribeStage` | `pipeline/transcribe.py` | mlx-whisper（large-v3 既定） | USL-70 |
| `TranslateStage` | `pipeline/translate.py` | Ollama（HTTP） | USL-71 |
| `SubtitleStage` | `pipeline/subtitle.py` | —（整形のみ） | USL-72 |
| `TtsStage` | `pipeline/tts.py` | VOICEVOX（ローカルHTTP） | USL-73 |
| `MixStage` | `pipeline/mix.py` | ffmpeg + VOICEVOX | USL-74 |

> `pipeline/stub_stages.py`（`StubStage` / `build_stub_stages`）は**テスト専用**で、
> 空のプレースホルダ成果物を書き出す。本番パイプラインには配線されていない
> （`tests/` で個別ステージを単体検証する際に他ステージを差し替える用途）。

## Prerequisites for real-engine run

実機で `extract -> ... -> mix` を通すには、ローカルの外部エンジンが起動・準備済みである必要がある
（API レイヤは可用性チェックのみ行う）。モデル名・話者IDは**すべて設定値**で、既定は環境変数で上書きできる
（タグは導入時に最新を確認すること）。

- **STT (mlx-whisper)**: 既定モデル `large-v3`（`REVERB_STT_MODEL`）。HF リポジトリ解決表は
  `REVERB_STT_MODEL_REPOS`。初回実行前にモデル重みのキャッシュ（ダウンロード）が必要。
- **翻訳 (Ollama)**: 既定 `http://127.0.0.1:11434`（`REVERB_OLLAMA_BASE_URL`）で Ollama を起動し、
  既定モデル `qwen3:30b-a3b`（`REVERB_TRANSLATE_MODEL`）を事前に `ollama pull` しておく。
- **TTS (VOICEVOX)**: 既定 `http://127.0.0.1:50021`（`REVERB_VOICEVOX_BASE_URL`）で VOICEVOX エンジンを
  起動。既定話者は `REVERB_SPEAKER_ID` / `REVERB_SPEAKER_NAME` / `REVERB_STYLE_ID`。
- **ffmpeg / ffprobe**: PATH 上に存在すること（`REVERB_FFMPEG_BIN` / `REVERB_FFPROBE_BIN` で上書き可）。

## TODO: VOICEVOX ライセンス・クレジット表記（USL-81 / ルール12）

TTS（VOICEVOX）の本実装・出荷前に、利用規約とクレジット表記の確認が必要（担当: 人間 / USL-81）。

- エンジン本体は LGPL v3（別ライセンスの選択肢あり）。組込み方法に応じた義務を確認する。
- 生成音声には音声ライブラリ単位のクレジット表記 `VOICEVOX:[話者名]` が必要。
- 採用話者ごとの個別利用規約にも準拠する（再配布・利用範囲）。
- 確定後、表記文言を Frontend のクレジット UI（USL-76/プレーヤー）へ反映する。

参照: `docs/specs/06-tts.md §7`, `docs/specs/00-overview.md §5`, Linear USL-81。
