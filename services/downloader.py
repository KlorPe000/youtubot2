"""Скачивание видео с YouTube и конвертация в mp3.

Модуль намеренно ничего не знает про Telegram и aiogram: на вход ссылка,
на выходе готовый файл или понятная ошибка. Так его можно тестировать
отдельно от бота, что мы и делаем в блоке __main__ внизу.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

import yt_dlp

from config import (
    COOKIES_FILE,
    DOWNLOAD_DIR,
    FALLBACK_BITRATE,
    MAX_DURATION_SEC,
    MAX_FILE_MB,
    PRIMARY_BITRATE,
)

log = logging.getLogger(__name__)


def _auth_opts() -> dict:
    """Cookies и форсированный IPv4 — то, что нужно только на сервере.

    С домашнего IP YouTube отдаёт видео без вопросов. С серверного часто
    требует подтверждения, что ты не бот, и cookies залогиненного аккаунта
    это снимают. Локально файла нет и опции просто не добавляются.
    """
    opts: dict = {}
    if COOKIES_FILE and Path(COOKIES_FILE).is_file():
        opts["cookiefile"] = COOKIES_FILE
        # На серверах IPv6 чаще попадает в чёрные списки, чем IPv4.
        opts["source_address"] = "0.0.0.0"
    return opts


YOUTUBE_URL_RE = re.compile(
    r"https?://(?:www\.|m\.|music\.)?"
    r"(?:youtube\.com/(?:watch\?\S*v=|shorts/|live/|embed/)|youtu\.be/)"
    r"[\w-]{11}",
    re.IGNORECASE,
)


class DownloadError(Exception):
    """Ошибка, текст которой можно показать пользователю как есть."""


@dataclass(slots=True)
class Track:
    path: Path
    title: str
    artist: str
    duration: int
    workdir: Path

    def cleanup(self) -> None:
        shutil.rmtree(self.workdir, ignore_errors=True)


def find_url(text: str) -> str | None:
    """Достаёт ссылку на YouTube из текста сообщения."""
    match = YOUTUBE_URL_RE.search(text or "")
    return match.group(0) if match else None


def _probe(url: str) -> dict:
    """Смотрим метаданные не скачивая — чтобы отсеять длинное до загрузки."""
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True}
    opts.update(_auth_opts())
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        log.warning("probe failed for %s: %s", url, exc)
        raise DownloadError(
            "Не получилось открыть видео: оно приватное, удалено "
            "или недоступно в этом регионе."
        ) from exc


def _human_duration(seconds: int) -> str:
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{sec:02d}" if hours else f"{minutes}:{sec:02d}"


def _shrink(path: Path, bitrate: str) -> Path:
    """Перекодируем в битрейт пониже, если файл не влезает в лимит Telegram."""
    target = path.with_name(f"{path.stem}_{bitrate}.mp3")
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(path),
            "-map", "0:a", "-map", "0:v?", "-c:v", "copy",
            "-b:a", f"{bitrate}k",
            "-map_metadata", "0",
            str(target),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not target.exists():
        log.error("ffmpeg re-encode failed: %s", result.stderr.strip())
        raise DownloadError("Не удалось сжать файл до размера, который принимает Telegram.")
    path.unlink(missing_ok=True)
    return target


def download(url: str) -> Track:
    """Качает аудио и возвращает готовый mp3. Блокирующая функция.

    Вызывать только через asyncio.to_thread, иначе бот встанет колом
    на всё время загрузки.
    """
    info = _probe(url)

    duration = int(info.get("duration") or 0)
    if duration > MAX_DURATION_SEC:
        raise DownloadError(
            f"Ролик слишком длинный — {_human_duration(duration)}. "
            f"Telegram не даёт ботам отправлять файлы больше 50 МБ, "
            f"а это примерно {_human_duration(MAX_DURATION_SEC)} звука."
        )
    if info.get("is_live"):
        raise DownloadError("Это прямой эфир, его нельзя скачать.")

    workdir = DOWNLOAD_DIR / uuid.uuid4().hex
    workdir.mkdir(parents=True, exist_ok=True)

    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(workdir / "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "writethumbnail": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": PRIMARY_BITRATE,
            },
            {"key": "FFmpegMetadata", "add_metadata": True},
            {"key": "EmbedThumbnail", "already_have_thumbnail": False},
        ],
    }
    opts.update(_auth_opts())

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        log.warning("download failed for %s: %s", url, exc)
        raise DownloadError(
            "Не получилось скачать. Видео может быть недоступным "
            "или требовать авторизации."
        ) from exc

    files = list(workdir.glob("*.mp3"))
    if not files:
        shutil.rmtree(workdir, ignore_errors=True)
        raise DownloadError("Конвертация не удалась — mp3 не появился. Проверь, что установлен ffmpeg.")

    audio = files[0]
    size_mb = audio.stat().st_size / 1024 / 1024

    if size_mb > MAX_FILE_MB:
        log.info("file is %.1f MB, re-encoding to %s kbps", size_mb, FALLBACK_BITRATE)
        try:
            audio = _shrink(audio, FALLBACK_BITRATE)
        except DownloadError:
            shutil.rmtree(workdir, ignore_errors=True)
            raise
        size_mb = audio.stat().st_size / 1024 / 1024
        if size_mb > MAX_FILE_MB:
            shutil.rmtree(workdir, ignore_errors=True)
            raise DownloadError(
                f"Даже сжатый файл весит {size_mb:.0f} МБ — Telegram столько не пропустит."
            )

    return Track(
        path=audio,
        title=info.get("title") or "audio",
        artist=info.get("uploader") or info.get("channel") or "YouTube",
        duration=duration,
        workdir=workdir,
    )


if __name__ == "__main__":
    # Ручная проверка без Telegram: python -m services.downloader <ссылка>
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    link = sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com/watch?v=BaW_jenozKc"
    track = download(link)
    mb = track.path.stat().st_size / 1024 / 1024
    print(f"OK: {track.artist} - {track.title} | {_human_duration(track.duration)} | {mb:.1f} MB")
    print(f"файл: {track.path}")
