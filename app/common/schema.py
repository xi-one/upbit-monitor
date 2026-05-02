ALERTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS market_alerts (
    id BIGSERIAL PRIMARY KEY,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    market TEXT NOT NULL,
    ratio_5m_vs_1h DOUBLE PRECISION NOT NULL,
    tps_now DOUBLE PRECISION NOT NULL,
    tps_baseline DOUBLE PRECISION NOT NULL,
    price_change_pct DOUBLE PRECISION NOT NULL,
    buy_1s_bid_trade_value DOUBLE PRECISION NOT NULL,
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

ALERTS_RENAME_BUY_VALUE_SQL = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'market_alerts'
          AND column_name = 'avg_1h_trade_value'
    ) AND NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'market_alerts'
          AND column_name = 'buy_1s_bid_trade_value'
    ) THEN
        ALTER TABLE market_alerts
        RENAME COLUMN avg_1h_trade_value TO buy_1s_bid_trade_value;
    END IF;
END $$;
"""

SETTINGS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS detector_settings (
    id BIGSERIAL PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    cooldown_seconds INTEGER NOT NULL DEFAULT 300,
    interval_seconds INTEGER NOT NULL DEFAULT 10,
    webhook_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    webhook_url TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

SETTINGS_ENABLED_SQL = """
ALTER TABLE detector_settings
ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE;
"""

SETTINGS_COOLDOWN_SQL = """
ALTER TABLE detector_settings
ADD COLUMN IF NOT EXISTS cooldown_seconds INTEGER NOT NULL DEFAULT 300;
"""

SETTINGS_INTERVAL_SQL = """
ALTER TABLE detector_settings
ADD COLUMN IF NOT EXISTS interval_seconds INTEGER NOT NULL DEFAULT 10;
"""

SETTINGS_WEBHOOK_ENABLED_SQL = """
ALTER TABLE detector_settings
ADD COLUMN IF NOT EXISTS webhook_enabled BOOLEAN NOT NULL DEFAULT TRUE;
"""

SETTINGS_WEBHOOK_URL_SQL = """
ALTER TABLE detector_settings
ADD COLUMN IF NOT EXISTS webhook_url TEXT NOT NULL DEFAULT '';
"""

RULES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS detector_rules (
    id BIGSERIAL PRIMARY KEY,
    settings_id BIGINT NOT NULL REFERENCES detector_settings(id) ON DELETE CASCADE,
    rule_key TEXT NOT NULL,
    label TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    operator TEXT NOT NULL,
    threshold_value DOUBLE PRECISION NOT NULL,
    params_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    sort_order INTEGER NOT NULL DEFAULT 100,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

RULES_INDEX_SETTINGS_SQL = """
CREATE INDEX IF NOT EXISTS idx_detector_rules_settings_id
ON detector_rules (settings_id, sort_order, id);
"""

RULES_RENAME_BUY_RULE_SQL = """
UPDATE detector_rules
SET
    rule_key = 'buy_1s_bid_trade_value',
    label = '최근 5분 내 1초 최대 매수 거래대금'
WHERE rule_key = 'avg_1h_trade_value';
"""


def ensure_runtime_schema(conn, defaults, default_rules):
    with conn.cursor() as cursor:
        cursor.execute(ALERTS_TABLE_SQL)
        cursor.execute(ALERTS_RENAME_BUY_VALUE_SQL)
        cursor.execute(ALERTS_INDEX_TIME_SQL)
        cursor.execute(ALERTS_INDEX_MARKET_SQL)

        cursor.execute(SETTINGS_TABLE_SQL)
        cursor.execute(SETTINGS_ENABLED_SQL)
        cursor.execute(SETTINGS_COOLDOWN_SQL)
        cursor.execute(SETTINGS_INTERVAL_SQL)
        cursor.execute(SETTINGS_WEBHOOK_ENABLED_SQL)
        cursor.execute(SETTINGS_WEBHOOK_URL_SQL)

        cursor.execute(RULES_TABLE_SQL)
        cursor.execute(RULES_INDEX_SETTINGS_SQL)
        cursor.execute(RULES_RENAME_BUY_RULE_SQL)

        cursor.execute("SELECT id FROM detector_settings ORDER BY updated_at DESC, id DESC LIMIT 1")
        latest_settings_row = cursor.fetchone()

        if latest_settings_row is None:
            cursor.execute(
                """
                INSERT INTO detector_settings (
                    enabled,
                    cooldown_seconds,
                    interval_seconds,
                    webhook_enabled,
                    webhook_url
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    True,
                    defaults.cooldown_seconds,
                    defaults.interval_seconds,
                    True,
                    defaults.webhook_url,
                ),
            )
            latest_settings_id = cursor.fetchone()[0]
        else:
            latest_settings_id = latest_settings_row[0]

        cursor.execute(
            "SELECT 1 FROM detector_rules WHERE settings_id = %s LIMIT 1",
            (latest_settings_id,),
        )
        has_rules = cursor.fetchone() is not None

        if not has_rules:
            for rule in default_rules:
                cursor.execute(
                    """
                    INSERT INTO detector_rules (
                        settings_id,
                        rule_key,
                        label,
                        enabled,
                        operator,
                        threshold_value,
                        params_json,
                        sort_order
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    """,
                    (
                        latest_settings_id,
                        rule["rule_key"],
                        rule["label"],
                        rule["enabled"],
                        rule["operator"],
                        rule["threshold_value"],
                        rule.get("params_json", "{}"),
                        rule["sort_order"],
                    ),
                )
    conn.commit()
