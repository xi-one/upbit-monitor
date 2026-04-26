import json
import logging
from logging.handlers import TimedRotatingFileHandler
import os
import re
import signal
import sys
import time
from urllib import error, request

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor

load_dotenv()

LOG_DIR = os.getenv("LOG_DIR", os.path.join(os.path.dirname(__file__), "logs"))
LOG_FILE = os.getenv("DETECTOR_LOG_FILE", os.path.join(LOG_DIR, "detector.log"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("upbit_detector")
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
logger.handlers.clear()

formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

file_handler = TimedRotatingFileHandler(
    LOG_FILE,
    when="midnight",
    interval=1,
    backupCount=92,
    encoding="utf-8",
)
file_handler.suffix = "%Y%m%d"
file_handler.extMatch = re.compile(r"^\d{8}$", re.ASCII)
file_handler.setFormatter(formatter)

stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)

logger.addHandler(file_handler)
logger.addHandler(stream_handler)
logger.propagate = False

ALERT_RATIO_5M_VS_1H = float(os.getenv("ALERT_RATIO_5M_VS_1H", "2.2"))
ALERT_TPS_MULTIPLIER = float(os.getenv("ALERT_TPS_MULTIPLIER", "1.5"))
ALERT_PRICE_CHANGE_PCT_MAX = float(os.getenv("ALERT_PRICE_CHANGE_PCT_MAX", "2.0"))
ALERT_1H_AVG_TRADE_VALUE_MIN = float(os.getenv("ALERT_1H_AVG_TRADE_VALUE_MIN", "1000000000"))
ALERT_COOLDOWN_SECONDS = int(os.getenv("ALERT_COOLDOWN_SECONDS", "300"))
DETECTOR_INTERVAL_SECONDS = int(os.getenv("DETECTOR_INTERVAL_SECONDS", "10"))
ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "").strip()

shutdown_requested = False

conn = psycopg2.connect(
    host=os.getenv("POSTGRES_HOST", "localhost"),
    database=os.getenv("POSTGRES_DB"),
    user=os.getenv("POSTGRES_USER"),
    password=os.getenv("POSTGRES_PASSWORD"),
    port=os.getenv("POSTGRES_PORT", 5432),
)


def handle_shutdown(signum, frame):
    global shutdown_requested
    shutdown_requested = True
    logger.info("detector stopping: received signal %s", signum)
    conn.close()
    sys.exit(0)


def fetch_candidates():
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """
            WITH recent_5m AS (
                SELECT
                    market,
                    COUNT(*)::double precision AS trade_count_5m,
                    COALESCE(SUM(trade_value), 0)::double precision AS trade_value_5m,
                    (
                        ARRAY_AGG(price ORDER BY time ASC)
                    )[1]::double precision AS first_price_5m,
                    (
                        ARRAY_AGG(price ORDER BY time DESC)
                    )[1]::double precision AS last_price_5m
                FROM trades
                WHERE time >= now() - interval '5 minutes'
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
            WHERE (r1.trade_value_1h / 12.0) > %s
              AND CASE
                    WHEN r1.trade_value_1h IS NULL OR r1.trade_value_1h = 0
                    THEN NULL
                    ELSE r5.trade_value_5m / (r1.trade_value_1h / 12.0)
                  END > %s
              AND CASE
                    WHEN r1.trade_count_1h IS NULL OR r1.trade_count_1h = 0
                    THEN NULL
                    ELSE (r5.trade_count_5m / 300.0) / (r1.trade_count_1h / 3600.0)
                  END > %s
              AND CASE
                    WHEN r5.first_price_5m IS NULL OR r5.first_price_5m = 0 OR r5.last_price_5m IS NULL
                    THEN NULL
                    ELSE ABS((r5.last_price_5m - r5.first_price_5m) / r5.first_price_5m * 100.0)
                  END < %s
            ORDER BY ratio_5m_vs_1h DESC, tps_ratio DESC;
            """,
            (
                ALERT_1H_AVG_TRADE_VALUE_MIN,
                ALERT_RATIO_5M_VS_1H,
                ALERT_TPS_MULTIPLIER,
                ALERT_PRICE_CHANGE_PCT_MAX,
            ),
        )
        return cursor.fetchall()


