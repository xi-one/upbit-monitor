-- Grafana panel queries for Upbit trade monitoring.
-- Assumption:
--   side = 'BID' -> buy-side trades
--   side = 'ASK' -> sell-side trades
--
-- Threshold:
--   20,000,000 KRW per second
--
-- Usage:
--   1. Create one Time series panel for buy-side and one for sell-side.
--   2. Paste the matching query below into each panel.
--   3. Format = Time series
--   4. Legend = {{market}}

-- Buy-side panel
WITH per_second AS (
  SELECT
    time_bucket('1 second', time) AS bucket,
    market,
    side,
    SUM(trade_value) AS value_krw
  FROM trades
  WHERE $__timeFilter(time)
  GROUP BY 1, 2, 3
),
active_markets AS (
  SELECT market
  FROM per_second
  WHERE side = 'BID'
  GROUP BY market
  HAVING MAX(value_krw) >= 20000000
)
SELECT
  bucket AS "time",
  market,
  value_krw
FROM per_second
WHERE side = 'BID'
  AND market IN (SELECT market FROM active_markets)
ORDER BY 1, 2;

-- Sell-side panel
WITH per_second AS (
  SELECT
    time_bucket('1 second', time) AS bucket,
    market,
    side,
    SUM(trade_value) AS value_krw
  FROM trades
  WHERE $__timeFilter(time)
  GROUP BY 1, 2, 3
),
active_markets AS (
  SELECT market
  FROM per_second
  WHERE side = 'ASK'
  GROUP BY market
  HAVING MAX(value_krw) >= 20000000
)
SELECT
  bucket AS "time",
  market,
  value_krw
FROM per_second
WHERE side = 'ASK'
  AND market IN (SELECT market FROM active_markets)
ORDER BY 1, 2;

-- Optional: combined panel with side in series name
WITH per_second AS (
  SELECT
    time_bucket('1 second', time) AS bucket,
    market,
    side,
    SUM(trade_value) AS value_krw
  FROM trades
  WHERE $__timeFilter(time)
  GROUP BY 1, 2, 3
),
active_markets AS (
  SELECT market, side
  FROM per_second
  GROUP BY market, side
  HAVING MAX(value_krw) >= 20000000
)
SELECT
  bucket AS "time",
  market || ' ' || side AS metric,
  value_krw
FROM per_second
WHERE (market, side) IN (SELECT market, side FROM active_markets)
ORDER BY 1, 2;
