from app.detector.rules import STRATEGY_DEFINITIONS, build_default_strategy_bundle

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

ALERTS_STRATEGY_ID_SQL = """
ALTER TABLE market_alerts
ADD COLUMN IF NOT EXISTS strategy_id BIGINT NULL;
"""

ALERTS_STRATEGY_KEY_SQL = """
ALTER TABLE market_alerts
ADD COLUMN IF NOT EXISTS strategy_key TEXT NOT NULL DEFAULT 'spike';
"""

ALERTS_DETAILS_JSON_SQL = """
ALTER TABLE market_alerts
ADD COLUMN IF NOT EXISTS details_json JSONB NOT NULL DEFAULT '{}'::jsonb;
"""

ALERTS_INDEX_TIME_SQL = """
CREATE INDEX IF NOT EXISTS idx_market_alerts_detected_at
ON market_alerts (detected_at DESC);
"""

ALERTS_INDEX_MARKET_SQL = """
CREATE INDEX IF NOT EXISTS idx_market_alerts_market_detected_at
ON market_alerts (market, detected_at DESC);
"""

ALERTS_INDEX_STRATEGY_SQL = """
CREATE INDEX IF NOT EXISTS idx_market_alerts_strategy_detected_at
ON market_alerts (strategy_key, detected_at DESC);
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

RULES_RENAME_TPS_RULE_SQL = """
UPDATE detector_rules
SET
    rule_key = 'tps_ratio',
    label = 'TPS 증가 배수'
WHERE rule_key = 'tps_multiplier';
"""

STRATEGIES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS alert_strategies (
    id BIGSERIAL PRIMARY KEY,
    strategy_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    cooldown_seconds INTEGER NOT NULL DEFAULT 300,
    interval_seconds INTEGER NOT NULL DEFAULT 10,
    webhook_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    webhook_url TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

STRATEGY_RULES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS alert_strategy_rules (
    id BIGSERIAL PRIMARY KEY,
    strategy_id BIGINT NOT NULL REFERENCES alert_strategies(id) ON DELETE CASCADE,
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

STRATEGY_RULES_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_alert_strategy_rules_strategy_id
ON alert_strategy_rules (strategy_id, sort_order, id);
"""

MONITORED_MARKETS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS monitored_markets (
    market TEXT PRIMARY KEY,
    korean_name TEXT NOT NULL,
    english_name TEXT NOT NULL,
    symbol TEXT NOT NULL,
    market_cap_krw DOUBLE PRECISION NULL,
    market_cap_source TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

MONITORED_MARKETS_SYMBOL_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_monitored_markets_symbol
ON monitored_markets (symbol);
"""

MARKET_SYNC_STATUS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS market_sync_status (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    last_refreshed_at TIMESTAMPTZ NULL,
    market_count INTEGER NOT NULL DEFAULT 0,
    refresh_version BIGINT NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

MARKET_SYNC_STATUS_SEED_SQL = """
INSERT INTO market_sync_status (id, market_count, refresh_version, last_error)
VALUES (1, 0, 0, '')
ON CONFLICT (id) DO NOTHING;
"""

BOT_DETECTION_STATUS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS bot_detection_status (
    market TEXT PRIMARY KEY,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    first_detected_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    last_detected_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
    cleared_at TIMESTAMPTZ NULL,
    buy_sell_pair_count DOUBLE PRECISION NOT NULL DEFAULT 0,
    tps DOUBLE PRECISION NOT NULL DEFAULT 0,
    price_range_pct DOUBLE PRECISION NULL,
    price_increase_pct DOUBLE PRECISION NULL,
    total_trade_value DOUBLE PRECISION NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '',
    metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb
);
"""

BOT_DETECTION_STATUS_ACTIVE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_bot_detection_status_active_last_detected
ON bot_detection_status (active, last_detected_at DESC);
"""


def ensure_market_sync_schema(conn):
    with conn.cursor() as cursor:
        cursor.execute(MONITORED_MARKETS_TABLE_SQL)
        cursor.execute(MONITORED_MARKETS_SYMBOL_INDEX_SQL)
        cursor.execute(MARKET_SYNC_STATUS_TABLE_SQL)
        cursor.execute(MARKET_SYNC_STATUS_SEED_SQL)
    conn.commit()


def _ensure_legacy_detector_schema(cursor):
    cursor.execute(SETTINGS_TABLE_SQL)
    cursor.execute(SETTINGS_ENABLED_SQL)
    cursor.execute(SETTINGS_COOLDOWN_SQL)
    cursor.execute(SETTINGS_INTERVAL_SQL)
    cursor.execute(SETTINGS_WEBHOOK_ENABLED_SQL)
    cursor.execute(SETTINGS_WEBHOOK_URL_SQL)

    cursor.execute(RULES_TABLE_SQL)
    cursor.execute(RULES_INDEX_SETTINGS_SQL)
    cursor.execute(RULES_RENAME_BUY_RULE_SQL)
    cursor.execute(RULES_RENAME_TPS_RULE_SQL)


def _seed_strategy_if_missing(cursor, strategy_key: str, bundle: dict):
    cursor.execute("SELECT id FROM alert_strategies WHERE strategy_key = %s", (strategy_key,))
    existing_row = cursor.fetchone()
    if existing_row is not None:
        return existing_row[0]

    strategy = bundle["strategy"]
    cursor.execute(
        """
        INSERT INTO alert_strategies (
            strategy_key,
            name,
            enabled,
            cooldown_seconds,
            interval_seconds,
            webhook_enabled,
            webhook_url
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            strategy_key,
            strategy["name"],
            strategy["enabled"],
            strategy["cooldown_seconds"],
            strategy["interval_seconds"],
            strategy["webhook_enabled"],
            strategy["webhook_url"],
        ),
    )
    strategy_id = cursor.fetchone()[0]

    for rule in bundle["rules"]:
        cursor.execute(
            """
            INSERT INTO alert_strategy_rules (
                strategy_id,
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
                strategy_id,
                rule["rule_key"],
                rule["label"],
                rule["enabled"],
                rule["operator"],
                rule["threshold_value"],
                rule.get("params_json", "{}"),
                rule["sort_order"],
            ),
        )
    return strategy_id


def _sync_strategy_rules(cursor, strategy_key: str, bundle: dict):
    strategy_id = _seed_strategy_if_missing(cursor, strategy_key, bundle)
    cursor.execute(
        "SELECT rule_key FROM alert_strategy_rules WHERE strategy_id = %s",
        (strategy_id,),
    )
    existing_rule_keys = {row[0] for row in cursor.fetchall()}

    for rule in bundle["rules"]:
        if rule["rule_key"] in existing_rule_keys:
            continue
        cursor.execute(
            """
            INSERT INTO alert_strategy_rules (
                strategy_id,
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
                strategy_id,
                rule["rule_key"],
                rule["label"],
                rule["enabled"],
                rule["operator"],
                rule["threshold_value"],
                rule.get("params_json", "{}"),
                rule["sort_order"],
            ),
        )


