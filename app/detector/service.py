import json
import signal
import sys
import time

from psycopg2.extras import RealDictCursor

from app.common.config import DbConfig
from app.common.db import create_connection
from app.common.logging import build_logger
from app.common.schema import ensure_runtime_schema
from app.detector.notifier import send_discord_alert
from app.detector.queries import (
    FETCH_DIP_MARKET_METRICS_SQL,
    FETCH_SPIKE_MARKET_METRICS_SQL,
    FETCH_STRATEGIES_SQL,
    FETCH_STRATEGY_RULES_SQL,
    INSERT_ALERT_SQL,
    RECENT_ALERT_SQL,
)
from app.detector.rules import (
    STRATEGY_DEFINITIONS,
    build_default_strategy_bundle,
    evaluate_rules,
    get_param_threshold,
)

logger = build_logger("upbit_detector", "detector.log")
conn = create_connection(DbConfig())
shutdown_requested = False


def handle_shutdown(signum, frame):
    global shutdown_requested
    shutdown_requested = True
    logger.info("detector stopping: received signal %s", signum)
    conn.close()
    sys.exit(0)


def fetch_runtime_strategies():
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(FETCH_STRATEGIES_SQL)
        strategies = cursor.fetchall()
        bundles = []
        for strategy in strategies:
            cursor.execute(FETCH_STRATEGY_RULES_SQL, (strategy["id"],))
            rules = cursor.fetchall()
            bundles.append({"strategy": strategy, "rules": rules})
        return bundles


def fetch_spike_metrics():
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(FETCH_SPIKE_MARKET_METRICS_SQL)
        return cursor.fetchall()


def fetch_dip_metrics(lookback_minutes: int):
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(FETCH_DIP_MARKET_METRICS_SQL, (lookback_minutes,))
        return cursor.fetchall()


def was_recently_alerted(market, strategy_key, cooldown_seconds):
    with conn.cursor() as cursor:
        cursor.execute(RECENT_ALERT_SQL, (market, strategy_key, cooldown_seconds))
        return cursor.fetchone() is not None


def build_reason(strategy_key, rule_reasons, rules):
    active_labels = []
    for rule in rules:
        if rule["enabled"]:
            for definition in STRATEGY_DEFINITIONS[strategy_key]["rules"]:
                if definition["rule_key"] == rule["rule_key"]:
                    active_labels.append(definition["label"])
                    break
            else:
                active_labels.append(rule["rule_key"])
    return f"active_rules={', '.join(active_labels)} | " + ", ".join(rule_reasons)


def insert_alert(strategy, row, reason):
    details = json.dumps(
        {
            key: value
            for key, value in row.items()
            if key not in {"market"}
        },
        ensure_ascii=False,
    )
    with conn.cursor() as cursor:
        cursor.execute(
            INSERT_ALERT_SQL,
            (
                strategy["id"],
                strategy["strategy_key"],
                row["market"],
                float(row.get("ratio_5m_vs_1h") or 0),
                float(row.get("tps_now") or 0),
                float(row.get("tps_baseline") or 0),
                float(row.get("price_change_pct") or row.get("price_drop_pct") or 0),
                float(row.get("buy_1s_bid_trade_value") or row.get("ask_trade_value") or 0),
                reason,
                details,
            ),
        )
    conn.commit()


def evaluate_spike_strategy(strategy, rules):
    for row in fetch_spike_metrics():
        passed, rule_reasons = evaluate_rules("spike", row, rules)
        if not passed:
            continue
        if was_recently_alerted(row["market"], "spike", int(strategy["cooldown_seconds"])):
            logger.debug("alert skipped by cooldown: strategy=spike market=%s", row["market"])
            continue
        reason = build_reason("spike", rule_reasons, rules)
        insert_alert(strategy, row, reason)
        webhook_url = strategy["webhook_url"] if strategy["webhook_enabled"] else ""
        send_discord_alert(logger, webhook_url, strategy, row, reason)
        logger.info("alert recorded: strategy=spike market=%s %s", row["market"], reason)


def evaluate_dip_buying_strategy(strategy, rules):
    lookback_minutes = int(get_param_threshold(rules, "lookback_minutes", 5))
    for row in fetch_dip_metrics(lookback_minutes):
        passed, rule_reasons = evaluate_rules("dip_buying", row, rules)
        if not passed:
            continue
        if was_recently_alerted(row["market"], "dip_buying", int(strategy["cooldown_seconds"])):
            logger.debug("alert skipped by cooldown: strategy=dip_buying market=%s", row["market"])
            continue
        reason = build_reason("dip_buying", rule_reasons, rules)
        insert_alert(strategy, row, reason)
        webhook_url = strategy["webhook_url"] if strategy["webhook_enabled"] else ""
        send_discord_alert(logger, webhook_url, strategy, row, reason)
        logger.info("alert recorded: strategy=dip_buying market=%s %s", row["market"], reason)


def run():
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)
    ensure_runtime_schema(conn)

    next_run_at = {}
    default_strategy_keys = ", ".join(STRATEGY_DEFINITIONS.keys())
    logger.info("detector started: strategies=%s", default_strategy_keys)

    while not shutdown_requested:
        sleep_seconds = 5
        try:
            bundles = fetch_runtime_strategies()
            if not bundles:
                bundles = [
                    build_default_strategy_bundle("spike"),
                    build_default_strategy_bundle("dip_buying"),
                ]

            now_ts = time.time()
            active_intervals = []

            for bundle in bundles:
                strategy = bundle["strategy"]
                rules = bundle["rules"]
                interval_seconds = int(strategy["interval_seconds"])
                active_intervals.append(interval_seconds)

                if not strategy["enabled"]:
                    continue

                strategy_key = strategy["strategy_key"]
                if next_run_at.get(strategy_key, 0) > now_ts:
                    continue

                if strategy_key == "spike":
                    evaluate_spike_strategy(strategy, rules)
                elif strategy_key == "dip_buying":
                    evaluate_dip_buying_strategy(strategy, rules)
                else:
                    logger.warning("unknown strategy skipped: %s", strategy_key)

                next_run_at[strategy_key] = now_ts + interval_seconds

            if active_intervals:
                sleep_seconds = max(1, min(active_intervals))
        except Exception as exc:
            conn.rollback()
            logger.exception("detector error: %s", exc)

        time.sleep(sleep_seconds)
