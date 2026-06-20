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