def was_recently_alerted(market):
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT 1
            FROM market_alerts
            WHERE market = %s
              AND detected_at >= now() - make_interval(secs => %s)
            LIMIT 1
            """,
            (market, ALERT_COOLDOWN_SECONDS),
        )
        return cursor.fetchone() is not None


def insert_alert(row, reason):
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO market_alerts (
                detected_at,
                market,
                ratio_5m_vs_1h,
                tps_now,
                tps_baseline,
                price_change_pct,
                avg_1h_trade_value,
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
            """,
            (
                row["market"],
                row["ratio_5m_vs_1h"],
                row["tps_now"],
                row["tps_baseline"],
                row["price_change_pct"],
                row["avg_1h_trade_value"],
                reason,
            ),
        )
    conn.commit()


def send_alert(row, reason):
    if not ALERT_WEBHOOK_URL:
        logger.info("alert detected without webhook: %s %s", row["market"], reason)
        return

    payload = {
        "username": "Upbit Monitor",
        "content": f"Alert detected for **{row['market']}**",
        "embeds": [
            {
                "title": f"{row['market']} alert",
                "description": reason,
                "color": 16753920,
                "fields": [
                    {
                        "name": "5m / 1h ratio",
                        "value": f"{row['ratio_5m_vs_1h']:.2f}x",
                        "inline": True,
                    },
                    {
                        "name": "TPS now",
                        "value": f"{row['tps_now']:.3f}",
                        "inline": True,
                    },
                    {
                        "name": "TPS baseline",
                        "value": f"{row['tps_baseline']:.3f}",
                        "inline": True,
                    },
                    {
                        "name": "TPS ratio",
                        "value": f"{row['tps_ratio']:.2f}x",
                        "inline": True,
                    },
                    {
                        "name": "Price change",
                        "value": f"{row['price_change_pct']:.2f}%",
                        "inline": True,
                    },
                    {
                        "name": "1h avg trade value",
                        "value": f"{row['avg_1h_trade_value']:.0f} KRW",
                        "inline": False,
                    },
                ],
                "footer": {
                    "text": "Upbit detector"
                },
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        ],
    }
    req = request.Request(
        ALERT_WEBHOOK_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=5) as response:
            logger.info(
                "alert sent: market=%s status=%s",
                row["market"],
                response.status,
            )
    except error.URLError as exc:
        logger.exception("failed to send alert for %s: %s", row["market"], exc)


def build_reason(row):
    return (
        f"ratio={row['ratio_5m_vs_1h']:.2f}>={ALERT_RATIO_5M_VS_1H},"
        f" tps_ratio={row['tps_ratio']:.2f}>={ALERT_TPS_MULTIPLIER},"
        f" price_change_pct={row['price_change_pct']:.2f}<={ALERT_PRICE_CHANGE_PCT_MAX},"
        f" avg_1h_trade_value={row['avg_1h_trade_value']:.0f}>={ALERT_1H_AVG_TRADE_VALUE_MIN:.0f}"
    )


def run_detector():
    logger.info(
        "detector started: ratio=%.2f tps_multiplier=%.2f price_change_pct_max=%.2f avg_1h_trade_value_min=%.0f cooldown=%ss interval=%ss",
        ALERT_RATIO_5M_VS_1H,
        ALERT_TPS_MULTIPLIER,
        ALERT_PRICE_CHANGE_PCT_MAX,
        ALERT_1H_AVG_TRADE_VALUE_MIN,
        ALERT_COOLDOWN_SECONDS,
        DETECTOR_INTERVAL_SECONDS,
    )
    while not shutdown_requested:
        try:
            candidates = fetch_candidates()
            for row in candidates:
                if was_recently_alerted(row["market"]):
                    logger.debug("alert skipped by cooldown: %s", row["market"])
                    continue
                reason = build_reason(row)
                insert_alert(row, reason)
                send_alert(row, reason)
                logger.info("alert recorded: %s %s", row["market"], reason)
        except Exception as exc:
            conn.rollback()
            logger.exception("detector error: %s", exc)

        time.sleep(DETECTOR_INTERVAL_SECONDS)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)
    run_detector()
