#!/bin/bash
set -e

echo "=== Running Database Initialization ==="

# Wait for PostgreSQL to be ready
until pg_isready -h localhost -U "${POSTGRES_USER:-trading_user}" -d "${POSTGRES_DB:-trading_db}"; do
    echo "Waiting for PostgreSQL..."
    sleep 2
done

echo "PostgreSQL is ready!"

# Create extensions if needed
psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER:-trading_user}" --dbname "${POSTGRES_DB:-trading_db}" <<-EOSQL
    -- Enable UUID extension
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
    
    -- Create schema for trading system
    CREATE SCHEMA IF NOT EXISTS trading;
    
    -- TODO: Add initial tables here or run Alembic migrations
    -- Example base table structure:
    /*
    CREATE TABLE IF NOT EXISTS trading.positions (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        symbol VARCHAR(20) NOT NULL,
        side VARCHAR(10) NOT NULL CHECK (side IN ('LONG', 'SHORT')),
        entry_price DECIMAL(20, 8) NOT NULL,
        quantity DECIMAL(20, 8) NOT NULL,
        status VARCHAR(20) DEFAULT 'OPEN',
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE TABLE IF NOT EXISTS trading.orders (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        position_id UUID REFERENCES trading.positions(id),
        order_type VARCHAR(20) NOT NULL,
        price DECIMAL(20, 8),
        quantity DECIMAL(20, 8) NOT NULL,
        status VARCHAR(20) DEFAULT 'PENDING',
        exchange_order_id VARCHAR(100),
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE INDEX idx_positions_symbol ON trading.positions(symbol);
    CREATE INDEX idx_positions_status ON trading.positions(status);
    CREATE INDEX idx_orders_position_id ON trading.orders(position_id);
    CREATE INDEX idx_orders_status ON trading.orders(status);
    */
EOSQL

echo "=== Database initialization completed ==="