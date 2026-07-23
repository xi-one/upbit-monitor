FETCH_SPIKE_MARKET_METRICS_SQL = """
WITH measurement AS (
    SELECT statement_timestamp() AS measured_at
),
recent_5m AS (
    SELECT
        market,
        COUNT(*)::double precision AS trade_count_5m,
        COALESCE(SUM(trade_value), 0)::double precision AS trade_value_5m,
        (ARRAY_AGG(price ORDER BY time ASC))[1]::double precision AS first_price_5m,
        (ARRAY_AGG(price ORDER BY time DESC))[1]::double precision AS last_price_5m
    FROM trades, measurement
    WHERE time >= measurement.measured_at - interval '5 minutes'
    GROUP BY market
),
recent_1m_buy_1s AS (
    SELECT
        market,
        COALESCE(MAX(buy_trade_value_1s), 0)::double precision AS buy_1s_bid_trade_value
    FROM (
        SELECT
            market,
            date_trunc('second', time) AS second_bucket,
            COALESCE(SUM(trade_value) FILTER (WHERE side = 'BID'), 0)::double precision AS buy_trade_value_1s
        FROM trades, measurement
        WHERE time >= measurement.measured_at - interval '1 minute'
        GROUP BY market, date_trunc('second', time)
    ) buy_seconds
    GROUP BY market
),
recent_1m AS (
    SELECT
        market,
        COUNT(*)::double precision AS trade_count_1m,
        COALESCE(SUM(trade_value) FILTER (WHERE side = 'BID'), 0)::double precision AS buy_1m_bid_trade_value,
        (ARRAY_AGG(price ORDER BY time ASC))[1]::double precision AS first_price_1m,
        (ARRAY_AGG(price ORDER BY time DESC))[1]::double precision AS last_price_1m
    FROM trades, measurement
    WHERE time >= measurement.measured_at - interval '1 minute'
    GROUP BY market
),
recent_1m_buy_by_price AS (
    SELECT
        market,
        price,
        COALESCE(SUM(volume), 0)::double precision AS buy_volume
    FROM trades, measurement
    WHERE time >= measurement.measured_at - interval '1 minute'
      AND side = 'BID'
    GROUP BY market, price
),
recent_1m_buy_summary AS (
    SELECT
        market,
        CASE
            WHEN SUM(buy_volume) = 0 THEN NULL
            ELSE ROUND((SUM(price * buy_volume) / SUM(buy_volume))::numeric, 6)
        END::double precision AS buy_average_price,
        JSONB_AGG(
            JSONB_BUILD_OBJECT('price', price, 'volume', buy_volume)
            ORDER BY price DESC
        ) AS buy_volume_by_price
    FROM recent_1m_buy_by_price
    GROUP BY market
),
recent_1h AS (
    SELECT
        market,
        COUNT(*)::double precision AS trade_count_1h,
        COALESCE(SUM(trade_value), 0)::double precision AS trade_value_1h
    FROM trades, measurement
    WHERE time >= measurement.measured_at - interval '1 hour'
    GROUP BY market
)
SELECT
    measurement.measured_at AS measurement_end_at,
    measurement.measured_at - interval '1 minute' AS measurement_start_at,
    r5.market,
    r5.trade_value_5m,
    r1.trade_value_1h / 12.0 AS avg_1h_trade_value,
    COALESCE(buy1s.buy_1s_bid_trade_value, 0)::double precision AS buy_1s_bid_trade_value,
    COALESCE(r1m.buy_1m_bid_trade_value, 0)::double precision AS buy_1m_bid_trade_value,
    buy_summary.buy_average_price,
    buy_summary.buy_volume_by_price,
    COALESCE(r1m.trade_count_1m, 0) / 60.0 AS tps_now,
    r1.trade_count_1h / 3600.0 AS tps_baseline,
    CASE
        WHEN r1m.first_price_1m IS NULL OR r1m.first_price_1m = 0 OR r1m.last_price_1m IS NULL
        THEN NULL
        ELSE ABS((r1m.last_price_1m - r1m.first_price_1m) / r1m.first_price_1m * 100.0)
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
JOIN measurement ON TRUE
JOIN recent_1h r1 ON r1.market = r5.market
LEFT JOIN recent_1m_buy_1s buy1s ON buy1s.market = r5.market
LEFT JOIN recent_1m r1m ON r1m.market = r5.market
LEFT JOIN recent_1m_buy_summary buy_summary ON buy_summary.market = r5.market
ORDER BY ratio_5m_vs_1h DESC, tps_ratio DESC;
"""

