CREATE INDEX IF NOT EXISTS idx_trades_market_time_side
ON trades (market, time DESC, side);

CREATE MATERIALIZED VIEW IF NOT EXISTS trades_1s
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT
    time_bucket('1 second', time) AS bucket,
    market,
    side,
    SUM(trade_value) AS value_krw
FROM trades
GROUP BY 1, 2, 3
WITH NO DATA;

-- Keep aggregate chunks smaller than the 30-day retention window.
SELECT set_chunk_time_interval(
    (
        SELECT format('%I.%I', materialization_hypertable_schema, materialization_hypertable_name)::regclass
        FROM timescaledb_information.continuous_aggregates
        WHERE view_schema = 'public' AND view_name = 'trades_1s'
    ),
    INTERVAL '7 days'
);

CREATE INDEX IF NOT EXISTS idx_trades_1s_market_bucket_side
ON trades_1s (market, bucket DESC, side);

SELECT add_continuous_aggregate_policy(
    'trades_1s',
    start_offset => INTERVAL '2 days',
    end_offset => INTERVAL '10 seconds',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists => TRUE
);
