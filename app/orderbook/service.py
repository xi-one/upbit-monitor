import json
import signal
import sys
import time
from datetime import datetime, timedelta, timezone

import websocket
import requests
from psycopg2.extras import Json

from app.common.config import DbConfig, OrderbookWallConfig
from app.common.db import create_connection
from app.common.logging import build_logger
from app.common.schema import ensure_market_sync_schema, ensure_orderbook_schema
from app.markets.service import fetch_market_label, fetch_market_refresh_version, fetch_monitored_markets

logger = build_logger("upbit_orderbook", "orderbook.log")
conn = create_connection(DbConfig())
cursor = conn.cursor()
config = OrderbookWallConfig()
settings = {
    "enabled": True,
    "orderbook_depth": config.orderbook_depth,
    "min_wall_value_krw": config.min_wall_value_krw,
    "min_concentration_ratio": config.min_concentration_ratio,
    "drop_alert_pct": config.drop_alert_pct,
    "breach_confirm_window_seconds": config.breach_confirm_window_seconds,
    "breach_confirm_bid_ratio": config.breach_confirm_bid_ratio,
    "breach_price_tolerance_pct": config.breach_price_tolerance_pct,
    "breach_display_seconds": config.breach_display_seconds,
    "webhook_enabled": False,
    "webhook_url": "",
    "cooldown_seconds": 300,
}
shutdown_requested = False
DEFAULT_MARKETS = ["KRW-BTC", "KRW-ETH"]
subscribed_refresh_version = 0
last_refresh_version_check_at = 0.0
previous_walls: dict[str, dict] = {}
pending_breaches: dict[str, dict] = {}
alert_cooldowns: dict[str, datetime] = {}
ticker_24h_by_market: dict[str, float] = {}

UPSERT_ORDERBOOK_WALL_STATUS_SQL = """
INSERT INTO orderbook_wall_status (
    market,
    active,
    breached,
    first_detected_at,
    last_detected_at,
    last_breached_at,
    breached_until,
    ask_price,
    ask_size,
    ask_value_krw,
    total_ask_value_krw,
    concentration_ratio,
    previous_ask_price,
    previous_ask_size,
    previous_ask_value_krw,
    drop_pct,
    bid_trade_value_at_wall,
    breach_confirm_ratio,
    acc_trade_price_24h,
    orderbook_ts,
    updated_at,
    metrics_json
)
VALUES (
    %(market)s,
    %(active)s,
    %(breached)s,
    CASE WHEN %(active)s THEN %(now)s ELSE NULL END,
    CASE WHEN %(active)s THEN %(now)s ELSE NULL END,
    %(last_breached_at)s,
    %(breached_until)s,
    %(ask_price)s,
    %(ask_size)s,
    %(ask_value_krw)s,
    %(total_ask_value_krw)s,
    %(concentration_ratio)s,
    %(previous_ask_price)s,
    %(previous_ask_size)s,
    %(previous_ask_value_krw)s,
    %(drop_pct)s,
    %(bid_trade_value_at_wall)s,
    %(breach_confirm_ratio)s,
    %(acc_trade_price_24h)s,
    %(orderbook_ts)s,
    %(now)s,
    %(metrics_json)s
)
ON CONFLICT (market) DO UPDATE SET
    active = EXCLUDED.active,
    breached = EXCLUDED.breached,
    first_detected_at = CASE
        WHEN EXCLUDED.active AND orderbook_wall_status.first_detected_at IS NULL THEN EXCLUDED.first_detected_at
        WHEN EXCLUDED.active AND NOT orderbook_wall_status.active THEN EXCLUDED.first_detected_at
        WHEN EXCLUDED.active THEN orderbook_wall_status.first_detected_at
        ELSE NULL
    END,
    last_detected_at = CASE WHEN EXCLUDED.active THEN EXCLUDED.last_detected_at ELSE orderbook_wall_status.last_detected_at END,
    last_breached_at = COALESCE(EXCLUDED.last_breached_at, orderbook_wall_status.last_breached_at),
    breached_until = COALESCE(EXCLUDED.breached_until, orderbook_wall_status.breached_until),
    ask_price = EXCLUDED.ask_price,
    ask_size = EXCLUDED.ask_size,
    ask_value_krw = EXCLUDED.ask_value_krw,
    total_ask_value_krw = EXCLUDED.total_ask_value_krw,
    concentration_ratio = EXCLUDED.concentration_ratio,
    previous_ask_price = EXCLUDED.previous_ask_price,
    previous_ask_size = EXCLUDED.previous_ask_size,
    previous_ask_value_krw = EXCLUDED.previous_ask_value_krw,
    drop_pct = EXCLUDED.drop_pct,
    bid_trade_value_at_wall = EXCLUDED.bid_trade_value_at_wall,
    breach_confirm_ratio = EXCLUDED.breach_confirm_ratio,
    acc_trade_price_24h = COALESCE(EXCLUDED.acc_trade_price_24h, orderbook_wall_status.acc_trade_price_24h),
    orderbook_ts = EXCLUDED.orderbook_ts,
    updated_at = EXCLUDED.updated_at,
    metrics_json = EXCLUDED.metrics_json
"""

