FETCH_MARKET_METRICS_SQL = """
WITH recent_5m AS (
    SELECT
        market,
        COUNT(*)::double precision AS trade_count_5m,
        COALESCE(SUM(trade_value), 0)::double precision AS trade_value_5m,
        (ARRAY_AGG(price ORDER BY time ASC))[1]::double precision AS first_price_5m,
        (ARRAY_AGG(price ORDER BY time DESC))[1]::double precision AS last_price_5m
    FROM trades
    WHERE time >= now() - interval '5 minutes'
    GROUP BY market
),
recent_5m_buy_1s AS (
    SELECT
        market,
        COALESCE(MAX(buy_trade_value_1s), 0)::double precision AS buy_1s_bid_trade_value
    FROM (
        SELECT
            market,
            date_trunc('second', time) AS second_bucket,
            COALESCE(SUM(trade_value) FILTER (WHERE side = 'BID'), 0)::double precision AS buy_trade_value_1s
        FROM trades
        WHERE time >= now() - interval '5 minutes'
        GROUP BY market, date_trunc('second', time)
    ) buy_seconds
    GROUP BY market
),
recent_1h AS (
    SELECT
        market,
        COUNT(*)::double precision AS trade_count_1h,
        COALESCE(SUM(trade_value), 0)::double precision AS trade_value_1h
    FROM trades
    WHERE time >= now() - interval '1 hour'
    GROUP BY market
)
SELECT
    r5.market,
    r5.trade_value_5m,
    r1.trade_value_1h / 12.0 AS avg_1h_trade_value,
    COALESCE(buy1s.buy_1s_bid_trade_value, 0)::double precision AS buy_1s_bid_trade_value,
    r5.trade_count_5m / 300.0 AS tps_now,
    r1.trade_count_1h / 3600.0 AS tps_baseline,
    CASE
        WHEN r5.first_price_5m IS NULL OR r5.first_price_5m = 0 OR r5.last_price_5m IS NULL
        THEN NULL
        ELSE ABS((r5.last_price_5m - r5.first_price_5m) / r5.first_price_5m * 100.0)
    END AS price_change_pct,
    CASE
        WHEN r1.trade_value_1h IS NULL OR r1.trade_value_1h = 0
        THEN NULL
        ELSE r5.trade_value_5m / (r1.trade_value_1h / 12.0)
    END AS ratio_5m_vs_1h,
    CASE
        WHEN r1.trade_count_1h IS NULL OR r1.trade_count_1h = 0
        THEN NULL
        ELSE (r5.trade_count_5m / 300.0) / (r1.trade_count_1h / 3600.0)
    END AS tps_ratio
FROM recent_5m r5
JOIN recent_1h r1 ON r1.market = r5.market
LEFT JOIN recent_5m_buy_1s buy1s ON buy1s.market = r5.market
ORDER BY ratio_5m_vs_1h DESC, tps_ratio DESC;
"""

RECENT_ALERT_SQL = """
SELECT 1
FROM market_alerts
WHERE market = %s
  AND detected_at >= now() - make_interval(secs => %s)
LIMIT 1
"""

INSERT_ALERT_SQL = """
INSERT INTO market_alerts (
    detected_at,
    market,
    ratio_5m_vs_1h,
    tps_now,
    tps_baseline,
    price_change_pct,
    buy_1s_bid_trade_value,
    reason
)
VALUES (
    now(),
    %s,
    %s,
    %s,
    %s,
    %s,
    %s,
    %s
)
"""

FETCH_SETTINGS_SQL = """
SELECT
    id,
    enabled,
    cooldown_seconds,
    interval_seconds,
    webhook_enabled,
    webhook_url,
    updated_at
FROM detector_settings
ORDER BY updated_at DESC, id DESC
LIMIT 1
"""

FETCH_RULES_SQL = """
SELECT
    id,
    settings_id,
    rule_key,
    label,
    enabled,
    operator,
    threshold_value,
    params_json,
    sort_order,
    updated_at
FROM detector_rules
WHERE settings_id = %s
ORDER BY sort_order ASC, id ASC
"""

INSERT_SETTINGS_SQL = """
INSERT INTO detector_settings (
    enabled,
    cooldown_seconds,
    interval_seconds,
    webhook_enabled,
    webhook_url
)
VALUES (%s, %s, %s, %s, %s)
RETURNING id
"""

INSERT_RULE_SQL = """
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
"""
