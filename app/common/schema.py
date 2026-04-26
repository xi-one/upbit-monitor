ALERTS_TABLE_SQL = """
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
"""

ALERTS_INDEX_TIME_SQL = """
CREATE INDEX IF NOT EXISTS idx_market_alerts_detected_at
ON market_alerts (detected_at DESC);
"""

ALERTS_INDEX_MARKET_SQL = """
CREATE INDEX IF NOT EXISTS idx_market_alerts_market_detected_at
ON market_alerts (market, detected_at DESC);
"""

SETTINGS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS detector_settings (
    id BIGSERIAL PRIMARY KEY,
    ratio_5m_vs_1h DOUBLE PRECISION NOT NULL,
    tps_multiplier DOUBLE PRECISION NOT NULL,
    price_change_pct_max DOUBLE PRECISION NOT NULL,
    avg_1h_trade_value_min DOUBLE PRECISION NOT NULL,
    cooldown_seconds INTEGER NOT NULL,
    interval_seconds INTEGER NOT NULL,
    webhook_url TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def ensure_runtime_schema(conn, defaults):
    with conn.cursor() as cursor:
        cursor.execute(ALERTS_TABLE_SQL)
        cursor.execute(ALERTS_INDEX_TIME_SQL)
        cursor.execute(ALERTS_INDEX_MARKET_SQL)
        cursor.execute(SETTINGS_TABLE_SQL)
        cursor.execute("SELECT 1 FROM detector_settings LIMIT 1")
        has_settings = cursor.fetchone() is not None
        if not has_settings:
            cursor.execute(
                """
                INSERT INTO detector_settings (
                    ratio_5m_vs_1h,
                    tps_multiplier,
                    price_change_pct_max,
                    avg_1h_trade_value_min,
                    cooldown_seconds,
                    interval_seconds,
                    webhook_url
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    defaults.ratio_5m_vs_1h,
                    defaults.tps_multiplier,
                    defaults.price_change_pct_max,
                    defaults.avg_1h_trade_value_min,
                    defaults.cooldown_seconds,
                    defaults.interval_seconds,
                    defaults.webhook_url,
                ),
            )
    conn.commit()
