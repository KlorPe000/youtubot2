"""Точка входа. Запуск: python main.py"""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys

from aiogram import Bot, Dispatcher

import config
from handlers.audio import router


def check_ffmpeg() -> None:
    """Без ffmpeg конвертация в mp3 невозможна — лучше сказать об этом сразу."""
    if shutil.which("ffmpeg") is None:
        raise SystemExit(
            "ffmpeg не найден в PATH, без него не будет mp3.\n"
            "Установи командой:  winget install Gyan.FFmpeg\n"
            "и перезапусти терминал."
        )


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    config.validate()
    check_ffmpeg()
    config.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    me = await bot.get_me()
    logging.info("бот @%s запущен", me.username)

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        # Подчищаем всё, что могло остаться от прерванных загрузок.
        shutil.rmtree(config.DOWNLOAD_DIR, ignore_errors=True)


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nостановлен")
