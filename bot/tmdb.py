from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TMDB_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)


class TMDBError(Exception):
    pass


TMDB_IMAGE_W500 = "https://image.tmdb.org/t/p/w500"

# 片名搜索最多展示的 TMDB 卡片数（每条会打一次详情+credits）
TMDB_SEARCH_CARD_LIMIT = 8


async def fetch_media_poster(
    api_key: str,
    media_type: str,
    tmdb_id: str,
    *,
    language: str = "zh-CN",
    proxy: str | None = None,
) -> tuple[str | None, str]:
    """获取 TMDB 海报直链与标题；zh-CN 无海报时自动回退英文/原始语言。"""
    if media_type not in ("movie", "tv"):
        return None, ""
    path = f"movie/{tmdb_id}" if media_type == "movie" else f"tv/{tmdb_id}"
    url = f"https://api.themoviedb.org/3/{path}"

    for lang in (language, "en-US", None):
        params: dict[str, str] = {"api_key": api_key}
        if lang:
            params["language"] = lang
        try:
            async with httpx.AsyncClient(proxy=proxy, timeout=TMDB_TIMEOUT, verify=False) as client:
                r = await client.get(url, params=params)
        except Exception:
            logger.warning("TMDB 海报请求失败 id=%s lang=%s", tmdb_id, lang, exc_info=True)
            continue
        if r.status_code != 200:
            continue
        data = r.json()
        pp = data.get("poster_path")
        if pp:
            title = (data.get("title") or data.get("name") or "").strip()
            return f"{TMDB_IMAGE_W500}{pp}", title
    return None, ""


async def search_multi(
    api_key: str,
    query: str,
    *,
    language: str = "zh-CN",
    proxy: str | None = None,
) -> list[dict[str, Any]]:
    """TMDB multi search; returns items with media_type movie or tv."""
    q = query.strip()
    if not q:
        return []
    url = "https://api.themoviedb.org/3/search/multi"
    params = {"api_key": api_key, "query": q, "language": language, "include_adult": "false"}

    r: httpx.Response | None = None
    for attempt in range(4):
        try:
            async with httpx.AsyncClient(proxy=proxy, timeout=TMDB_TIMEOUT, verify=False) as client:
                r = await client.get(url, params=params)
        except Exception:
            logger.warning("TMDB 搜索连接失败 attempt=%s", attempt)
            if attempt < 3:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            raise TMDBError("TMDB 网络异常，请稍后重试")

        if r.status_code == 429:
            wait = float(r.headers.get("Retry-After", "2"))
            logger.warning("TMDB 搜索限流 429, 等待 %.1fs", wait)
            await asyncio.sleep(min(wait, 10.0))
            continue
        if r.status_code >= 500 and attempt < 3:
            await asyncio.sleep(0.5 * (attempt + 1))
            continue
        break

    if r is None or r.status_code != 200:
        code = r.status_code if r else 0
        logger.warning("TMDB 搜索 HTTP %s", code)
        raise TMDBError(f"TMDB HTTP {code}")
    body = r.json()
    results = body.get("results") or []
    out: list[dict[str, Any]] = []
    for item in results:
        mt = item.get("media_type")
        if mt not in ("movie", "tv"):
            continue
        tid = item.get("id")
        if tid is None:
            continue
        title = item.get("title") or item.get("name") or ""
        date = item.get("release_date") or item.get("first_air_date") or ""
        year = (date[:4] if len(date) >= 4 else "") or "?"
        out.append(
            {
                "media_type": mt,
                "id": int(tid),
                "title": str(title),
                "year": year,
            }
        )
    return out[:TMDB_SEARCH_CARD_LIMIT]


