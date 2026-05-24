import json
import signal
import sys
import time
from datetime import datetime, timezone

import websocket
from psycopg2.extras import execute_values

from app.common.config import CollectorConfig, DbConfig
from app.common.db import create_connection
from app.common.logging import build_logger
from app.common.schema import ensure_market_sync_schema
from app.markets.service import fetch_market_refresh_version, fetch_monitored_markets

logger = build_logger("upbit_collector", "collector.log")
conn = create_connection(DbConfig())
cursor = conn.cursor()
batch = []
current_batch_second = None
shutdown_requested = False
DEFAULT_MARKETS = ["KRW-BTC", "KRW-ETH"]
collector_config = CollectorConfig()
subscribed_refresh_version = 0
last_refresh_version_check_at = 0.0


def load_markets():
    try:
        markets = fetch_monitored_markets(conn)
        if markets:
            return markets
    except Exception as exc:
        logger.warning("failed to read monitored markets from DB: %s (using defaults)", exc)
        return DEFAULT_MARKETS
    logger.warning("monitored markets table is empty (using defaults)")
    return DEFAULT_MARKETS


def insert_batch():
    global batch
    if not batch:
        return

    try:
        execute_values(
            cursor,
            """
            INSERT INTO trades
            (time,market,price,volume,trade_value,side)
            VALUES %s
            """,
            batch,
        )
        conn.commit()
        logger.debug("inserted %d rows", len(batch))
        batch = []
    except Exception as exc:
        conn.rollback()
        logger.exception("DB batch error: %s", exc)
        batch = []


def on_message(ws, message):
    global batch, current_batch_second, last_refresh_version_check_at
    try:
        if isinstance(message, bytes):
            message = message.decode("utf-8")
        data = json.loads(message)
        trade_second = data["timestamp"] // 1000

        if current_batch_second is None:
            current_batch_second = trade_second
        elif trade_second != current_batch_second:
            insert_batch()
            current_batch_second = trade_second

        row = (
            datetime.fromtimestamp(data["timestamp"] / 1000, tz=timezone.utc),
            data["code"],
            data["trade_price"],
            data["trade_volume"],
            data["trade_price"] * data["trade_volume"],
            data["ask_bid"],
        )
        batch.append(row)
        current_monotonic = time.monotonic()
        if current_monotonic - last_refresh_version_check_at >= collector_config.refresh_check_interval_seconds:
            last_refresh_version_check_at = current_monotonic
            latest_refresh_version = fetch_market_refresh_version(conn)
            if latest_refresh_version > subscribed_refresh_version:
                logger.info(
                    "market refresh detected: version %s -> %s, reconnecting collector",
                    subscribed_refresh_version,
                    latest_refresh_version,
                )
                ws.close()
    except Exception as exc:
        logger.exception("processing error: %s", exc)


def on_open(ws):
    global subscribed_refresh_version, last_refresh_version_check_at
    markets = load_markets()
    subscribed_refresh_version = fetch_market_refresh_version(conn)
    last_refresh_version_check_at = time.monotonic()
    logger.info("collector started: subscribing %d markets", len(markets))
    subscribe = [
        {"ticket": "test"},
        {"type": "trade", "codes": markets},
    ]
    ws.send(json.dumps(subscribe))


def on_error(ws, error):
    logger.error("websocket error: %s", error)


def on_close(ws, close_status_code, close_msg):
    global current_batch_second
    insert_batch()
    current_batch_second = None
    if not shutdown_requested:
        logger.warning(
            "websocket closed: status=%s message=%s",
            close_status_code,
            close_msg,
        )


def handle_shutdown(signum, frame):
    global shutdown_requested
    shutdown_requested = True
    logger.info("collector stopping: received signal %s", signum)
    insert_batch()
    conn.close()
    sys.exit(0)


def run():
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)
    ensure_market_sync_schema(conn)

    while True:
        try:
            ws = websocket.WebSocketApp(
                "wss://api.upbit.com/websocket/v1",
                on_message=on_message,
                on_open=on_open,
                on_error=on_error,
                on_close=on_close,
            )
            ws.run_forever(
                ping_interval=collector_config.ping_interval,
                ping_timeout=collector_config.ping_timeout,
            )
        except Exception as exc:
            logger.exception("collector error: %s", exc)

        if shutdown_requested:
            break

        logger.warning("reconnecting in %d seconds...", collector_config.reconnect_delay_seconds)
        time.sleep(collector_config.reconnect_delay_seconds)