def _migrate_spike_strategy_from_legacy(cursor):
    cursor.execute("SELECT id, enabled, cooldown_seconds, interval_seconds, webhook_enabled, webhook_url FROM detector_settings ORDER BY updated_at DESC, id DESC LIMIT 1")
    latest_settings = cursor.fetchone()
    if latest_settings is None:
        return False

    cursor.execute("SELECT id FROM alert_strategies WHERE strategy_key = 'spike'")
    if cursor.fetchone() is not None:
        return False

    legacy_settings_id = latest_settings[0]
    cursor.execute(
        """
        INSERT INTO alert_strategies (
            strategy_key,
            name,
            enabled,
            cooldown_seconds,
            interval_seconds,
            webhook_enabled,
            webhook_url
        )
        VALUES ('spike', %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            STRATEGY_DEFINITIONS["spike"]["name"],
            latest_settings[1],
            latest_settings[2],
            latest_settings[3],
            latest_settings[4],
            latest_settings[5],
        ),
    )
    strategy_id = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT rule_key, label, enabled, operator, threshold_value, params_json, sort_order
        FROM detector_rules
        WHERE settings_id = %s
        ORDER BY sort_order ASC, id ASC
        """,
        (legacy_settings_id,),
    )
    legacy_rules = cursor.fetchall()
    for rule_key, label, enabled, operator, threshold_value, params_json, sort_order in legacy_rules:
        if rule_key == "avg_1h_trade_value":
            rule_key = "buy_1s_bid_trade_value"
            label = "최근 5분 내 1초 최대 매수 거래대금"
        if rule_key == "tps_multiplier":
            rule_key = "tps_ratio"
            label = "TPS 증가 배수"
        cursor.execute(
            """
            INSERT INTO alert_strategy_rules (
                strategy_id,
                rule_key,
                label,
                enabled,
                operator,
                threshold_value,
                params_json,
                sort_order
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (strategy_id, rule_key, label, enabled, operator, threshold_value, params_json, sort_order),
        )
    return True


def ensure_runtime_schema(conn, defaults=None, default_rules=None):
    with conn.cursor() as cursor:
        cursor.execute(ALERTS_TABLE_SQL)
        cursor.execute(ALERTS_RENAME_BUY_VALUE_SQL)
        cursor.execute(ALERTS_STRATEGY_ID_SQL)
        cursor.execute(ALERTS_STRATEGY_KEY_SQL)
        cursor.execute(ALERTS_DETAILS_JSON_SQL)
        cursor.execute(ALERTS_INDEX_TIME_SQL)
        cursor.execute(ALERTS_INDEX_MARKET_SQL)
        cursor.execute(ALERTS_INDEX_STRATEGY_SQL)

        _ensure_legacy_detector_schema(cursor)

        cursor.execute(STRATEGIES_TABLE_SQL)
        cursor.execute(STRATEGY_RULES_TABLE_SQL)
        cursor.execute(STRATEGY_RULES_INDEX_SQL)
        cursor.execute(BOT_DETECTION_STATUS_TABLE_SQL)
        cursor.execute(BOT_DETECTION_STATUS_ACTIVE_INDEX_SQL)

        _migrate_spike_strategy_from_legacy(cursor)
        _sync_strategy_rules(cursor, "spike", build_default_strategy_bundle("spike"))
        _sync_strategy_rules(cursor, "dip_buying", build_default_strategy_bundle("dip_buying"))
        _sync_strategy_rules(cursor, "bot_detection", build_default_strategy_bundle("bot_detection"))

    conn.commit()
    ensure_market_sync_schema(conn)
