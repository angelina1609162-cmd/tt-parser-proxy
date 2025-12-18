FROM python:3.11-slim

# Настройка таймзоны (Москва), чтобы "Сегодня" определялось корректно
ENV TZ=Europe/Moscow
RUN apt-get update && apt-get install -y \
    wget curl gnupg tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Установка Python-зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Установка Playwright и браузеров
RUN playwright install chromium
RUN playwright install-deps

# Копируем код проекта
COPY . .

# Создаем директорию для логов
RUN mkdir -p logs

# Порт для FastAPI
EXPOSE 8000

# Запуск сервера
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
