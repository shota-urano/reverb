from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import List, Optional

from core.errors import StageError
from core.net import validate_loopback_url


class OllamaAdapter:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        translate_timeout_seconds: Optional[float] = None,
        keep_alive: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> None:
        # ローカル完結（ルール1）: 翻訳トラフィックを非ローカルへ流さないよう
        # 構築時にループバックのみへ制限する。
        self.base_url = validate_loopback_url("ollama_base_url", base_url)
        self.timeout_seconds = timeout_seconds
        self.translate_timeout_seconds = translate_timeout_seconds or timeout_seconds
        self.keep_alive = keep_alive
        self.temperature = temperature

    def ping(self) -> bool:
        try:
            self._get_json("/api/tags")
            return True
        except Exception:
            return False

    def list_models(self) -> List[str]:
        try:
            payload = self._get_json("/api/tags")
        except Exception:
            return []
        models = payload.get("models", [])
        names = [model.get("name") for model in models if isinstance(model, dict)]
        return [name for name in names if isinstance(name, str)]

    def translate(
        self,
        segments: list[dict[str, object]],
        model: str,
        source_lang: Optional[str],
        system_prompt: str,
        context_window: int,
    ) -> list[str]:
        context_segments = [segment for segment in segments if segment.get("contextOnly")]
        input_segments = [segment for segment in segments if not segment.get("contextOnly")]
        payload = {
            "model": model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": _translation_user_content(
                        source_lang,
                        context_window,
                        context_segments,
                        input_segments,
                    ),
                },
            ],
        }
        if self.keep_alive:
            payload["keep_alive"] = self.keep_alive
        if self.temperature is not None:
            payload["options"] = {"temperature": self.temperature}
        response = self._post_json("/api/chat", payload, model)
        message = response.get("message", {})
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            return []
        parsed = _parse_translation_array(content)
        return _translation_texts(parsed, input_segments)

    def warm_up(self, model: str, system_prompt: str) -> None:
        payload = {
            "model": model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "OK とだけ返してください。"},
            ],
        }
        if self.keep_alive:
            payload["keep_alive"] = self.keep_alive
        self._post_json("/api/chat", payload, model)

    def _get_json(self, path: str) -> dict:
        request = urllib.request.Request(
            self.base_url + path,
            method="GET",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def _post_json(self, path: str, payload: dict, model: str) -> dict:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.translate_timeout_seconds,
            ) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = _read_error_body(exc)
            if exc.code == 404 and "not found" in error_body.lower():
                raise StageError("MODEL_MISSING", _model_missing_message(model)) from exc
            raise StageError("OLLAMA_UNAVAILABLE", error_body or str(exc), retryable=True) from exc
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            raise StageError("OLLAMA_UNAVAILABLE", str(exc), retryable=True) from exc


def _translation_user_content(
    source_lang: Optional[str],
    context_window: int,
    context_segments: list[dict[str, object]],
    input_segments: list[dict[str, object]],
) -> str:
    return json.dumps(
        {
            "sourceLanguage": source_lang,
            "contextWindow": context_window,
            "contextSegments": _segment_text_payload(context_segments),
            "inputSegments": _segment_text_payload(input_segments),
        },
        ensure_ascii=False,
    )


def _segment_text_payload(segments: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "id": segment.get("id"),
            "text": segment.get("text", ""),
        }
        for segment in segments
    ]


def _parse_translation_array(content: str) -> list[object]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = _extract_json_array(content)
    if not isinstance(parsed, list):
        return []
    return parsed


def _extract_json_array(content: str) -> object:
    for start, char in enumerate(content):
        if char != "[":
            continue
        candidate = _balanced_json_array_candidate(content, start)
        if candidate is None:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return []


def _balanced_json_array_candidate(content: str, start: int) -> Optional[str]:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(content)):
        char = content[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return content[start : index + 1]
    return None


def _translation_texts(
    parsed: list[object],
    input_segments: list[dict[str, object]],
) -> list[str]:
    input_ids = [segment.get("id") for segment in input_segments]
    by_id: dict[object, dict[str, object]] = {}
    has_id_items = False
    can_map_by_id = bool(input_ids)

    for item in parsed:
        if not isinstance(item, dict) or "id" not in item:
            can_map_by_id = False
            continue
        has_id_items = True
        item_id = item["id"]
        if item_id in by_id:
            can_map_by_id = False
            continue
        by_id[item_id] = item

    if can_map_by_id:
        return [
            _translation_text(by_id[input_id]) if input_id in by_id else ""
            for input_id in input_ids
        ]

    if has_id_items:
        return [
            _translation_text(by_id[input_id]) if input_id in by_id else ""
            for input_id in input_ids
        ]

    return [
        _translation_text(parsed[index]) if index < len(parsed) else ""
        for index in range(len(input_segments))
    ]


def _translation_text(item: object) -> str:
    if isinstance(item, str):
        return item.replace("\n", " ").strip()
    if not isinstance(item, dict):
        return ""
    text = item.get("text")
    if not isinstance(text, str):
        return ""
    return text.replace("\n", " ").strip()


def _read_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8")
    except Exception:
        return str(exc)


def _model_missing_message(model: str) -> str:
    return (
        f"Ollama model is not available locally: {model}. "
        f"Run `ollama pull {model}` before running Reverb."
    )
