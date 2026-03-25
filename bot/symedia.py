from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

SYMEDIA_TRANSFER_PATH = "/api/v1/plugin/cloud_helper/add_share_urls_115"


async def transfer_to_symedia(
    *,
    share_url: str,
    base_url: str,
    token: str = "symedia",
    parent_id: str = "0",
    timeout: float = 120.0,
) -> tuple[bool, str]:
    """
    POST {base_url}/api/v1/plugin/cloud_helper/add_share_urls_115?token={token}
    Body: {"urls": [share_url], "parent_id": parent_id}

    No explicit proxy — httpx auto-detects from env vars and respects NO_PROXY,
    so LAN Symedia instances are reached directly.
    """
    endpoint = f"{base_url.rstrip('/')}{SYMEDIA_TRANSFER_PATH}"
    params = {"token": token}
    payload = {"urls": [share_url], "parent_id": str(parent_id)}

    logger.info("Symedia 转存请求 → %s  parent_id=%s", endpoint[:120], parent_id)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(
                endpoint,
                params=params,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
    except httpx.TimeoutException:
        logger.warning("Symedia 超时 endpoint=%s", endpoint[:120])
        return False, "Symedia 请求超时（可增大 SYMEDIA_TIMEOUT 或检查服务）"
    except Exception as e:
        logger.exception("Symedia 请求异常")
        return False, f"请求异常: {e!s}"

    # 非 2xx 直接报错（502/503 等常见于 Symedia 服务挂了或 Nginx 反代异常）
    if r.status_code >= 400:
        snippet = (r.text or "")[:200].replace("\n", " ")
        logger.warning("Symedia HTTP %s: %s", r.status_code, snippet[:120])
        return False, f"Symedia 返回 HTTP {r.status_code}，服务可能未启动或异常，请检查 Symedia 状态。"

    ct = (r.headers.get("content-type") or "").lower()
    head = (r.text or "").lstrip()[:500].upper()
    if "text/html" in ct or head.startswith("<!DOCTYPE") or head.startswith("<HTML"):
        return (
            False,
            "HTTP 200 但返回 HTML，API 路径可能有误。"
            "请确认 SYMEDIA_BASE_URL 正确且 Symedia 版本支持 cloud_helper 插件。",
        )

    try:
        body = r.json()
    except Exception:
        snippet = (r.text or "")[:300].replace("\n", " ")
        return False, f"HTTP {r.status_code} 非 JSON：{snippet}"

    if r.status_code == 200 and body.get("success") is True:
        msg = body.get("message") or ""
        if "转存失败" in msg:
            logger.warning("Symedia 业务失败: %s", msg)
            return False, f"Symedia 转存失败：{msg}"
        logger.info("Symedia 转存成功: %s", msg)
        return True, f"Symedia 已受理转存。{msg}"

    err_msg = body.get("message") or body.get("detail") or str(body)
    logger.warning("Symedia HTTP %s: %s", r.status_code, err_msg[:200])
    return False, f"HTTP {r.status_code}：{err_msg}"