FETCH_BID_TRADE_VALUE_AT_WALL_SQL = """
SELECT COALESCE(SUM(trade_value), 0)::double precision
FROM trades
WHERE market = %s
  AND side = 'BID'
  AND time >= %s
  AND time <= %s
  AND price >= %s
  AND price <= %s;
"""

FETCH_ORDERBOOK_WALL_SETTINGS_SQL = """
SELECT
    enabled,
    orderbook_depth,
    min_wall_value_krw,
    min_concentration_ratio,
    drop_alert_pct,
    breach_confirm_window_seconds,
    breach_confirm_bid_ratio,
    breach_price_tolerance_pct,
    breach_display_seconds,
    webhook_enabled,
    webhook_url,
    cooldown_seconds
FROM orderbook_wall_settings
WHERE id = 1;
"""

DISABLE_ORDERBOOK_WALL_STATUS_SQL = """
UPDATE orderbook_wall_status
SET active = FALSE,
    breached = FALSE,
    updated_at = statement_timestamp()
WHERE active = TRUE OR breached = TRUE;
"""


def refresh_settings():
    try:
        cursor.execute(FETCH_ORDERBOOK_WALL_SETTINGS_SQL)
        row = cursor.fetchone()
    except Exception as exc:
        conn.rollback()
        logger.warning("failed to load orderbook settings: %s", exc)
        return
    if row is None:
        return

    keys = list(settings.keys())
    for key, value in zip(keys, row):
        settings[key] = value


def _format_krw(value) -> str:
    if value is None:
        return "-"
    return f"{float(value):,.0f}원"


def _format_pct(value, digits=1) -> str:
    if value is None:
        return "-"
    return f"{float(value):.{digits}f}%"


def _format_price(value) -> str:
    if value is None:
        return "-"
    price = float(value)
    digits = 0
    threshold = 100.0
    while price < threshold and digits < 8:
        digits += 1
        threshold /= 10.0
    return f"{price:,.{digits}f}원"


