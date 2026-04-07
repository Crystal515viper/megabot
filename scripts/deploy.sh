#!/bin/bash
set -e

echo "🚀 Starting deployment..."

# Configuration
COMPOSE_FILE="docker-compose.yml"
PROJECT_NAME="megabot"
HEALTHCHECK_RETRIES=5
HEALTHCHECK_INTERVAL=10

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if .env exists
if [ ! -f .env ]; then
    log_error ".env file not found! Please create it from .env.example"
    exit 1
fi

# Pull latest images (optional, uncomment if using remote registry)
# log_info "Pulling latest images..."
# docker compose -f $COMPOSE_FILE -p $PROJECT_NAME pull

# Run database migrations
log_info "Running database migrations..."
docker compose -f $COMPOSE_FILE -p $PROJECT_NAME run --rm orchestrator python -m alembic upgrade head || {
    log_error "Database migration failed!"
    exit 1
}

# Deploy services
log_info "Deploying services..."
docker compose -f $COMPOSE_FILE -p $PROJECT_NAME up -d

# Wait for services to be ready
log_info "Waiting for services to start..."
sleep 10

# Healthcheck function
check_health() {
    local service=$1
    local url=$2
    
    log_info "Checking health of $service at $url"
    
    for i in $(seq 1 $HEALTHCHECK_RETRIES); do
        if curl -sf "$url" > /dev/null 2>&1; then
            log_info "$service is healthy!"
            return 0
        fi
        
        if [ $i -lt $HEALTHCHECK_RETRIES ]; then
            log_warn "$service not ready yet, retrying in ${HEALTHCHECK_INTERVAL}s... ($i/$HEALTHCHECK_RETRIES)"
            sleep $HEALTHCHECK_INTERVAL
        fi
    done
    
    log_error "$service failed healthcheck after $HEALTHCHECK_RETRIES attempts"
    return 1
}

# Perform healthchecks
DEPLOYMENT_SUCCESS=true

# Check API Gateway
if ! check_health "API Gateway" "http://localhost:8000/health"; then
    DEPLOYMENT_SUCCESS=false
fi

# Check Orchestrator
if ! check_health "Orchestrator" "http://localhost:8001/health"; then
    DEPLOYMENT_SUCCESS=false
fi

# Check Prometheus
if ! check_health "Prometheus" "http://localhost:9090/-/healthy"; then
    log_warn "Prometheus healthcheck skipped (endpoint may vary)"
fi

# Check Grafana
if ! check_health "Grafana" "http://localhost:3000/api/health"; then
    log_warn "Grafana healthcheck skipped (may need authentication)"
fi

# Show status
log_info "Deployment status:"
docker compose -f $COMPOSE_FILE -p $PROJECT_NAME ps

if [ "$DEPLOYMENT_SUCCESS" = true ]; then
    log_info "✅ Deployment completed successfully!"
    echo ""
    echo "Services available at:"
    echo "  - API Gateway: http://localhost:8000"
    echo "  - Grafana: http://localhost:3000 (admin/admin)"
    echo "  - Prometheus: http://localhost:9090"
else
    log_error "❌ Deployment completed with errors. Check logs with: docker compose logs"
    exit 1
fi
