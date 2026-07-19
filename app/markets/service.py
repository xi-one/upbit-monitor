import time
from datetime import datetime, timezone

import requests
from psycopg2.extras import RealDictCursor, execute_values

from app.common.config import DbConfig, MarketSyncConfig
from app.common.db import create_connection
from app.common.logging import build_logger
from app.common.schema import ensure_market_sync_schema

logger = build_logger("upbit_market_sync", "market-sync.log")

FETCH_MONITORED_MARKETS_SQL = """
SELECT market
FROM monitored_markets
ORDER BY market;
"""

FETCH_MARKET_LABEL_SQL = """
SELECT korean_name, symbol
FROM monitored_markets
WHERE market = %s;
"""

FETCH_MARKET_SYNC_STATUS_SQL = """
SELECT
    last_refreshed_at,
    market_count,
    refresh_version,
    last_error,
    updated_at
FROM market_sync_status
WHERE id = 1;
"""

REPLACE_MONITORED_MARKETS_SQL = """
INSERT INTO monitored_markets (
    market,
    korean_name,
    english_name,
    symbol,
    market_cap_krw,
    market_cap_source,
    updated_at
)
VALUES %s;
"""

UPDATE_MARKET_SYNC_STATUS_SUCCESS_SQL = """
INSERT INTO market_sync_status (
    id,
    last_refreshed_at,
    market_count,
    refresh_version,
    last_error,
    updated_at
)
VALUES (1, %s, %s, 1, '', now())
ON CONFLICT (id) DO UPDATE
SET
    last_refreshed_at = EXCLUDED.last_refreshed_at,
    market_count = EXCLUDED.market_count,
    refresh_version = market_sync_status.refresh_version + 1,
    last_error = '',
    updated_at = now()
RETURNING refresh_version;
"""

UPDATE_MARKET_SYNC_STATUS_ERROR_SQL = """
INSERT INTO market_sync_status (
    id,
    market_count,
    refresh_version,
    last_error,
    updated_at
)
VALUES (1, 0, 0, %s, now())
ON CONFLICT (id) DO UPDATE
SET
    last_error = EXCLUDED.last_error,
    updated_at = now();
"""


def fetch_monitored_markets(conn) -> list[str]:
    ensure_market_sync_schema(conn)
    with conn.cursor() as cursor:
        cursor.execute(FETCH_MONITORED_MARKETS_SQL)
        return [row[0] for row in cursor.fetchall()]


def format_market_label(market: str, korean_name: str | None, symbol: str | None) -> str:
    if korean_name and symbol:
        return f"{korean_name}[{symbol}]"
    return market


def fetch_market_label(conn, market: str) -> str:
    with conn.cursor() as cursor:
        cursor.execute(FETCH_MARKET_LABEL_SQL, (market,))
        row = cursor.fetchone()
    if row is None:
        return market
    return format_market_label(market, row[0], row[1])


def fetch_market_sync_status(conn) -> dict | None:
    ensure_market_sync_schema(conn)
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(FETCH_MARKET_SYNC_STATUS_SQL)
        return cursor.fetchone()


def fetch_market_refresh_version(conn) -> int:
    status = fetch_market_sync_status(conn)
    return int(status["refresh_version"]) if status else 0


def _fetch_json(url: str, timeout_seconds: int):
    response = requests.get(url, timeout=timeout_seconds)
    response.raise_for_status()
    return response.json()


