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

## Current Stub Scope

The pipeline stages are scaffolded behind the common `Stage` ABC and currently write
empty placeholder artifacts in the required order:

`extract -> transcribe -> translate -> subtitle -> tts -> mix`

External engines are only checked for availability. STT, translation, TTS, and mix
execution will be implemented by later backend issues without changing the API layer.

## TODO: VOICEVOX ライセンス・クレジット表記（USL-81 / ルール12）

TTS（VOICEVOX）の本実装・出荷前に、利用規約とクレジット表記の確認が必要（担当: 人間 / USL-81）。

- エンジン本体は LGPL v3（別ライセンスの選択肢あり）。組込み方法に応じた義務を確認する。
- 生成音声には音声ライブラリ単位のクレジット表記 `VOICEVOX:[話者名]` が必要。
- 採用話者ごとの個別利用規約にも準拠する（再配布・利用範囲）。
- 確定後、表記文言を Frontend のクレジット UI（USL-76/プレーヤー）へ反映する。

参照: `docs/specs/06-tts.md §7`, `docs/specs/00-overview.md §5`, Linear USL-81。
