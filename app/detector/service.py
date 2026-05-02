import signal
import sys
import time

from psycopg2.extras import RealDictCursor

from app.common.config import DbConfig, DetectorConfig
from app.common.db import create_connection
from app.common.logging import build_logger
from app.common.schema import ensure_runtime_schema
from app.detector.notifier import send_discord_alert
from app.detector.queries import (
    FETCH_MARKET_METRICS_SQL,
    FETCH_RULES_SQL,
    FETCH_SETTINGS_SQL,
    INSERT_ALERT_SQL,
    RECENT_ALERT_SQL,
)
from app.detector.rules import RULE_DEFINITION_MAP, build_default_rules, evaluate_rules

logger = build_logger("upbit_detector", "detector.log")
detector_config = DetectorConfig()
default_rules = build_default_rules(detector_config)
conn = create_connection(DbConfig())
shutdown_requested = False


def handle_shutdown(signum, frame):
    global shutdown_requested
    shutdown_requested = True
    logger.info("detector stopping: received signal %s", signum)
    conn.close()
    sys.exit(0)


def fetch_market_metrics():
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(FETCH_MARKET_METRICS_SQL)
        return cursor.fetchall()


def build_default_settings_bundle():
    return {
        "settings": {
            "enabled": True,
            "cooldown_seconds": detector_config.cooldown_seconds,
            "interval_seconds": detector_config.interval_seconds,
            "webhook_enabled": True,
            "webhook_url": detector_config.webhook_url,
        },
        "rules": default_rules,
    }


def fetch_runtime_settings_bundle():
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(FETCH_SETTINGS_SQL)
        settings = cursor.fetchone()
        if settings is None:
            return build_default_settings_bundle()

        cursor.execute(FETCH_RULES_SQL, (settings["id"],))
        rules = cursor.fetchall()
        if not rules:
            rules = default_rules

        return {"settings": settings, "rules": rules}


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
                row["buy_1s_bid_trade_value"],
                reason,
            ),
        )
    conn.commit()


def build_reason(rule_reasons, rules):
    active_labels = [
        RULE_DEFINITION_MAP.get(rule["rule_key"], {}).get("label", rule["rule_key"])
        for rule in rules
        if rule["enabled"]
    ]
    return f"active_rules={', '.join(active_labels)} | " + ", ".join(rule_reasons)


def run():
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)
    ensure_runtime_schema(conn, detector_config, default_rules)

    logger.info(
        "detector started: cooldown=%ss interval=%ss default_rules=%s",
        detector_config.cooldown_seconds,
        detector_config.interval_seconds,
        ", ".join(rule["rule_key"] for rule in default_rules),
    )

    while not shutdown_requested:
        sleep_seconds = detector_config.interval_seconds
        try:
            bundle = fetch_runtime_settings_bundle()
            settings = bundle["settings"]
            rules = bundle["rules"]
            sleep_seconds = int(settings["interval_seconds"])

            if not settings["enabled"]:
                logger.info("detector disabled: skipping evaluation loop")
                time.sleep(sleep_seconds)
                continue

            candidates = fetch_market_metrics()
            for row in candidates:
                passed, rule_reasons = evaluate_rules(row, rules)
                if not passed:
                    continue
                if was_recently_alerted(row["market"], int(settings["cooldown_seconds"])):
                    logger.debug("alert skipped by cooldown: %s", row["market"])
                    continue

                reason = build_reason(rule_reasons, rules)
                insert_alert(row, reason)
                webhook_url = settings["webhook_url"] if settings["webhook_enabled"] else ""
                send_discord_alert(logger, webhook_url, row, reason)
                logger.info("alert recorded: %s %s", row["market"], reason)
        except Exception as exc:
            conn.rollback()
            logger.exception("detector error: %s", exc)

        time.sleep(sleep_seconds)
