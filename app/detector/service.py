import signal
import sys
import time

from psycopg2.extras import RealDictCursor

from app.common.config import DbConfig, DetectorConfig
from app.common.db import create_connection
from app.common.logging import build_logger
from app.common.schema import ensure_runtime_schema
from app.detector.notifier import send_discord_alert
from app.detector.queries import FETCH_CANDIDATES_SQL, FETCH_SETTINGS_SQL, INSERT_ALERT_SQL, RECENT_ALERT_SQL

logger = build_logger("upbit_detector", "detector.log")
detector_config = DetectorConfig()
conn = create_connection(DbConfig())
shutdown_requested = False


def handle_shutdown(signum, frame):
    global shutdown_requested
    shutdown_requested = True
    logger.info("detector stopping: received signal %s", signum)
    conn.close()
    sys.exit(0)


def fetch_candidates(settings):
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            FETCH_CANDIDATES_SQL,
            (
                settings["avg_1h_trade_value_min"],
                settings["ratio_5m_vs_1h"],
                settings["tps_multiplier"],
                settings["price_change_pct_max"],
            ),
        )
        return cursor.fetchall()


def fetch_runtime_settings():
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(FETCH_SETTINGS_SQL)
        row = cursor.fetchone()
        if row is None:
            return {
                "ratio_5m_vs_1h": detector_config.ratio_5m_vs_1h,
                "tps_multiplier": detector_config.tps_multiplier,
                "price_change_pct_max": detector_config.price_change_pct_max,
                "avg_1h_trade_value_min": detector_config.avg_1h_trade_value_min,
                "cooldown_seconds": detector_config.cooldown_seconds,
                "interval_seconds": detector_config.interval_seconds,
                "webhook_url": detector_config.webhook_url,
            }
        return row


def was_recently_alerted(market, cooldown_seconds):
    with conn.cursor() as cursor:
        cursor.execute(RECENT_ALERT_SQL, (market, cooldown_seconds))
        return cursor.fetchone() is not None


def insert_alert(row, reason):
    with conn.cursor() as cursor:
        cursor.execute(
            INSERT_ALERT_SQL,
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


def build_reason(row, settings):
    return (
        f"ratio={row['ratio_5m_vs_1h']:.2f}>={settings['ratio_5m_vs_1h']},"
        f" tps_ratio={row['tps_ratio']:.2f}>={settings['tps_multiplier']},"
        f" price_change_pct={row['price_change_pct']:.2f}<={settings['price_change_pct_max']},"
        f" avg_1h_trade_value={row['avg_1h_trade_value']:.0f}>={settings['avg_1h_trade_value_min']:.0f}"
    )


def run():
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)
    ensure_runtime_schema(conn, detector_config)

    logger.info(
        "detector started: ratio=%.2f tps_multiplier=%.2f price_change_pct_max=%.2f avg_1h_trade_value_min=%.0f cooldown=%ss interval=%ss",
        detector_config.ratio_5m_vs_1h,
        detector_config.tps_multiplier,
        detector_config.price_change_pct_max,
        detector_config.avg_1h_trade_value_min,
        detector_config.cooldown_seconds,
        detector_config.interval_seconds,
    )

    while not shutdown_requested:
        settings = {
            "ratio_5m_vs_1h": detector_config.ratio_5m_vs_1h,
            "tps_multiplier": detector_config.tps_multiplier,
            "price_change_pct_max": detector_config.price_change_pct_max,
            "avg_1h_trade_value_min": detector_config.avg_1h_trade_value_min,
            "cooldown_seconds": detector_config.cooldown_seconds,
            "interval_seconds": detector_config.interval_seconds,
            "webhook_url": detector_config.webhook_url,
        }
        try:
            settings = fetch_runtime_settings()
            candidates = fetch_candidates(settings)
            for row in candidates:
                if was_recently_alerted(row["market"], int(settings["cooldown_seconds"])):
                    logger.debug("alert skipped by cooldown: %s", row["market"])
                    continue
                reason = build_reason(row, settings)
                insert_alert(row, reason)
                send_discord_alert(logger, settings["webhook_url"], row, reason)
                logger.info("alert recorded: %s %s", row["market"], reason)
        except Exception as exc:
            conn.rollback()
            logger.exception("detector error: %s", exc)

        time.sleep(int(settings["interval_seconds"]))
