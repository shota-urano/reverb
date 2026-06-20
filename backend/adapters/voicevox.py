from __future__ import annotations

import json
import urllib.request
from typing import List

from core.net import validate_loopback_url
from schemas.meta import Speaker


class VoicevoxAdapter:
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        # ローカル完結（ルール1）: TTS データを外部サービスへ送らないよう
        # 構築時にループバックのみへ制限する。
        self.base_url = validate_loopback_url("voicevox_base_url", base_url)
        self.timeout_seconds = timeout_seconds

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

    def _get_json(self, path: str):
        request = urllib.request.Request(
            self.base_url + path,
            method="GET",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
