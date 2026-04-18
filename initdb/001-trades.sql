CREATE TABLE IF NOT EXISTS trades (
    time TIMESTAMPTZ NOT NULL,
    market TEXT NOT NULL,
    price DOUBLE PRECISION NOT NULL,
    volume DOUBLE PRECISION NOT NULL,
    trade_value DOUBLE PRECISION NOT NULL,
    side TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trades_time_market
ON trades (time DESC, market);

CREATE INDEX IF NOT EXISTS idx_trades_time_side_market
ON trades (time DESC, side, market);

SELECT create_hypertable('trades', 'time', if_not_exists => TRUE);
