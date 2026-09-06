FROM python:3.12-slim

# ffmpeg — обязателен: без него yt-dlp скачает звук, но не сделает mp3.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Слой с зависимостями отдельно: правка кода не будет пересобирать pip.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

CMD ["python", "main.py"]
