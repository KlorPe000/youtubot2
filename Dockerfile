# Этап 1: собираем сервер PO-токенов (bgutil-ytdlp-pot-provider) на Node.
FROM node:22-bookworm-slim AS builder

# canvas собирает native-модуль — нужны инструменты и системные библиотеки.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       python3 build-essential git \
       libcairo2-dev libpango1.0-dev libjpeg-dev libgif-dev librsvg2-dev \
    && rm -rf /var/lib/apt/lists/*

# Кладём сервер провайдера и собираем его TypeScript-исходники.
RUN git clone --depth 1 --branch 1.3.2 \
        https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git \
        /opt/pot-provider \
    && cd /opt/pot-provider/server \
    && npm ci --no-audit --no-fund \
    && npx tsc

# Этап 2: финальный образ — python-бот + node-рантайм + собранный сервер.
FROM node:22-bookworm-slim

# ffmpeg — обязателен для конвертации в mp3; python — для самого бота;
# runtime-библиотеки — для запуска canvas внутри сервера PO-токенов.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ffmpeg ca-certificates \
       python3 python3-pip python3-venv \
       libcairo2 libpango-1.0-0 libjpeg62-turbo libgif7 librsvg2-2 \
       libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Слой с зависимостями отдельно: правка кода не будет пересобирать pip.
COPY requirements.txt .
# Debian bookworm помечает глобальный python как "managed" — работаем в venv.
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

COPY . .

# Забираем собранный сервер PO-токенов из builder-этапа.
COPY --from=builder /opt/pot-provider/server /opt/pot-provider/server

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:${PATH}"

CMD ["python", "main.py"]