def _build_market_cap_lookup(coinpaprika_tickers: list[dict], usdkrw_rate: float) -> dict[str, float]:
    market_cap_by_symbol: dict[str, float] = {}
    for ticker in coinpaprika_tickers:
        symbol = (ticker.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        quotes = ticker.get("quotes") or {}
        usd_quote = quotes.get("USD") or {}
        market_cap_usd = usd_quote.get("market_cap")
        if market_cap_usd in (None, ""):
            continue
        try:
            market_cap_krw = float(market_cap_usd) * usdkrw_rate
        except (TypeError, ValueError):
            continue
        previous = market_cap_by_symbol.get(symbol)
        if previous is None or market_cap_krw > previous:
            market_cap_by_symbol[symbol] = market_cap_krw
    return market_cap_by_symbol


def _filter_upbit_markets(upbit_markets: list[dict], market_cap_lookup: dict[str, float], config: MarketSyncConfig):
    filtered_markets = []
    excluded_markets = {
        market.strip().upper()
        for market in config.exclude_markets.split(",")
        if market.strip()
    }
    for entry in upbit_markets:
        market = entry.get("market", "")
        if not market.startswith("KRW-"):
            continue
        if market.upper() in excluded_markets:
            continue
        symbol = market.split("-", 1)[1]
        market_cap_krw = market_cap_lookup.get(symbol)
        include_market = market_cap_krw is None and config.include_unknown_markets
        if market_cap_krw is not None and market_cap_krw <= config.market_cap_limit_krw:
            include_market = True
        if not include_market:
            continue

        filtered_markets.append(
            {
                "market": market,
                "korean_name": entry.get("korean_name", ""),
                "english_name": entry.get("english_name", ""),
                "symbol": symbol,
                "market_cap_krw": market_cap_krw,
                "market_cap_source": "coinpaprika" if market_cap_krw is not None else "unknown",
            }
        )

    filtered_markets.sort(key=lambda item: item["market"])
    return filtered_markets


def refresh_market_universe(conn=None, config: MarketSyncConfig | None = None) -> dict:
    close_conn = False
    if conn is None:
        conn = create_connection(DbConfig())
        close_conn = True
    if config is None:
        config = MarketSyncConfig()

    ensure_market_sync_schema(conn)

    try:
        upbit_markets = _fetch_json(config.upbit_market_all_url, config.request_timeout_seconds)
        coinpaprika_tickers = _fetch_json(config.coinpaprika_tickers_url, config.request_timeout_seconds)
        market_cap_lookup = _build_market_cap_lookup(coinpaprika_tickers, config.usdkrw_rate)
        filtered_markets = _filter_upbit_markets(upbit_markets, market_cap_lookup, config)
        refreshed_at = datetime.now(timezone.utc)

        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM monitored_markets")
            if filtered_markets:
                execute_values(
                    cursor,
                    REPLACE_MONITORED_MARKETS_SQL,
                    [
                        (
                            item["market"],
                            item["korean_name"],
                            item["english_name"],
                            item["symbol"],
                            item["market_cap_krw"],
                            item["market_cap_source"],
                            refreshed_at,
                        )
                        for item in filtered_markets
                    ],
                )
            cursor.execute(
                UPDATE_MARKET_SYNC_STATUS_SUCCESS_SQL,
                (refreshed_at, len(filtered_markets)),
            )
            refresh_version = cursor.fetchone()[0]
        conn.commit()
        result = {
            "ok": True,
            "refreshed_at": refreshed_at,
            "market_count": len(filtered_markets),
            "refresh_version": refresh_version,
        }
        logger.info(
            "market refresh completed: count=%d version=%s",
            result["market_count"],
            result["refresh_version"],
        )
        return result
    except Exception as exc:
        conn.rollback()
        error_message = str(exc)
        with conn.cursor() as cursor:
            cursor.execute(UPDATE_MARKET_SYNC_STATUS_ERROR_SQL, (error_message,))
        conn.commit()
        logger.exception("market refresh failed: %s", exc)
        return {"ok": False, "error": error_message}
    finally:
        if close_conn:
            conn.close()


def run_market_sync_loop():
    conn = create_connection(DbConfig())
    config = MarketSyncConfig()
    ensure_market_sync_schema(conn)

    while True:
        result = refresh_market_universe(conn=conn, config=config)
        sleep_seconds = config.refresh_interval_seconds if result["ok"] else config.failure_retry_seconds
        time.sleep(sleep_seconds)
