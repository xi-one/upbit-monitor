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
    FETCH_BOT_MARKET_METRICS_SQL,
    FETCH_DIP_MARKET_METRICS_SQL,
    FETCH_SPIKE_MARKET_METRICS_SQL,
    FETCH_STRATEGIES_SQL,
    FETCH_STRATEGY_RULES_SQL,
    INSERT_ALERT_SQL,
    MARK_ALL_INACTIVE_BOT_DETECTION_STATUS_SQL,
    MARK_INACTIVE_BOT_DETECTION_STATUS_SQL,
    RECENT_ALERT_SQL,
    UPSERT_BOT_DETECTION_STATUS_SQL,
)
from app.detector.rules import (
    STRATEGY_DEFINITIONS,
    build_default_strategy_bundle,
    evaluate_rules,
    get_param_threshold,
    normalize_rule_key,
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


def fetch_bot_metrics(
    lookback_seconds: int,
    trade_value_min: float,
    trade_value_max: float,
    max_pair_gap_seconds: float,
):
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            FETCH_BOT_MARKET_METRICS_SQL,
            (
                lookback_seconds,
                trade_value_min,
                trade_value_max,
                max_pair_gap_seconds,
                lookback_seconds,
            ),
        )
        return cursor.fetchall()


def was_recently_alerted(market, strategy_key, cooldown_seconds):
    with conn.cursor() as cursor:
        cursor.execute(RECENT_ALERT_SQL, (market, strategy_key, cooldown_seconds))
        return cursor.fetchone() is not None


def build_reason(strategy_key, rule_reasons, rules):
    active_labels = []
    definition_map = {
        definition["rule_key"]: definition
        for definition in STRATEGY_DEFINITIONS[strategy_key]["rules"]
    }
    for rule in rules:
        rule_key = normalize_rule_key(rule["rule_key"])
        if rule["enabled"] and rule_key in definition_map:
            active_labels.append(definition_map[rule_key]["label"])
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
                float(row.get("tps_now") or row.get("tps") or 0),
                float(row.get("tps_baseline") or 0),
                float(row.get("price_change_pct") or row.get("price_drop_pct") or row.get("price_range_pct") or 0),
                float(
                    row.get("buy_1m_bid_trade_value")
                    or row.get("buy_2m_bid_trade_value")
                    or row.get("buy_1s_bid_trade_value")
                    or row.get("ask_trade_value")
                    or row.get("total_trade_value")
                    or 0
                ),
                reason,
                details,
            ),
        )
    conn.commit()


def upsert_bot_detection_status(row, reason):
    metrics = json.dumps(
        {
            key: value
            for key, value in row.items()
            if key not in {"market"}
        },
        ensure_ascii=False,
    )
    with conn.cursor() as cursor:
        cursor.execute(
            UPSERT_BOT_DETECTION_STATUS_SQL,
            (
                row["market"],
                float(row.get("buy_sell_pair_count") or 0),
                float(row.get("tps") or 0),
                float(row["price_range_pct"]) if row.get("price_range_pct") is not None else None,
                float(row["price_increase_pct"]) if row.get("price_increase_pct") is not None else None,
                float(row.get("total_trade_value") or 0),
                reason,
                metrics,
            ),
        )


def mark_inactive_bot_detection_status(active_markets):
    with conn.cursor() as cursor:
        if active_markets:
            cursor.execute(MARK_INACTIVE_BOT_DETECTION_STATUS_SQL, (active_markets,))
        else:
            cursor.execute(MARK_ALL_INACTIVE_BOT_DETECTION_STATUS_SQL)


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


def evaluate_bot_detection_strategy(strategy, rules):
    lookback_seconds = int(get_param_threshold(rules, "lookback_seconds", 30))
    trade_value_min = float(get_param_threshold(rules, "trade_value_min", 0))
    trade_value_max = float(get_param_threshold(rules, "trade_value_max", 50000))
    max_pair_gap_seconds = float(get_param_threshold(rules, "max_pair_gap_seconds", 3))
    active_markets = []
    for row in fetch_bot_metrics(lookback_seconds, trade_value_min, trade_value_max, max_pair_gap_seconds):
        passed, rule_reasons = evaluate_rules("bot_detection", row, rules)
        if not passed:
            continue
        active_markets.append(row["market"])
        reason = build_reason("bot_detection", rule_reasons, rules)
        upsert_bot_detection_status(row, reason)
        if was_recently_alerted(row["market"], "bot_detection", int(strategy["cooldown_seconds"])):
            logger.debug("alert skipped by cooldown: strategy=bot_detection market=%s", row["market"])
            continue
        insert_alert(strategy, row, reason)
        webhook_url = strategy["webhook_url"] if strategy["webhook_enabled"] else ""
        send_discord_alert(logger, webhook_url, strategy, row, reason)
        logger.info("alert recorded: strategy=bot_detection market=%s %s", row["market"], reason)
    mark_inactive_bot_detection_status(active_markets)
    conn.commit()


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
                    build_default_strategy_bundle("bot_detection"),
                ]

            now_ts = time.time()
            active_intervals = []

            for bundle in bundles:
                strategy = bundle["strategy"]
                rules = bundle["rules"]
                interval_seconds = int(strategy["interval_seconds"])
                active_intervals.append(interval_seconds)

                strategy_key = strategy["strategy_key"]
                if not strategy["enabled"]:
                    if strategy_key == "bot_detection" and next_run_at.get(strategy_key, 0) <= now_ts:
                        mark_inactive_bot_detection_status([])
                        conn.commit()
                        next_run_at[strategy_key] = now_ts + interval_seconds
                    continue

                if next_run_at.get(strategy_key, 0) > now_ts:
                    continue

                if strategy_key == "spike":
                    evaluate_spike_strategy(strategy, rules)
                elif strategy_key == "dip_buying":
                    evaluate_dip_buying_strategy(strategy, rules)
                elif strategy_key == "bot_detection":
                    evaluate_bot_detection_strategy(strategy, rules)
                else:
                    logger.warning("unknown strategy skipped: %s", strategy_key)

                next_run_at[strategy_key] = now_ts + interval_seconds

            if active_intervals:
                sleep_seconds = max(1, min(active_intervals))
        except Exception as exc:
            conn.rollback()
            logger.exception("detector error: %s", exc)

        time.sleep(sleep_seconds)
