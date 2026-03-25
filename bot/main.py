from __future__ import annotations

import asyncio
import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

from bot.config import Settings
from bot.handlers import attach_whitelist_middleware, router, setup_handlers

LEVEL_EMOJI = {
    logging.DEBUG: "\U0001f41b",      # 🐛
    logging.INFO: "\u2139\ufe0f",     # ℹ️
    logging.WARNING: "\u26a0\ufe0f",  # ⚠️
    logging.ERROR: "\u274c",          # ❌
    logging.CRITICAL: "\U0001f525",   # 🔥
}

LOG_FMT = "%(asctime)s %(emoji)s %(name)s %(message)s"


class EmojiFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.emoji = LEVEL_EMOJI.get(record.levelno, record.levelname)
        return super().format(record)


def _setup_logging() -> None:
    fmt = EmojiFormatter(LOG_FMT)

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(fmt)

    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)
    file_handler = TimedRotatingFileHandler(
        os.path.join(log_dir, "bot.log"),
        when="midnight",
        backupCount=1,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(stdout_handler)
    root.addHandler(file_handler)


_setup_logging()
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = Settings.from_env()
    logger.info(
        "启动 Bot  chats=%s  pan_filter=%s  tmdb=%s  symedia=%s  proxy=%s",
        settings.allowed_chat_ids,
        sorted(settings.pan_types_filter) if settings.pan_types_filter else "无",
        "✔" if settings.tmdb_api_key else "✘",
        "✔" if settings.symedia_base_url else "✘",
        "✔" if settings.http_proxy else "✘",
    )

    session = AiohttpSession(proxy=settings.http_proxy) if settings.http_proxy else None
    bot = Bot(
        settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=session,
    )
    dp = Dispatcher()
    setup_handlers(router, settings)
    attach_whitelist_middleware(dp, settings)
    dp.include_router(router)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
