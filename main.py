"""Точка входа. Локально: python main.py — на хостинге то же самое.

Разница только в переменной PORT: если хостинг её задал, поднимаем
крошечный health-эндпоинт рядом с ботом. Он нужен платформе, чтобы
считать сервис живым, и внешнему пингеру, чтобы сервис не засыпал.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys

from aiogram import Bot, Dispatcher
from aiohttp import web

import config
from handlers.audio import router
from services.pot_provider import run_pot_provider, stop_pot_provider

log = logging.getLogger(__name__)


def check_ffmpeg() -> None:
    """Без ffmpeg конвертация в mp3 невозможна — лучше сказать об этом сразу."""
    if shutil.which("ffmpeg") is None:
        raise SystemExit(
            "ffmpeg не найден в PATH, без него не будет mp3.\n"
            "Установи командой:  winget install Gyan.FFmpeg\n"
            "и перезапусти терминал."
        )


async def start_health_server(port: int) -> web.AppRunner:
    """Отдаёт 200 на любой запрос. Больше от него ничего не требуется."""
    app = web.Application()
    app.router.add_get("/", lambda _: web.Response(text="ok"))
    app.router.add_get("/health", lambda _: web.Response(text="ok"))

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info("health-эндпоинт слушает порт %s", port)
    return runner


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    config.validate()
    check_ffmpeg()
    config.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    if config.COOKIES_FILE:
        from pathlib import Path

        found = Path(config.COOKIES_FILE).is_file()
        log.info("cookies: %s (%s)", config.COOKIES_FILE, "найден" if found else "НЕ найден")

    runner = await start_health_server(config.PORT) if config.PORT else None

    # Поднимаем локальный генератор PO-токенов. Если его нет (локально) —
    # просто работаем без него.
    pot_proc = await run_pot_provider()

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    me = await bot.get_me()
    log.info("бот @%s запущен", me.username)

    try:
        # Сбрасываем накопившиеся за простой сообщения: после перезапуска
        # разгребать очередь старых ссылок смысла нет.
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await stop_pot_provider(pot_proc)
        if runner:
            await runner.cleanup()
        shutil.rmtree(config.DOWNLOAD_DIR, ignore_errors=True)


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nостановлен")
