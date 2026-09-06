"""Настройки бота. Всё, что можно покрутить, лежит здесь."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Куда складываем временные файлы. Каждая загрузка получает свою подпапку.
DOWNLOAD_DIR = Path(__file__).parent / "downloads"

# Порт для health-эндпоинта. На хостинге его задаёт платформа, локально его нет
# и веб-сервер не поднимается вообще.
PORT = int(os.getenv("PORT", "0"))

# Файл с cookies YouTube в формате Netscape.
# С серверного IP YouTube часто требует подтверждения "я не робот";
# cookies залогиненного аккаунта это снимают. Локально не нужен.
COOKIES_FILE = os.getenv("COOKIES_FILE", "").strip()

# Telegram не даёт боту отправить файл больше 50 МБ.
# Берём 45 с запасом на метаданные и обложку.
MAX_FILE_MB = 45

# Дольше этого не качаем: час звука в 192 kbps это ~86 МБ, в лимит не влезет.
MAX_DURATION_SEC = 60 * 60

# Основной битрейт и запасной, на который перекодируем, если файл не влез.
PRIMARY_BITRATE = "192"
FALLBACK_BITRATE = "128"

# Сколько загрузок крутим одновременно на весь бот.
MAX_CONCURRENT_DOWNLOADS = 2


def validate() -> None:
    """Падаем сразу и с понятным текстом, а не через десять секунд внутри aiogram."""
    if not BOT_TOKEN:
        raise SystemExit(
            "BOT_TOKEN не задан.\n"
            "Создай файл .env рядом с main.py и впиши строку:\n"
            "BOT_TOKEN=токен_от_BotFather"
        )
