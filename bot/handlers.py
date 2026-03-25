from __future__ import annotations

import asyncio
import html
import logging
from typing import Any

from aiogram import F, Router
from aiogram.exceptions import TelegramRetryAfter
from aiogram.filters import Command, CommandObject
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import Settings
from bot.formatting import (
    filter_resources,
    format_resource_caption,
    resource_deeplink,
)
from bot.hdhive import HDHiveError, fetch_resources, unlock_resource
from bot.symedia import transfer_to_symedia
from bot.tmdb import TMDBError, fetch_media_card, fetch_media_poster, search_multi

logger = logging.getLogger(__name__)

router = Router(name="main")

TG_CAPTION_LIMIT = 1024
FLOOD_SLEEP_SEC = 0.35
# TMDB 详情+credits 并行上限，兼顾速度与 429（可与 tmdb.fetch_media_card 内重试配合）
TMDB_CARD_CONCURRENCY = 3


def _hive_cb(media_type: str, tmdb_id: str) -> str:
    return f"h:{media_type}:{tmdb_id}"


def _symedia_transfer_cb(pan_type: str | None, slug: str) -> str:
    pt = str(pan_type or "x").strip().lower()
    sg = str(slug or "").strip()
    return f"y:{pt}:{sg}"


def _parse_symedia_cb(data: str) -> tuple[str, str] | None:
    if not data.startswith("y:"):
        return None
    parts = data.split(":", 2)
    if len(parts) != 3:
        return None
    _, pan, slug = parts
    if not slug:
        return None
    return pan, slug


def _parse_hive_cb(data: str) -> tuple[str, str] | None:
    if not data.startswith("h:"):
        return None
    parts = data.split(":", 2)
    if len(parts) != 3:
        return None
    _, mt, tid = parts
    if mt not in ("movie", "tv") or not tid.isdigit():
        return None
    return mt, tid


def _build_tmdb_search_caption(card: dict[str, Any], fb: dict[str, Any]) -> str:
    title = (card.get("title") or fb.get("title") or "").strip()
    release = (card.get("release_date") or "").strip()
    if not release:
        y = (fb.get("year") or "").strip()
        if y and y != "?":
            release = f"{y}（仅年份）"
    dirs: list[str] = list(card.get("director_names") or [])
    casts: list[str] = list(card.get("cast_names") or [])
    overview = (card.get("overview") or "").strip()
    tid = fb.get("id") or card.get("id")
    mt = fb.get("media_type") or card.get("media_type")
    kind = "电影" if mt == "movie" else "剧集"

    lines: list[str] = [f"🎬 <b>{html.escape(title)}</b>"]
    if release:
        lines.append(f"📅 上映/首播: {html.escape(release)}")
    if dirs:
        lines.append(f"🎭 导演: {html.escape('、'.join(dirs[:5]))}")
    if casts:
        lines.append(f"👥 主演: {html.escape('、'.join(casts))}")
    if overview:
        lines.append(f"📝 {html.escape(overview)}")
    lines.append(f"🆔 TMDB <code>{html.escape(str(tid))}</code> · {kind}")

    text = "\n".join(lines)
    if len(text) > TG_CAPTION_LIMIT:
        text = text[: TG_CAPTION_LIMIT - 1] + "…"
    return text


