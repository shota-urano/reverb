from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import List, Optional

from core.errors import StageError
from core.net import validate_loopback_url
from schemas.meta import Speaker


class VoicevoxAdapter:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        synthesis_timeout_seconds: Optional[float] = None,
    ) -> None:
        # ローカル完結（ルール1）: TTS データを外部サービスへ送らないよう
        # 構築時にループバックのみへ制限する。
        self.base_url = validate_loopback_url("voicevox_base_url", base_url)
        self.timeout_seconds = timeout_seconds
        self.synthesis_timeout_seconds = synthesis_timeout_seconds or timeout_seconds

    def ping(self) -> bool:
        try:
            self._get_json("/version")
            return True
        except Exception:
            return False

    def list_speakers(self) -> List[Speaker]:
        try:
            payload = self._get_json("/speakers")
        except Exception:
            return []

        speakers: List[Speaker] = []
        if not isinstance(payload, list):
            return speakers
        for speaker in payload:
            if not isinstance(speaker, dict):
                continue
            name = speaker.get("name")
            styles = speaker.get("styles", [])
            if not isinstance(name, str) or not isinstance(styles, list):
                continue
            for style in styles:
                if not isinstance(style, dict):
                    continue
                style_id = style.get("id")
                if isinstance(style_id, int):
                    speakers.append(Speaker(speakerId=style_id, name=name, styleId=style_id))
        return speakers

    def synthesize(
        self,
        text: str,
        speaker_id: int,
        style_id: int,
        speed_scale: float = 1.0,
    ) -> bytes:
        query = self._post_json(
            "/audio_query",
            {"text": text, "speaker": style_id},
            speaker_id,
            style_id,
        )
        query["speedScale"] = speed_scale
        return self._post_bytes(
            "/synthesis",
            {"speaker": style_id},
            query,
            speaker_id,
            style_id,
        )

    def _get_json(self, path: str):
        request = urllib.request.Request(
            self.base_url + path,
            method="GET",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def _post_json(
        self,
        path: str,
        params: dict[str, object],
        speaker_id: int,
        style_id: int,
    ) -> dict:
        request = urllib.request.Request(
            self._url(path, params),
            data=b"",
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.synthesis_timeout_seconds,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            _raise_stage_error(exc, speaker_id, style_id)
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            raise StageError("VOICEVOX_UNAVAILABLE", str(exc), retryable=True) from exc
        if not isinstance(payload, dict):
            raise StageError("TTS_SYNTHESIS_FAILED", "VOICEVOX returned an invalid audio query.")
        return payload

    def _post_bytes(
        self,
        path: str,
        params: dict[str, object],
        payload: dict,
        speaker_id: int,
        style_id: int,
    ) -> bytes:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self._url(path, params),
            data=body,
            method="POST",
            headers={
                "Accept": "audio/wav",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.synthesis_timeout_seconds,
            ) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            _raise_stage_error(exc, speaker_id, style_id)
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            raise StageError("VOICEVOX_UNAVAILABLE", str(exc), retryable=True) from exc

    def _url(self, path: str, params: dict[str, object]) -> str:
        query = urllib.parse.urlencode(params)
        return f"{self.base_url}{path}?{query}"


def _raise_stage_error(
    exc: urllib.error.HTTPError,
    speaker_id: int,
    style_id: int,
) -> None:
    message = _read_error_body(exc)
    if exc.code in (400, 422):
        raise StageError(
            "SPEAKER_INVALID",
            message or f"VOICEVOX speaker/style is invalid: {speaker_id}/{style_id}",
            retryable=False,
        ) from exc
    raise StageError("TTS_SYNTHESIS_FAILED", message or str(exc), retryable=True) from exc


def _read_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8")
    except Exception:
        return str(exc)
