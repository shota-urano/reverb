from __future__ import annotations

import json
import urllib.request
from typing import List

from core.net import validate_loopback_url


class OllamaAdapter:
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        # ローカル完結（ルール1）: 翻訳トラフィックを非ローカルへ流さないよう
        # 構築時にループバックのみへ制限する。
        self.base_url = validate_loopback_url("ollama_base_url", base_url)
        self.timeout_seconds = timeout_seconds

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

    def _get_json(self, path: str) -> dict:
        request = urllib.request.Request(
            self.base_url + path,
            method="GET",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
