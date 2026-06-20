from __future__ import annotations

import ipaddress
from typing import Optional
from urllib.parse import urlparse

# ローカル完結（ルール1）を構造で担保するための共通バリデーション。
# 待受ホスト・外部エンジン（Ollama/VOICEVOX）URL をループバックのみに制限し、
# クラウド/外部ホストへの送信を起点で不可能にする。

_LOOPBACK_HOSTNAMES = {"localhost"}


def is_loopback_host(hostname: Optional[str]) -> bool:
    if not hostname:
        return False
    if hostname in _LOOPBACK_HOSTNAMES:
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def validate_loopback_host(name: str, host: str) -> None:
    if not is_loopback_host(host):
        raise ValueError(f"{name} はループバックホストのみ許可されます: {host!r}")


def validate_loopback_url(name: str, url: str) -> str:
    """ループバックの http(s) URL のみ許可。正規化済み URL を返す。"""
    normalized = url.rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"{name} は http(s) URL である必要があります: {url!r}")
    if not is_loopback_host(parsed.hostname):
        raise ValueError(f"{name} はループバックエンドポイントのみ許可されます: {url!r}")
    return normalized
