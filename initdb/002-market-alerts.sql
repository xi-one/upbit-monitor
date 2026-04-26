CREATE TABLE IF NOT EXISTS market_alerts (
    id BIGSERIAL PRIMARY KEY,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    market TEXT NOT NULL,
    ratio_5m_vs_1h DOUBLE PRECISION NOT NULL,
    tps_now DOUBLE PRECISION NOT NULL,
    tps_baseline DOUBLE PRECISION NOT NULL,
    price_change_pct DOUBLE PRECISION NOT NULL,
    avg_1h_trade_value DOUBLE PRECISION NOT NULL,
    reason TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_market_alerts_detected_at
ON market_alerts (detected_at DESC);

CREATE INDEX IF NOT EXISTS idx_market_alerts_market_detected_at
ON market_alerts (market, detected_at DESC);
