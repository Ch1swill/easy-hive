from __future__ import annotations

import html
from typing import Any

from bot.config import Settings, pan_type_allowed

TG_CAPTION_SAFE = 1024
# 纯文字消息（无配图）可用更长正文
TG_TEXT_SAFE = 3800


def resource_deeplink(pan_type: str | None, slug: str | None) -> str:
    pt = (pan_type or "unknown").strip().lower()
    sg = (slug or "").strip()
    return f"https://hdhive.com/resource/{pt}/{sg}"


def format_link_status_brief(validate_status: Any, validate_message: Any) -> str:
    """影巢 validate_status：有效 → ✅，异常/失败 → ❌ 疑似失效。"""
    s = str(validate_status or "").strip().lower()
    msg = str(validate_message or "").strip()
    if len(msg) > 120:
        msg = msg[:117] + "…"
    msg_esc = html.escape(msg) if msg else ""

    if s == "valid":
        return "✅ 有效"
    if s in ("error", "invalid", "failed", "expired"):
        return "❌ 疑似失效" + (f"（{msg_esc}）" if msg_esc else "")
    if not s:
        return "❔ 未检测"
    return f"❔ {html.escape(s)}" + (f"（{msg_esc}）" if msg_esc else "")


def format_resource_line(r: dict[str, Any]) -> str:
    title = html.escape(str(r.get("title") or ""))
    slug = r.get("slug") or ""
    pan = r.get("pan_type")
    share_url = resource_deeplink(str(pan) if pan else None, slug)
    share_href = html.escape(share_url, quote=True)
    size = html.escape(str(r.get("share_size") or "").strip())
    res = r.get("video_resolution") or []
    src = r.get("source") or []
    sub_lang = r.get("subtitle_language") or []
    sub_type = r.get("subtitle_type") or []
    remark = html.escape(str(r.get("remark") or ""))
    points = r.get("unlock_points")
    unlocked = r.get("is_unlocked")
    vstat = r.get("validate_status")
    vmsg_raw = r.get("validate_message")
    vat = r.get("last_validated_at")
    user = r.get("user") or {}
    nick = html.escape(str(user.get("nickname") or ""))
    created = r.get("created_at")

    lines = [
        f"🎬 <b>{title}</b>",
        f"🔗 分享链接: <code>{share_href}</code>",
        f"💾 体积: {size}" if size else "💾 体积: —",
        f"📺 分辨率: {html.escape(', '.join(str(x) for x in res))}" if res else "📺 分辨率: —",
        f"🎞️ 片源: {html.escape(', '.join(str(x) for x in src))}" if src else "🎞️ 片源: —",
        f"🗣️ 字幕语言: {html.escape(', '.join(str(x) for x in sub_lang))}"
        if sub_lang
        else "🗣️ 字幕语言: —",
        f"📄 字幕类型: {html.escape(', '.join(str(x) for x in sub_type))}"
        if sub_type
        else "📄 字幕类型: —",
    ]
    if remark:
        lines.append(f"📌 备注: {remark}")
    if points is None:
        lines.append("🪙 积分: 免费/未标")
    else:
        lines.append(f"🪙 积分: {points}")
    lines.append(f"🔓 已解锁: {unlocked}")
    lines.append(f"📶 {format_link_status_brief(vstat, vmsg_raw)}")
    if vat:
        lines.append(f"🕐 最近检测: {html.escape(str(vat))}")
    if nick:
        lines.append(f"👤 分享者: {nick}")
    if created:
        lines.append(f"📅 创建: {html.escape(str(created))}")

    return "\n".join(lines)


def format_resource_caption(r: dict[str, Any], limit: int = TG_TEXT_SAFE) -> str:
    """单条影巢资源说明；默认按纯文字消息长度截断。"""
    text = format_resource_line(r)
    if len(text) <= limit:
        return text
    slim = {**r, "remark": None, "validate_message": None}
    text = format_resource_line(slim)
    if len(text) <= limit:
        return text
    slim2 = {**slim, "subtitle_language": [], "subtitle_type": []}
    text = format_resource_line(slim2)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 8)] + "\n…(截断)"


def filter_resources(items: list[dict[str, Any]], settings: Settings) -> list[dict[str, Any]]:
    if not settings.pan_types_filter:
        return list(items)
    return [r for r in items if pan_type_allowed(str(r.get("pan_type") or ""), settings)]
