# Trading System Infrastructure

## Project Structure

```
megabot/
├── docker-compose.yml          # Main Docker Compose configuration
├── .env.example                # Environment variables template
├── .gitignore                  # Git ignore rules
├── requirements.txt            # Root requirements (if needed)
├── requirements-common.txt     # Common dependencies for all services
│
├── orchestrator/               # Main orchestration service
│   ├── Dockerfile
│   ├── app.py
│   └── requirements.txt
│
├── bot_long/                   # Long position trading bot
│   ├── Dockerfile
│   ├── app.py
│   └── requirements.txt
│
├── bot_short/                  # Short position trading bot
│   ├── Dockerfile
│   ├── app.py
│   └── requirements.txt
│
├── api_gateway/                # API Gateway service
│   ├── Dockerfile
│   ├── app.py
│   └── requirements.txt
│
├── src/                        # Shared source code
│   ├── api/                    # API utilities
│   ├── bots/                   # Bot base classes
│   ├── core/                   # Core business logic
│   ├── db/                     # Database models and utilities
│   ├── orchestrator/           # Orchestrator logic
│   ├── risk/                   # Risk management
│   └── telegram_bot/           # Telegram notifications
│
├── alembic/                    # Database migrations
│   ├── versions/
│   └── env.py
├── alembic.ini
│
├── scripts/                    # Utility scripts
│   └── init_db.sh              # Database initialization script
│
├── monitoring/                 # Monitoring stack
│   ├── prometheus/
│   │   └── prometheus.yml
│   └── grafana/
│       └── provisioning/
│           ├── dashboards/
│           └── datasources/
│
├── tests/                      # Test suite
│   └── test_risk.py
│
└── frontend/                   # Web UI (optional)
    └── package.json
```

## Services Overview

| Service | Port | Description |
|---------|------|-------------|
| api_gateway | 8000 | Main API entry point |
| orchestrator | 8001 | Trade coordination and management |
| bot_long | 8002 | Long position trading bot |
| bot_short | 8003 | Short position trading bot |
| postgres | 5432 | PostgreSQL database |
| redis | 6379 | Redis cache and message broker |
| prometheus | 9090 | Metrics collection |
| grafana | 3000 | Visualization and dashboards |

## Quick Start

### 1. Setup Environment Variables

```bash
cp .env.example .env
# Edit .env with your credentials:
# - EXCHANGE_API_KEY / EXCHANGE_API_SECRET
# - TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
# - Secure passwords for DB and Grafana
```

### 2. Start Infrastructure Services

```bash
docker compose up -d postgres redis
```

Wait for databases to be ready:

```bash
docker compose logs -f postgres
# Wait for "database system is ready to accept connections"
```

### 3. Run Database Migrations

```bash
docker compose exec postgres /docker-entrypoint-initdb.d/init_db.sh
# Or run Alembic migrations if using Alembic
```

### 4. Start All Services

```bash
docker compose up -d
```

### 5. Verify Health

```bash
docker compose ps
docker compose logs -f
```

Check individual services:
- API Gateway: http://localhost:8000
- Grafana: http://localhost:3000 (admin/admin_secure_password_here)
- Prometheus: http://localhost:9090

## Network Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     backend_net                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │orchestrator │  │  bot_long   │  │  bot_short  │          │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘          │
│         │                │                │                  │
│         └────────────────┼────────────────┘                  │
│                          │                                   │
│                  ┌───────▼────────┐                          │
│                  │  api_gateway   │ ← Exposed to host        │
│                  └────────────────┘                          │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                       db_net                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │orchestrator │  │  bot_long   │  │  bot_short  │          │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘          │
│         │                │                │                  │
│         └────────────────┼────────────────┘                  │
│                          │                                   │
│                  ┌───────▼────────┐                          │
│                  │    postgres    │ ← Exposed to host        │
│                  └────────────────┘                          │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                   monitoring_net                             │
│  ┌─────────────┐  ┌─────────────┐                           │
│  │ prometheus  │  │   grafana   │ ← Exposed to host         │
│  └──────┬──────┘  └─────────────┘                           │
│         │                                                    │
│         └──────────────────────────────────────────┐         │
│                         │                          │         │
│                  ┌──────▼────────┐                 │         │
│                  │  backend_net  │◄────────────────┘         │
│                  │  (scraping)   │                           │
│                  └───────────────┘                           │
└─────────────────────────────────────────────────────────────┘
```

## Security Notes

- `.env` file is **NOT** committed to git
- All secrets are passed via environment variables
- Database and Redis are isolated in `db_net` and `backend_net`
- Bots have no direct internet access except through defined channels
- Change default passwords before deployment!

## TODO

- [ ] Implement business logic in bot services
- [ ] Add exchange API integration
- [ ] Configure Telegram notifications
- [ ] Set up production-grade secrets management
- [ ] Add comprehensive health checks
- [ ] Configure alerting in Prometheus/Grafana