async def fetch_media_card(
    api_key: str,
    media_type: str,
    tmdb_id: str,
    *,
    language: str = "zh-CN",
    proxy: str | None = None,
    overview_max: int = 200,
    cast_limit: int = 8,
) -> dict[str, Any]:
    """
    TMDB 详情 + credits（append_to_response），用于搜索卡片 caption / 海报。
    含 429/5xx 重试；失败时返回 ok=False，由调用方兜底。
    """
    if media_type not in ("movie", "tv"):
        return {"ok": False, "media_type": media_type, "id": tmdb_id}
    path = f"movie/{tmdb_id}" if media_type == "movie" else f"tv/{tmdb_id}"
    url = f"https://api.themoviedb.org/3/{path}"
    params = {
        "api_key": api_key,
        "language": language,
        "append_to_response": "credits",
    }

    r: httpx.Response | None = None
    for attempt in range(5):
        try:
            async with httpx.AsyncClient(proxy=proxy, timeout=TMDB_TIMEOUT, verify=False) as client:
                r = await client.get(url, params=params)
        except Exception:
            logger.warning("TMDB 详情连接失败 id=%s attempt=%s", tmdb_id, attempt, exc_info=True)
            if attempt < 4:
                await asyncio.sleep(0.35 * (attempt + 1))
                continue
            return {"ok": False, "media_type": media_type, "id": tmdb_id}

        if r is None:
            return {"ok": False, "media_type": media_type, "id": tmdb_id}

        if r.status_code == 429:
            ra = r.headers.get("Retry-After", "2")
            try:
                wait = float(ra)
            except ValueError:
                wait = 2.0
            logger.warning("TMDB 详情限流 429 id=%s, 等待 %.1fs", tmdb_id, wait)
            await asyncio.sleep(min(wait, 10.0))
            continue

        if r.status_code >= 500:
            logger.warning("TMDB 详情 5xx id=%s status=%s attempt=%s", tmdb_id, r.status_code, attempt)
            if attempt < 4:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            return {"ok": False, "media_type": media_type, "id": tmdb_id}

        if r.status_code == 404:
            return {"ok": False, "media_type": media_type, "id": tmdb_id}

        if r.status_code != 200:
            logger.warning("TMDB 详情 HTTP %s id=%s", r.status_code, tmdb_id)
            return {"ok": False, "media_type": media_type, "id": tmdb_id}

        break
    else:
        return {"ok": False, "media_type": media_type, "id": tmdb_id}

    data = r.json()
    credits = data.get("credits") or {}
    crew = credits.get("crew") or []
    cast = credits.get("cast") or []

    director_names: list[str] = []
    seen_d: set[str] = set()
    for c in crew:
        if c.get("job") == "Director" and c.get("name"):
            n = str(c["name"]).strip()
            if n and n not in seen_d:
                seen_d.add(n)
                director_names.append(n)

    if media_type == "tv":
        for p in data.get("created_by") or []:
            n = (p.get("name") or "").strip()
            if n and n not in seen_d:
                seen_d.add(n)
                director_names.append(n)

    cast_names: list[str] = []
    for c in cast[:cast_limit]:
        n = (c.get("name") or "").strip()
        if n:
            cast_names.append(n)

    title = (data.get("title") or data.get("name") or "").strip()
    release = (data.get("release_date") or data.get("first_air_date") or "").strip()
    overview = (data.get("overview") or "").strip()
    if len(overview) > overview_max:
        overview = overview[: overview_max - 1] + "…"

    pp = data.get("poster_path")
    poster_url = f"{TMDB_IMAGE_W500}{pp}" if pp else None

    # zh-CN 缺海报或简介时，用英文补全
    if (not pp or not overview) and language == "zh-CN":
        try:
            async with httpx.AsyncClient(proxy=proxy, timeout=TMDB_TIMEOUT, verify=False) as client:
                r2 = await client.get(url, params={"api_key": api_key, "language": "en-US", "append_to_response": "credits"})
            if r2.status_code == 200:
                d2 = r2.json()
                if not pp and d2.get("poster_path"):
                    poster_url = f"{TMDB_IMAGE_W500}{d2['poster_path']}"
                if not overview:
                    ov2 = (d2.get("overview") or "").strip()
                    if ov2:
                        overview = ov2 if len(ov2) <= overview_max else ov2[: overview_max - 1] + "…"
                if not title:
                    title = (d2.get("title") or d2.get("name") or "").strip()
                if not director_names:
                    cr2 = (d2.get("credits") or {}).get("crew") or []
                    for c in cr2:
                        if c.get("job") == "Director" and c.get("name"):
                            director_names.append(str(c["name"]).strip())
                if not cast_names:
                    ca2 = (d2.get("credits") or {}).get("cast") or []
                    for c in ca2[:cast_limit]:
                        n = (c.get("name") or "").strip()
                        if n:
                            cast_names.append(n)
        except Exception:
            pass

    return {
        "ok": True,
        "media_type": media_type,
        "id": tmdb_id,
        "poster_url": poster_url,
        "title": title,
        "release_date": release,
        "director_names": director_names,
        "cast_names": cast_names,
        "overview": overview,
    }