def send_breach_alert(snapshot: dict, breach: dict, now: datetime):
    if not settings["webhook_enabled"] or not settings["webhook_url"]:
        return

    market = snapshot["market"]
    try:
        market_label = fetch_market_label(conn, market)
    except Exception as exc:
        conn.rollback()
        logger.warning("failed to load market label: market=%s error=%s", market, exc)
        market_label = market
    last_alert_at = alert_cooldowns.get(market)
    cooldown_seconds = int(settings["cooldown_seconds"] or 0)
    if last_alert_at and (now - last_alert_at).total_seconds() < cooldown_seconds:
        logger.debug("orderbook breach alert skipped by cooldown: market=%s", market)
        return

    payload = {
        "username": "업비트 모니터",
        "content": f"[호가벽 뚫림] 매수 체결로 매도벽 돌파 감지: **{market_label}**",
        "embeds": [
            {
                "title": f"{market_label} 호가벽 뚫림",
                "description": "매도벽 물량 감소와 같은 가격대 BID 체결이 함께 확인되었습니다.",
                "color": 15158332,
                "fields": [
                    {"name": "매도벽 가격", "value": _format_price(breach.get("previous_ask_price")), "inline": True},
                    {"name": "기존 매도벽 거래대금", "value": _format_krw(breach.get("previous_ask_value_krw")), "inline": True},
                    {"name": "물량 감소율", "value": _format_pct(breach.get("drop_pct"), 1), "inline": True},
                    {"name": "확인된 BID 체결금액", "value": _format_krw(breach.get("bid_trade_value_at_wall")), "inline": True},
                    {
                        "name": "BID 확인 비율",
                        "value": _format_pct((breach.get("breach_confirm_ratio") or 0) * 100, 1),
                        "inline": True,
                    },
                    {"name": "24H 거래대금", "value": _format_krw(ticker_24h_by_market.get(market)), "inline": False},
                ],
                "footer": {"text": "업비트 호가벽 감지기"},
                "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        ],
    }
    try:
        response = requests.post(str(settings["webhook_url"]), json=payload, timeout=5)
        response.raise_for_status()
        alert_cooldowns[market] = now
        logger.info("orderbook breach alert sent: market=%s status=%s", market, response.status_code)
    except requests.RequestException as exc:
        logger.exception("failed to send orderbook breach alert for %s: %s", market, exc)


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


def _parse_ts(data: dict) -> datetime:
    timestamp = data.get("timestamp") or data.get("tms")
    if timestamp:
        return datetime.fromtimestamp(float(timestamp) / 1000, tz=timezone.utc)
    return datetime.now(timezone.utc)


def _get_current_value_at_price(units: list[dict], price: float | None) -> tuple[float, float]:
    if price is None:
        return 0.0, 0.0
    for unit in units:
        ask_price = float(unit.get("ask_price") or 0)
        if ask_price == price:
            ask_size = float(unit.get("ask_size") or 0)
            return ask_size, ask_price * ask_size
    return 0.0, 0.0


def _build_wall_snapshot(data: dict) -> dict | None:
    if not settings["enabled"]:
        return None

    units = data.get("orderbook_units") or []
    if not units:
        return None

    depth_units = units[: max(1, int(settings["orderbook_depth"]))]
    ask_levels = []
    for unit in depth_units:
        ask_price = float(unit.get("ask_price") or 0)
        ask_size = float(unit.get("ask_size") or 0)
        ask_value = ask_price * ask_size
        ask_levels.append(
            {
                "ask_price": ask_price,
                "ask_size": ask_size,
                "ask_value_krw": ask_value,
            }
        )

    total_ask_value = sum(level["ask_value_krw"] for level in ask_levels)
    if total_ask_value <= 0:
        return None

    max_level = max(ask_levels, key=lambda level: level["ask_value_krw"])
    concentration_ratio = max_level["ask_value_krw"] / total_ask_value
    active = (
        max_level["ask_value_krw"] >= float(settings["min_wall_value_krw"])
        and concentration_ratio >= float(settings["min_concentration_ratio"])
    )
    return {
        "market": data["code"],
        "active": active,
        "ask_price": max_level["ask_price"],
        "ask_size": max_level["ask_size"],
        "ask_value_krw": max_level["ask_value_krw"],
        "total_ask_value_krw": total_ask_value,
        "concentration_ratio": concentration_ratio,
        "orderbook_ts": _parse_ts(data),
        "ask_levels": ask_levels,
    }


def _detect_breach(market: str, snapshot: dict, now: datetime) -> dict:
    previous = previous_walls.get(market) or {}
    previous_active = bool(previous.get("active"))
    previous_price = previous.get("ask_price")
    previous_value = float(previous.get("ask_value_krw") or 0)
    previous_size = float(previous.get("ask_size") or 0)
    previous_orderbook_ts = previous.get("orderbook_ts")
    current_size_at_previous, current_value_at_previous = _get_current_value_at_price(
        snapshot["ask_levels"],
        previous_price,
    )

    drop_pct = None
    bid_trade_value_at_wall = None
    breach_confirm_ratio = None
    breached_until = previous.get("breached_until")
    last_breached_at = previous.get("last_breached_at")
    if previous_active and previous_value > 0:
        drop_pct = max(0.0, (previous_value - current_value_at_previous) / previous_value * 100.0)
        if drop_pct >= float(settings["drop_alert_pct"]):
            pending_breaches[market] = {
                "market": market,
                "detected_at": now,
                "expires_at": now + timedelta(seconds=float(settings["breach_confirm_window_seconds"])),
                "previous_ask_price": previous_price,
                "previous_ask_size": previous_size,
                "previous_ask_value_krw": previous_value,
                "removed_value_krw": previous_value - current_value_at_previous,
                "drop_pct": drop_pct,
                "start_at": (previous_orderbook_ts or snapshot["orderbook_ts"]) - timedelta(seconds=1),
            }

    pending = pending_breaches.get(market)
    if pending:
        if now <= pending["expires_at"]:
            bid_trade_value_at_wall = _fetch_bid_trade_value_at_wall(pending, now)
            removed_value = float(pending["removed_value_krw"] or 0)
            if removed_value > 0:
                breach_confirm_ratio = bid_trade_value_at_wall / removed_value
            if breach_confirm_ratio is not None and breach_confirm_ratio >= float(settings["breach_confirm_bid_ratio"]):
                last_breached_at = now
                breached_until = now + timedelta(seconds=int(settings["breach_display_seconds"]))
                previous_price = pending["previous_ask_price"]
                previous_size = pending["previous_ask_size"]
                previous_value = pending["previous_ask_value_krw"]
                drop_pct = pending["drop_pct"]
                pending_breaches.pop(market, None)
        else:
            pending_breaches.pop(market, None)

    breached = bool(breached_until and now <= breached_until)
    return {
        "breached": breached,
        "last_breached_at": last_breached_at,
        "breached_until": breached_until,
        "previous_ask_price": previous_price,
        "previous_ask_size": previous_size if previous else None,
        "previous_ask_value_krw": previous_value if previous else None,
        "drop_pct": drop_pct,
        "bid_trade_value_at_wall": bid_trade_value_at_wall,
        "breach_confirm_ratio": breach_confirm_ratio,
        "newly_confirmed": last_breached_at == now,
    }


def _fetch_bid_trade_value_at_wall(pending: dict, now: datetime) -> float:
    wall_price = float(pending["previous_ask_price"] or 0)
    if wall_price <= 0:
        return 0.0
    tolerance = wall_price * float(settings["breach_price_tolerance_pct"]) / 100.0
    min_price = wall_price - tolerance
    max_price = wall_price + tolerance
    cursor.execute(
        FETCH_BID_TRADE_VALUE_AT_WALL_SQL,
        (
            pending["market"],
            pending["start_at"],
            now,
            min_price,
            max_price,
        ),
    )
    return float(cursor.fetchone()[0] or 0)


def upsert_status(snapshot: dict):
    market = snapshot["market"]
    now = datetime.now(timezone.utc)
    breach = _detect_breach(market, snapshot, now)
    if breach["newly_confirmed"]:
        send_breach_alert(snapshot, breach, now)
    params = {
        "market": market,
        "active": snapshot["active"],
        "breached": breach["breached"],
        "now": now,
        "last_breached_at": breach["last_breached_at"],
        "breached_until": breach["breached_until"],
        "ask_price": snapshot["ask_price"],
        "ask_size": snapshot["ask_size"],
        "ask_value_krw": snapshot["ask_value_krw"],
        "total_ask_value_krw": snapshot["total_ask_value_krw"],
        "concentration_ratio": snapshot["concentration_ratio"],
        "previous_ask_price": breach["previous_ask_price"],
        "previous_ask_size": breach["previous_ask_size"],
        "previous_ask_value_krw": breach["previous_ask_value_krw"],
        "drop_pct": breach["drop_pct"],
        "bid_trade_value_at_wall": breach["bid_trade_value_at_wall"],
        "breach_confirm_ratio": breach["breach_confirm_ratio"],
        "acc_trade_price_24h": ticker_24h_by_market.get(market),
        "orderbook_ts": snapshot["orderbook_ts"],
        "metrics_json": Json(
            {
                "ask_levels": snapshot["ask_levels"],
                "breach_confirm_bid_ratio": settings["breach_confirm_bid_ratio"],
                "breach_price_tolerance_pct": settings["breach_price_tolerance_pct"],
            }
        ),
    }
    cursor.execute(UPSERT_ORDERBOOK_WALL_STATUS_SQL, params)
    conn.commit()

    previous_walls[market] = {
        "active": snapshot["active"],
        "ask_price": snapshot["ask_price"],
        "ask_size": snapshot["ask_size"],
        "ask_value_krw": snapshot["ask_value_krw"],
        "orderbook_ts": snapshot["orderbook_ts"],
        "last_breached_at": breach["last_breached_at"],
        "breached_until": breach["breached_until"],
    }


def process_orderbook(data: dict):
    snapshot = _build_wall_snapshot(data)
    if not snapshot:
        return
    upsert_status(snapshot)


def process_ticker(data: dict):
    market = data.get("code")
    if not market:
        return
    acc_trade_price_24h = data.get("acc_trade_price_24h")
    if acc_trade_price_24h is None:
        return
    ticker_24h_by_market[market] = float(acc_trade_price_24h)


def on_message(ws, message):
    global last_refresh_version_check_at
    try:
        if isinstance(message, bytes):
            message = message.decode("utf-8")
        data = json.loads(message)
        message_type = data.get("type")
        if message_type == "ticker":
            process_ticker(data)
        elif message_type == "orderbook":
            process_orderbook(data)

        current_monotonic = time.monotonic()
        if current_monotonic - last_refresh_version_check_at >= config.refresh_check_interval_seconds:
            last_refresh_version_check_at = current_monotonic
            refresh_settings()
            if not settings["enabled"]:
                cursor.execute(DISABLE_ORDERBOOK_WALL_STATUS_SQL)
                conn.commit()
            latest_refresh_version = fetch_market_refresh_version(conn)
            if latest_refresh_version > subscribed_refresh_version:
                logger.info(
                    "market refresh detected: version %s -> %s, reconnecting orderbook collector",
                    subscribed_refresh_version,
                    latest_refresh_version,
                )
                ws.close()
    except Exception as exc:
        conn.rollback()
        logger.exception("orderbook processing error: %s", exc)


def on_open(ws):
    global subscribed_refresh_version, last_refresh_version_check_at
    markets = load_markets()
    subscribed_refresh_version = fetch_market_refresh_version(conn)
    last_refresh_version_check_at = time.monotonic()
    logger.info("orderbook collector started: subscribing %d markets", len(markets))
    refresh_settings()
    subscribe = [
        {"ticket": "orderbook-wall-monitor"},
        {"type": "ticker", "codes": markets},
        {"type": "orderbook", "codes": markets},
    ]
    ws.send(json.dumps(subscribe))


def on_error(ws, error):
    logger.error("orderbook websocket error: %s", error)


def on_close(ws, close_status_code, close_msg):
    if not shutdown_requested:
        logger.warning("orderbook websocket closed: status=%s message=%s", close_status_code, close_msg)


def handle_shutdown(signum, frame):
    global shutdown_requested
    shutdown_requested = True
    logger.info("orderbook collector stopping: received signal %s", signum)
    conn.close()
    sys.exit(0)


def run():
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)
    ensure_market_sync_schema(conn)
    ensure_orderbook_schema(conn)

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
                ping_interval=config.ping_interval,
                ping_timeout=config.ping_timeout,
            )
        except Exception as exc:
            logger.exception("orderbook collector error: %s", exc)

        if shutdown_requested:
            break

        logger.warning("reconnecting orderbook collector in %d seconds...", config.reconnect_delay_seconds)
        time.sleep(config.reconnect_delay_seconds)
