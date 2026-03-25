from __future__ import annotations

import logging
from typing import Any

import httpx

from bot.config import HDHIVE_API_BASE

logger = logging.getLogger(__name__)


class HDHiveError(Exception):
    def __init__(self, message: str, code: str | None = None, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


async def fetch_resources(
    api_key: str,
    media_type: str,
    tmdb_id: str,
    *,
    proxy: str | None = None,
) -> list[dict[str, Any]]:
    """GET /resources/movie|tv/{tmdb_id}"""
    if media_type not in ("movie", "tv"):
        raise ValueError("media_type must be movie or tv")
    url = f"{HDHIVE_API_BASE.rstrip('/')}/resources/{media_type}/{tmdb_id}"
    headers = {"X-API-Key": api_key}
    async with httpx.AsyncClient(proxy=proxy, timeout=60.0) as client:
        r = await client.get(url, headers=headers)
    try:
        body = r.json()
    except Exception:
        logger.warning("影巢非 JSON 响应 status=%s body=%s", r.status_code, r.text[:500])
        raise HDHiveError(f"Invalid JSON (HTTP {r.status_code})", status=r.status_code)

    if not body.get("success"):
        raise HDHiveError(
            body.get("description") or body.get("message") or "HDHive error",
            code=str(body.get("code")),
            status=r.status_code,
        )
    data = body.get("data")
    if not isinstance(data, list):
        return []
    logger.info("影巢资源查询 %s/%s → %d 条", media_type, tmdb_id, len(data))
    return data


async def unlock_resource(
    api_key: str,
    slug: str,
    *,
    proxy: str | None = None,
) -> dict[str, Any]:
    """POST /resources/unlock → {url, access_code, full_url, already_owned}"""
    url = f"{HDHIVE_API_BASE.rstrip('/')}/resources/unlock"
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    async with httpx.AsyncClient(proxy=proxy, timeout=60.0) as client:
        r = await client.post(url, json={"slug": slug}, headers=headers)
    try:
        body = r.json()
    except Exception:
        raise HDHiveError(f"Invalid JSON (HTTP {r.status_code})", status=r.status_code)
    if not body.get("success"):
        raise HDHiveError(
            body.get("description") or body.get("message") or "unlock error",
            code=str(body.get("code")),
            status=r.status_code,
        )
    d = body.get("data") or {}
    logger.info("影巢解锁 slug=%s already_owned=%s", slug, d.get("already_owned"))
    return d