async def _answer_photo_retry(
    message: Message,
    photo: str,
    *,
    caption: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    for _ in range(4):
        try:
            await message.answer_photo(
                photo,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )
            return
        except TelegramRetryAfter as e:
            await asyncio.sleep(float(e.retry_after) + 0.5)
    await message.answer_photo(
        photo,
        caption=caption,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
    )


async def _send_hdhive_resource_cards(
    message: Message,
    settings: Settings,
    media_type: str,
    tmdb_id: str,
) -> None:
    try:
        raw = await fetch_resources(
            settings.hdhive_api_key,
            media_type,
            tmdb_id,
            proxy=settings.http_proxy,
        )
    except HDHiveError as e:
        logger.warning("影巢查询失败 %s/%s: %s", media_type, tmdb_id, e)
        await message.answer(f"影巢接口错误: {html.escape(str(e))}")
        return
    except Exception:
        logger.exception("影巢请求异常 %s/%s", media_type, tmdb_id)
        await message.answer("影巢请求失败，请稍后重试。")
        return

    items = filter_resources(raw, settings)
    logger.info("影巢资源 %s/%s: %d 条（过滤后 %d 条）", media_type, tmdb_id, len(raw), len(items))
    pan_hint = "（已全部被 PAN_TYPES 过滤或该片暂无资源）" if settings.pan_types_filter else ""

    if not items:
        await message.answer(f"📭 未找到资源{pan_hint}")
        return

    for r in items:
        cap = format_resource_caption(r)
        url = resource_deeplink(str(r.get("pan_type")), str(r.get("slug")))
        row: list[InlineKeyboardButton] = [
            InlineKeyboardButton(text="打开资源", url=url),
        ]
        if settings.symedia_base_url:
            row.append(
                InlineKeyboardButton(
                    text="转存到115",
                    callback_data=_symedia_transfer_cb(
                        str(r.get("pan_type")),
                        str(r.get("slug") or ""),
                    ),
                )
            )
        kb = InlineKeyboardMarkup(inline_keyboard=[row])
        try:
            await message.answer(
                cap,
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
            )
        except TelegramRetryAfter as e:
            await asyncio.sleep(float(e.retry_after) + 0.5)
            await message.answer(
                cap,
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
            )
        await asyncio.sleep(FLOOD_SLEEP_SEC)


def setup_handlers(r: Router, settings: Settings) -> None:
    @r.message(Command("start"))
    async def cmd_start(message: Message) -> None:
        lines = [
            "影巢资源查询 Bot（框架）",
            "",
            "· 发送片名搜索（需配置 TMDB_API_KEY），每条结果为一张卡片",
            "· 或 /movie &lt;TMDB_ID&gt;、/tv &lt;TMDB_ID&gt;",
            "· 影巢资源卡片可「转存」到 Symedia（需配置 SYMEDIA_*）",
            "· /help 查看说明",
        ]
        await message.answer("\n".join(lines))

    @r.message(Command("help"))
    async def cmd_help(message: Message) -> None:
        tmdb_ok = "已配置" if settings.tmdb_api_key else "未配置（请用 /movie /tv）"
        pans = ", ".join(sorted(settings.pan_types_filter)) if settings.pan_types_filter else "（不过滤）"
        chats = ", ".join(str(c) for c in settings.allowed_chat_ids)
        lines = [
            "<b>命令</b>",
            "/start /help",
            "/movie &lt;id&gt; — 电影 TMDB ID",
            "/tv &lt;id&gt; — 剧集 TMDB ID",
            "",
            f"TMDB: {tmdb_ok}",
            f"PAN_TYPES: {html.escape(pans)}",
            f"授权对话: <code>{html.escape(chats)}</code>",
        ]
        if settings.symedia_base_url:
            lines.append("")
            lines.append(
                f"Symedia: 已配置，影巢卡片可点「转存到115」→ CID <code>{html.escape(settings.symedia_parent_id)}</code>"
            )
        await message.answer("\n".join(lines))

    @r.message(Command("movie"))
    async def cmd_movie(message: Message, command: CommandObject) -> None:
        arg = (command.args or "").strip()
        if not arg.isdigit():
            await message.answer("用法: <code>/movie &lt;TMDB_ID&gt;</code>")
            return
        await _send_hdhive_resource_cards(message, settings, "movie", arg)

    @r.message(Command("tv"))
    async def cmd_tv(message: Message, command: CommandObject) -> None:
        arg = (command.args or "").strip()
        if not arg.isdigit():
            await message.answer("用法: <code>/tv &lt;TMDB_ID&gt;</code>")
            return
        await _send_hdhive_resource_cards(message, settings, "tv", arg)

    @r.callback_query(F.data.startswith("y:"))
    async def cb_symedia_transfer(query: CallbackQuery) -> None:
        if not settings.symedia_base_url:
            await query.answer("未配置 SYMEDIA_BASE_URL")
            return
        parsed = _parse_symedia_cb(query.data or "")
        if not parsed:
            await query.answer("无效操作")
            return
        _pan, slug = parsed
        logger.info("转存请求 slug=%s user=%s", slug, query.from_user.id)
        await query.answer("正在解锁并转存…")

        async def _reply(text: str) -> None:
            if query.message:
                await query.message.answer(text, parse_mode=ParseMode.HTML)
            else:
                await query.bot.send_message(query.from_user.id, text, parse_mode=ParseMode.HTML)

        try:
            unlock_data = await unlock_resource(
                settings.hdhive_api_key, slug, proxy=settings.http_proxy,
            )
        except HDHiveError as e:
            logger.warning("解锁失败 slug=%s: %s", slug, e)
            await _reply(f"❌ 影巢解锁失败：{html.escape(str(e))}")
            return
        except Exception:
            logger.exception("解锁异常 slug=%s", slug)
            await _reply("❌ 影巢解锁请求异常，请稍后重试。")
            return

        share_url = unlock_data.get("full_url") or unlock_data.get("url") or ""
        if not share_url:
            await _reply("❌ 解锁成功但未返回分享链接，无法转存。")
            return

        ok, detail = await transfer_to_symedia(
            share_url=share_url,
            base_url=settings.symedia_base_url,
            token=settings.symedia_token,
            parent_id=settings.symedia_parent_id,
            proxy=settings.http_proxy,
            timeout=settings.symedia_timeout,
        )
        icon = "✅" if ok else "❌"
        logger.info("转存结果 slug=%s ok=%s: %s", slug, ok, detail[:120])
        await _reply(f"{icon} {html.escape(detail)}")

    @r.callback_query(F.data.startswith("h:"))
    async def cb_hive_search(query: CallbackQuery) -> None:
        parsed = _parse_hive_cb(query.data or "")
        if not parsed or not query.message:
            await query.answer("无效操作")
            return
        mt, tid = parsed
        await query.answer("正在查询影巢…")
        await _send_hdhive_resource_cards(query.message, settings, mt, tid)

    @r.message(F.text & ~F.text.startswith("/"))
    async def on_text_search(message: Message) -> None:
        if not settings.tmdb_api_key:
            await message.answer("未配置 TMDB_API_KEY，请使用 /movie 或 /tv 加 TMDB ID。")
            return
        q = (message.text or "").strip()
        if not q:
            return
        logger.info("TMDB 搜索 query=%r user=%s", q, message.from_user.id if message.from_user else "?")
        await message.answer("正在搜索 TMDB…")
        try:
            results: list[dict[str, Any]] = await search_multi(
                settings.tmdb_api_key,
                q,
                proxy=settings.http_proxy,
            )
        except TMDBError as e:
            logger.warning("TMDB 搜索失败 query=%r: %s", q, e)
            await message.answer(f"TMDB 错误: {html.escape(str(e))}")
            return
        except Exception:
            logger.exception("TMDB 搜索异常 query=%r", q)
            await message.answer("TMDB 请求失败。")
            return
        logger.info("TMDB 搜索结果 query=%r: %d 条", q, len(results))
        if not results:
            await message.answer("TMDB 无匹配结果，换关键词或直接用 /movie /tv。")
            return

        sem = asyncio.Semaphore(TMDB_CARD_CONCURRENCY)

        async def _fetch_card(item: dict[str, Any]) -> dict[str, Any]:
            async with sem:
                return await fetch_media_card(
                    settings.tmdb_api_key,
                    item["media_type"],
                    str(item["id"]),
                    proxy=settings.http_proxy,
                )

        cards: list[dict[str, Any]] = list(
            await asyncio.gather(*[_fetch_card(item) for item in results])
        )

        for item, card in zip(results, cards, strict=True):
            fb = {
                "id": item["id"],
                "media_type": item["media_type"],
                "title": item.get("title") or "",
                "year": item.get("year") or "?",
            }
            caption = _build_tmdb_search_caption(card, fb)
            poster = card.get("poster_url") if card.get("ok") else None
            if poster is None and settings.tmdb_api_key:
                pu, _ = await fetch_media_poster(
                    settings.tmdb_api_key,
                    item["media_type"],
                    str(item["id"]),
                    proxy=settings.http_proxy,
                )
                poster = pu
            cb = _hive_cb(item["media_type"], str(item["id"]))
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="搜索影巢", callback_data=cb)],
                ]
            )
            if poster:
                await _answer_photo_retry(message, poster, caption=caption, reply_markup=kb)
            else:
                try:
                    await message.answer(
                        caption,
                        parse_mode=ParseMode.HTML,
                        reply_markup=kb,
                    )
                except TelegramRetryAfter as e:
                    await asyncio.sleep(float(e.retry_after) + 0.5)
                    await message.answer(
                        caption,
                        parse_mode=ParseMode.HTML,
                        reply_markup=kb,
                    )
            await asyncio.sleep(FLOOD_SLEEP_SEC)


def attach_whitelist_middleware(dp, settings: Settings) -> None:
    from aiogram import BaseMiddleware
    from aiogram.types import CallbackQuery, Message, TelegramObject

    class WhitelistMiddleware(BaseMiddleware):
        async def __call__(self, handler, event: TelegramObject, data: dict):
            chat_id = None
            if isinstance(event, Message):
                chat_id = event.chat.id
            elif isinstance(event, CallbackQuery) and event.message:
                chat_id = event.message.chat.id
            if chat_id is None or chat_id not in settings.allowed_chat_ids:
                if isinstance(event, Message):
                    logger.warning("拒绝未授权 chat_id=%s", chat_id)
                return None
            return await handler(event, data)

    dp.message.middleware(WhitelistMiddleware())
    dp.callback_query.middleware(WhitelistMiddleware())
