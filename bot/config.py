from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

HDHIVE_API_BASE = "https://hdhive.com/api/open"


def _parse_chat_ids(raw: str | None) -> list[int]:
    if not raw or not raw.strip():
        return []
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        out.append(int(part))
    return out


def _parse_pan_types(raw: str | None) -> set[str]:
    if not raw or not raw.strip():
        return set()
    return {p.strip().lower() for p in raw.split(",") if p.strip()}


def proxy_url() -> str | None:
    return (
        os.getenv("HTTPS_PROXY")
        or os.getenv("https_proxy")
        or os.getenv("HTTP_PROXY")
        or os.getenv("http_proxy")
        or None
    )


@dataclass
class Settings:
    hdhive_api_key: str
    telegram_bot_token: str
    allowed_chat_ids: tuple[int, ...]
    tmdb_api_key: str | None
    pan_types_filter: frozenset[str]  # lowercased; empty = no filter
    symedia_base_url: str | None
    symedia_token: str
    symedia_parent_id: str  # 115 folder CID; "0" = root
    symedia_timeout: float
    http_proxy: str | None = field(default_factory=lambda: proxy_url())

    @classmethod
    def from_env(cls) -> Settings:
        key = os.getenv("HDHIVE_API_KEY", "").strip()
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        chats = _parse_chat_ids(os.getenv("TELEGRAM_CHAT_ID"))
        tmdb = os.getenv("TMDB_API_KEY", "").strip() or None
        pans = _parse_pan_types(os.getenv("PAN_TYPES"))
        sym = os.getenv("SYMEDIA_BASE_URL", "").strip() or None
        sym_token = (os.getenv("SYMEDIA_TOKEN") or "symedia").strip() or "symedia"
        sym_pid = (os.getenv("SYMEDIA_PARENT_ID") or "0").strip() or "0"
        try:
            sym_to = float(os.getenv("SYMEDIA_TIMEOUT", "120").strip() or "120")
        except ValueError:
            sym_to = 120.0
        if not key:
            raise ValueError("HDHIVE_API_KEY is required")
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required")
        if not chats:
            raise ValueError("TELEGRAM_CHAT_ID is required (comma-separated chat ids)")
        return cls(
            hdhive_api_key=key,
            telegram_bot_token=token,
            allowed_chat_ids=tuple(chats),
            tmdb_api_key=tmdb,
            pan_types_filter=frozenset(pans),
            symedia_base_url=sym,
            symedia_token=sym_token,
            symedia_parent_id=sym_pid,
            symedia_timeout=sym_to,
            http_proxy=proxy_url(),
        )


def pan_type_allowed(pan_type: str | None, settings: Settings) -> bool:
    if not settings.pan_types_filter:
        return True
    if not pan_type:
        return False
    return pan_type.strip().lower() in settings.pan_types_filter
