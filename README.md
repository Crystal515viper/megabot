# Distributed Trading System Infrastructure

Базовая инфраструктура для распределённой торговой системы с использованием Docker Compose.

## 📁 Структура проекта

```
.
├── docker-compose.yml          # Основная конфигурация сервисов
├── .env.example                # Шаблон переменных окружения
├── .gitignore                  # Игнорируемые файлы Git
├── README.md                   # Этот файл
│
├── orchestrator/               # Координационный сервис
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app.py
│
├── bot_long/                   # Бот для длинных позиций
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app.py
│
├── bot_short/                  # Бот для коротких позиций
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app.py
│
├── api_gateway/                # API шлюз
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app.py
│
├── scripts/
│   └── init_db.sh              # Скрипт инициализации БД
│
└── monitoring/
    ├── prometheus/
    │   └── prometheus.yml      # Конфигурация Prometheus
    └── grafana/
        └── provisioning/
            ├── datasources/
            │   └── datasources.yml
            └── dashboards/
                └── dashboards.yml
```

## 🚀 Быстрый старт

### 1. Подготовка переменных окружения

```bash
cp .env.example .env
# Отредактируйте .env, указав реальные секреты и credentials
```

### 2. Запуск баз данных

```bash
docker compose up -d postgres redis
```

Проверка подключения:

```bash
# PostgreSQL
docker compose exec postgres psql -U trading_user -d trading_db -c "SELECT 1;"

# Redis
docker compose exec redis redis-cli -a redis_secret ping
```

### 3. Запуск всех сервисов

```bash
docker compose up -d
```

### 4. Проверка статуса

```bash
docker compose ps
docker compose logs -f
```

## 🔌 Доступ к сервисам

| Сервис | Порт | URL |
|--------|------|-----|
| API Gateway | 8000 | http://localhost:8000 |
| Orchestrator | 8001 | http://localhost:8001 |
| Bot Long | 8002 | http://localhost:8002 |
| Bot Short | 8003 | http://localhost:8003 |
| PostgreSQL | 5432 | localhost:5432 |
| Redis | 6379 | localhost:6379 |
| Prometheus | 9090 | http://localhost:9090 |
| Grafana | 3000 | http://localhost:3000 |

**Grafana credentials:** admin / admin (измените в `.env`!)

## 🛡️ Безопасность

- ⚠️ **Никогда не коммитьте `.env` файл!**
- Используйте сложные пароли для production
- Exchange API ключи храните только в environment variables
- Секреты генерируйте через:
  ```bash
  openssl rand -base64 32  # Для JWT secret
  openssl rand -hex 32     # Для encryption key
  ```

## 📊 Мониторинг

### Prometheus
- Автоматический scrape всех сервисов
- Метрики доступны по `/metrics` endpoint
- Конфигурация: `monitoring/prometheus/prometheus.yml`

### Grafana
- Автоматически подключенный datasource Prometheus
- Провизионирование дашбордов через YAML
- Добавляйте дашборды в `monitoring/grafana/provisioning/dashboards/`

## 🔧 Разработка

### Добавление новой миграции БД

```bash
# В контейнере orchestrator
alembic revision --autogenerate -m "Description"
alembic upgrade head
```

### Логи сервисов

```bash
docker compose logs -f orchestrator
docker compose logs -f bot_long
docker compose logs -f api_gateway
```

### Пересборка сервисов

```bash
docker compose build --no-cache
docker compose up -d
```

## 📝 TODO для следующих этапов

- [ ] Реализовать бизнес-логику торговых ботов
- [ ] Добавить интеграцию с биржевым API (ccxt, binance-connector)
- [ ] Настроить Telegram уведомления
- [ ] Добавить аутентификацию в API Gateway
- [ ] Реализовать rate limiting
- [ ] Добавить circuit breaker pattern
- [ ] Создать Grafana дашборды для мониторинга
- [ ] Настроить алертинг в Prometheus/Grafana
- [ ] Добавить unit/integration тесты

## 🆘 Troubleshooting

### Сервис не запускается
```bash
docker compose logs <service_name>
```

### Проблемы с подключением к БД
```bash
docker compose exec postgres pg_isready
docker compose logs postgres
```

### Сброс состояния (удаление volumes)
```bash
docker compose down -v
docker compose up -d
```