FETCH_DIP_MARKET_METRICS_SQL = """
WITH measurement AS (
    SELECT statement_timestamp() AS measured_at
),
recent_window AS (
    SELECT
        market,
        (ARRAY_AGG(price ORDER BY time ASC))[1]::double precision AS first_price,
        (ARRAY_AGG(price ORDER BY time DESC))[1]::double precision AS last_price,
        COALESCE(SUM(trade_value) FILTER (WHERE side = 'ASK'), 0)::double precision AS ask_trade_value
    FROM trades, measurement
    WHERE time >= measurement.measured_at - make_interval(mins => %s)
    GROUP BY market
),
recent_1m AS (
    SELECT
        market,
        COALESCE(SUM(trade_value) FILTER (WHERE side = 'BID'), 0)::double precision AS buy_1m_bid_trade_value,
        COALESCE(SUM(trade_value) FILTER (WHERE side = 'ASK'), 0)::double precision AS ask_1m_trade_value,
        CASE WHEN SUM(volume) FILTER (WHERE side = 'BID') = 0 THEN NULL
             ELSE ROUND((SUM(price * volume) FILTER (WHERE side = 'BID') / SUM(volume) FILTER (WHERE side = 'BID'))::numeric, 6)::double precision
        END AS buy_average_price,
        CASE WHEN SUM(volume) FILTER (WHERE side = 'ASK') = 0 THEN NULL
             ELSE ROUND((SUM(price * volume) FILTER (WHERE side = 'ASK') / SUM(volume) FILTER (WHERE side = 'ASK'))::numeric, 6)::double precision
        END AS ask_average_price,
        COUNT(*)::double precision / 60.0 AS tps_now,
        (ARRAY_AGG(price ORDER BY time ASC))[1]::double precision AS first_price_1m,
        (ARRAY_AGG(price ORDER BY time DESC))[1]::double precision AS last_price_1m
    FROM trades, measurement
    WHERE time >= measurement.measured_at - interval '1 minute'
    GROUP BY market
)
SELECT
    recent_window.market,
    recent_window.first_price,
    recent_window.last_price,
    recent_window.ask_trade_value,
    COALESCE(recent_1m.buy_1m_bid_trade_value, 0)::double precision AS buy_1m_bid_trade_value,
    COALESCE(recent_1m.ask_1m_trade_value, 0)::double precision AS ask_1m_trade_value,
    recent_1m.buy_average_price,
    recent_1m.ask_average_price,
    COALESCE(recent_1m.tps_now, 0)::double precision AS tps_now,
    CASE WHEN recent_1m.first_price_1m IS NULL OR recent_1m.first_price_1m = 0 OR recent_1m.last_price_1m IS NULL THEN NULL
         ELSE ((recent_1m.last_price_1m - recent_1m.first_price_1m) / recent_1m.first_price_1m) * 100.0
    END AS price_change_pct,
    CASE
        WHEN recent_window.first_price IS NULL OR recent_window.first_price = 0 OR recent_window.last_price IS NULL
        THEN NULL
        ELSE ((recent_window.first_price - recent_window.last_price) / recent_window.first_price) * 100.0
    END AS price_drop_pct
FROM recent_window
LEFT JOIN recent_1m ON recent_1m.market = recent_window.market
ORDER BY price_drop_pct DESC NULLS LAST, ask_trade_value DESC;
"""

FETCH_BOT_MARKET_METRICS_SQL = """
WITH recent_all AS (
    SELECT
        time,
        market,
        side,
        price,
        trade_value
    FROM trades
    WHERE time >= statement_timestamp() - make_interval(secs => %s)
),
candidate_trades AS (
    SELECT *
    FROM recent_all
    WHERE trade_value >= %s
      AND trade_value <= %s
),
buy_sell_pairs AS (
    SELECT
        buy.market,
        buy.time AS bid_time,
        MIN(sell.time) AS ask_time
    FROM candidate_trades buy
    JOIN candidate_trades sell
      ON sell.market = buy.market
     AND sell.side = 'ASK'
     AND sell.time > buy.time
     AND sell.time <= buy.time + make_interval(secs => %s)
    WHERE buy.side = 'BID'
    GROUP BY buy.market, buy.time
),
metrics AS (
    SELECT
        market,
        COUNT(*)::double precision AS trade_count,
        COALESCE(SUM(trade_value), 0)::double precision AS total_trade_value,
        MIN(price)::double precision AS min_price,
        MAX(price)::double precision AS max_price,
        (ARRAY_AGG(price ORDER BY time ASC))[1]::double precision AS first_price,
        (ARRAY_AGG(price ORDER BY time DESC))[1]::double precision AS last_price
    FROM recent_all
    GROUP BY market
),
pair_metrics AS (
    SELECT
        market,
        COUNT(*)::double precision AS buy_sell_pair_count
    FROM buy_sell_pairs
    GROUP BY market
)
SELECT
    metrics.market,
    metrics.trade_count,
    COALESCE(pair_metrics.buy_sell_pair_count, 0)::double precision AS buy_sell_pair_count,
    metrics.total_trade_value,
    metrics.trade_count / %s::double precision AS tps,
    CASE
        WHEN min_price IS NULL OR min_price = 0 OR max_price IS NULL
        THEN NULL
        ELSE ((max_price - min_price) / min_price) * 100.0
    END AS price_range_pct,
    CASE
        WHEN first_price IS NULL OR first_price = 0 OR last_price IS NULL
        THEN NULL
        ELSE GREATEST(((last_price - first_price) / first_price) * 100.0, 0)
    END AS price_increase_pct
FROM metrics
LEFT JOIN pair_metrics ON pair_metrics.market = metrics.market
ORDER BY buy_sell_pair_count DESC, tps DESC, total_trade_value DESC;
"""

