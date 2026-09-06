""""Запуск HTTP-сервера генератора PO-токенов (bgutil-ytdlp-pot-provider).

Сервер написан на Node.js и генерирует proof-of-origin токен, который yt-dlp
предъявляет YouTube, чтобы пройти проверку "Sign in to confirm you're not a bot"
с серверных IP. Живёт в том же контейнере, что и бот. Заметка: сам сервер
в версии 1.3.2 слушает и loopback, и внешние интерфейсы (это зашито в его код),
но Render не маршрутизирует в него трафик извне — наружу доступен только
health-эндпоинт на PORT.

Модуль намеренно изолирован: он умеет лишь поднять процесс, дождаться
готовности и корректно погасить его вместе с ботом.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import urllib.request
from pathlib import Path

from config import POT_ENABLED, POT_PROVIDER_URL, POT_SERVER_CMD

log = logging.getLogger(__name__)


class PotProviderError(Exception):
    """Не удалось поднять или проверить сервер PO-токенов."""


def _wait_for_server(url: str, timeout: float = 30.0) -> None:
    """Ждём, пока сервер начнёт отвечать на GET /ping."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/ping", timeout=2) as resp:
                if resp.status == 200:
                    return
        except Exception:
            pass
        time.sleep(0.2)
    raise PotProviderError(f"сервер PO-токенов не ответил на {url}/ping за {timeout:.0f}s")


async def run_pot_provider() -> asyncio.subprocess.Process | None:
    """Запускает Node-сервер PO-токенов и ждёт, пока он поднимется.

    Возвращает None, если PO-токены отключены или сервер ставить негде.
    Вызывать только в async-контексте.
    """
    if not POT_ENABLED:
        log.info("PO-токены отключены, сервер не запускается")
        return None

    script = Path(POT_SERVER_CMD)
    if not script.is_file():
        # Локально без собранного сервера всё равно можно гонять бота —
        # просто капча будет как раньше (или её не будет с домашнего IP).
        log.warning(
            "сервер PO-токенов не найден (%s), PO-токены не активны", script
        )
        return None

    if shutil.which("node") is None:
        log.warning("node не найден в PATH, PO-токены не активны")
        return None

    proc = await asyncio.create_subprocess_exec(
        "node",
        script.name,
        cwd=str(script.parent),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        # Ждём до 30 секунд, но выходим раньше, если процесс уже умер —
        # подвешенный на 30с контейнер при каждом рестарте не нужен.
        for _ in range(60):
            if proc.returncode is not None:
                stderr = await proc.stderr.read() if proc.stderr else b""
                raise PotProviderError(
                    f"сервер PO-токенов завершился сразу (код {proc.returncode}): "
                    f"{stderr.decode(errors='replace')[:500]}"
                )
            await asyncio.sleep(0.2)
            try:
                await asyncio.to_thread(_wait_for_server, POT_PROVIDER_URL, timeout=1.0)
                break
            except PotProviderError:
                continue
        else:
            raise PotProviderError(
                f"сервер PO-токенов не ответил на {POT_PROVIDER_URL}/ping за 30s"
            )
    except PotProviderError:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except (asyncio.TimeoutError, ProcessLookupError):
                proc.kill()
                await proc.wait()
        raise
    log.info("сервер PO-токенов поднят (%s)", POT_PROVIDER_URL)
    return proc


async def stop_pot_provider(proc: asyncio.subprocess.Process | None) -> None:
    """Корректно гасит сервер PO-токенов, если он запускался."""
    if proc is None:
        return
    if proc.returncode is None:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()