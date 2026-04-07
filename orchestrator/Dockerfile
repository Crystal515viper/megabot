FROM python:3.11-slim

WORKDIR /app

# Установка системных зависимостей (если нужны для numpy/ta-lib)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Копирование требований
COPY requirements-common.txt .
COPY src/orchestrator/requirements.txt ./requirements.txt

# Установка зависимостей
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода
COPY src/db ./src/db
COPY src/risk ./src/risk
COPY src/core ./src/core
COPY src/orchestrator ./src/orchestrator
COPY config ./config

CMD ["uvicorn", "src.orchestrator.main:app", "--host", "0.0.0.0", "--port", "8000"]