RECENT_ALERT_SQL = """
SELECT 1
FROM market_alerts
WHERE market = %s
  AND strategy_key = %s
  AND detected_at >= statement_timestamp() - make_interval(secs => %s)
LIMIT 1
"""

INSERT_ALERT_SQL = """
INSERT INTO market_alerts (
    detected_at,
    strategy_id,
    strategy_key,
    market,
    ratio_5m_vs_1h,
    tps_now,
    tps_baseline,
    price_change_pct,
    buy_1s_bid_trade_value,
    reason,
    details_json
)
VALUES (
    statement_timestamp(),
    %s,
    %s,
    %s,
    %s,
    %s,
    %s,
    %s,
    %s,
    %s,
    %s::jsonb
)
"""

UPSERT_BOT_DETECTION_STATUS_SQL = """
INSERT INTO bot_detection_status (
    market,
    active,
    first_detected_at,
    last_detected_at,
    cleared_at,
    buy_sell_pair_count,
    tps,
    price_range_pct,
    price_increase_pct,
    total_trade_value,
    reason,
    metrics_json
)
VALUES (
    %s,
    TRUE,
    statement_timestamp(),
    statement_timestamp(),
    NULL,
    %s,
    %s,
    %s,
    %s,
    %s,
    %s,
    %s::jsonb
)
ON CONFLICT (market) DO UPDATE SET
    active = TRUE,
    last_detected_at = EXCLUDED.last_detected_at,
    cleared_at = NULL,
    buy_sell_pair_count = EXCLUDED.buy_sell_pair_count,
    tps = EXCLUDED.tps,
    price_range_pct = EXCLUDED.price_range_pct,
    price_increase_pct = EXCLUDED.price_increase_pct,
    total_trade_value = EXCLUDED.total_trade_value,
    reason = EXCLUDED.reason,
    metrics_json = EXCLUDED.metrics_json
"""

MARK_INACTIVE_BOT_DETECTION_STATUS_SQL = """
UPDATE bot_detection_status
SET
    active = FALSE,
    cleared_at = statement_timestamp()
WHERE active = TRUE
  AND NOT (market = ANY(%s))
"""

MARK_ALL_INACTIVE_BOT_DETECTION_STATUS_SQL = """
UPDATE bot_detection_status
SET
    active = FALSE,
    cleared_at = statement_timestamp()
WHERE active = TRUE
"""

FETCH_STRATEGIES_SQL = """
SELECT
    id,
    strategy_key,
    name,
    enabled,
    cooldown_seconds,
    interval_seconds,
    webhook_enabled,
    webhook_url,
    updated_at
FROM alert_strategies
ORDER BY id ASC
"""

FETCH_STRATEGY_SQL = """
SELECT
    id,
    strategy_key,
    name,
    enabled,
    cooldown_seconds,
    interval_seconds,
    webhook_enabled,
    webhook_url,
    updated_at
FROM alert_strategies
WHERE strategy_key = %s
LIMIT 1
"""

FETCH_STRATEGY_RULES_SQL = """
SELECT
    id,
    strategy_id,
    rule_key,
    label,
    enabled,
    operator,
    threshold_value,
    params_json,
    sort_order,
    updated_at
FROM alert_strategy_rules
WHERE strategy_id = %s
ORDER BY sort_order ASC, id ASC
"""

UPSERT_STRATEGY_SQL = """
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
ON CONFLICT (strategy_key) DO UPDATE SET
    name = EXCLUDED.name,
    enabled = EXCLUDED.enabled,
    cooldown_seconds = EXCLUDED.cooldown_seconds,
    interval_seconds = EXCLUDED.interval_seconds,
    webhook_enabled = EXCLUDED.webhook_enabled,
    webhook_url = EXCLUDED.webhook_url,
    updated_at = now()
RETURNING id
"""

DELETE_STRATEGY_RULES_SQL = """
DELETE FROM alert_strategy_rules
WHERE strategy_id = %s
"""

INSERT_STRATEGY_RULE_SQL = """
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
"""
