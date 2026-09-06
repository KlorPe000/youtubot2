"""Хендлеры бота: приветствие и обработка ссылок."""

from __future__ import annotations

import asyncio
import logging
import time

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, Message

from config import MAX_CONCURRENT_DOWNLOADS
from services.downloader import DownloadError, download, find_url

log = logging.getLogger(__name__)
router = Router()

# Общий лимит на весь бот: больше двух загрузок разом не тянем.
_slots = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

# Кто прямо сейчас что-то качает — чтобы один человек не занял оба слота.
_busy: set[int] = set()


@router.message(CommandStart())
async def start(message: Message) -> None:
    await message.answer(
        "Пришли ссылку на YouTube — верну mp3.\n\n"
        "Работает с обычными видео, Shorts и YouTube Music."
    )


@router.message(F.text)
async def handle_link(message: Message) -> None:
    url = find_url(message.text)
    if not url:
        await message.answer("Это не похоже на ссылку YouTube. Пришли ссылку на видео.")
        return

    user_id = message.from_user.id
    if user_id in _busy:
        await message.answer("Дождись окончания текущей загрузки.")
        return

    _busy.add(user_id)
    status = await message.answer("Скачиваю…")
    started = time.monotonic()
    track = None

    try:
        async with _slots:
            await status.edit_text("Скачиваю и конвертирую…")
            # yt-dlp синхронный: уводим его в поток, иначе бот перестанет
            # отвечать всем остальным на время загрузки.
            track = await asyncio.to_thread(download, url)

            await status.edit_text("Отправляю…")
            await message.answer_audio(
                FSInputFile(track.path),
                title=track.title,
                performer=track.artist,
                duration=track.duration or None,
            )

        elapsed = time.monotonic() - started
        log.info(
            "user=%s ok url=%s title=%r %.1fs", user_id, url, track.title, elapsed
        )

    except DownloadError as exc:
        # Ожидаемая ошибка: текст уже написан по-человечески.
        log.info("user=%s rejected url=%s reason=%s", user_id, url, exc)
        await message.answer(str(exc))

    except Exception:
        # Всё остальное: пользователю коротко, подробности в лог.
        log.exception("user=%s failed url=%s", user_id, url)
        await message.answer("Что-то пошло не так. Попробуй другую ссылку.")

    finally:
        _busy.discard(user_id)
        if track:
            track.cleanup()
        try:
            await status.delete()
        except Exception:
            pass
