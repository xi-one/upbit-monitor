import base64
from functools import wraps
from urllib.parse import quote

from flask import Flask, Response, jsonify, redirect, render_template, request
from psycopg2.extras import RealDictCursor

from app.common.config import DbConfig, DetectorWebConfig
from app.common.db import create_connection
from app.common.schema import ensure_runtime_schema
from app.detector.queries import (
    DELETE_STRATEGY_RULES_SQL,
    FETCH_STRATEGIES_SQL,
    FETCH_STRATEGY_RULES_SQL,
    FETCH_STRATEGY_SQL,
    INSERT_STRATEGY_RULE_SQL,
    UPSERT_STRATEGY_SQL,
)
from app.detector.rules import STRATEGY_DEFINITIONS, build_default_strategy_bundle, get_rule_definitions
from app.markets.service import fetch_market_sync_status, refresh_market_universe

app = Flask(__name__, template_folder="templates")
db_conn = create_connection(DbConfig())
db_conn.autocommit = True
ensure_runtime_schema(db_conn)
web_config = DetectorWebConfig()
TEN_MILLION_KRW = 10_000_000
TEN_MILLION_RULE_KEYS = {"buy_1s_bid_trade_value", "buy_1m_bid_trade_value", "buy_2m_bid_trade_value", "ask_trade_value"}
PARAM_ONLY_RULE_KEYS = {
    "lookback_minutes",
    "lookback_seconds",
    "trade_value_min",
    "trade_value_max",
    "small_trade_value_max",
    "max_pair_gap_seconds",
}


def _check_auth(auth_header: str) -> bool:
    if not auth_header or not auth_header.startswith("Basic "):
        return False
    try:
        encoded = auth_header.split(" ", 1)[1]
        decoded = base64.b64decode(encoded).decode("utf-8")
        username, password = decoded.split(":", 1)
        return username == web_config.username and password == web_config.password
    except Exception:
        return False


def requires_auth(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if _check_auth(request.headers.get("Authorization", "")):
            return view(*args, **kwargs)
        return Response(
            "Authentication required",
            401,
            {"WWW-Authenticate": 'Basic realm="Detector Settings"'},
        )

    return wrapped


def _strategy_path(strategy_key: str) -> str:
    if strategy_key == "dip_buying":
        return "/detector-admin/dip-buying"
    if strategy_key == "bot_detection":
        return "/detector-admin/bot-detection"
    return f"/detector-admin/{strategy_key}"


def _format_rule_for_display(rule: dict) -> dict:
    formatted_rule = dict(rule)
    raw_threshold_value = float(formatted_rule["threshold_value"])
    formatted_rule["raw_threshold_value"] = raw_threshold_value
    formatted_rule["threshold_step"] = "0.01"
    formatted_rule["threshold_unit"] = ""
    formatted_rule["show_operator"] = formatted_rule["rule_key"] not in PARAM_ONLY_RULE_KEYS

    if formatted_rule["rule_key"] in TEN_MILLION_RULE_KEYS:
        formatted_rule["threshold_value"] = raw_threshold_value / TEN_MILLION_KRW
        formatted_rule["threshold_step"] = "0.1"
        formatted_rule["threshold_unit"] = "천만원"
    elif formatted_rule["rule_key"] == "lookback_minutes":
        formatted_rule["threshold_value"] = int(raw_threshold_value)
        formatted_rule["threshold_step"] = "1"
        formatted_rule["threshold_unit"] = "분"
    elif formatted_rule["rule_key"] == "lookback_seconds":
        formatted_rule["threshold_value"] = int(raw_threshold_value)
        formatted_rule["threshold_step"] = "1"
        formatted_rule["threshold_unit"] = "초"
    elif formatted_rule["rule_key"] in {"trade_value_min", "trade_value_max", "small_trade_value_max"}:
        formatted_rule["threshold_value"] = int(raw_threshold_value)
        formatted_rule["threshold_step"] = "1000"
        formatted_rule["threshold_unit"] = "원"
    elif formatted_rule["rule_key"] == "max_pair_gap_seconds":
        formatted_rule["threshold_value"] = raw_threshold_value
        formatted_rule["threshold_step"] = "0.1"
        formatted_rule["threshold_unit"] = "초"
    elif formatted_rule["rule_key"] in {"tps_now", "tps_now_max", "min_tps", "max_tps"}:
        formatted_rule["threshold_value"] = raw_threshold_value
        formatted_rule["threshold_step"] = "0.1"
        formatted_rule["threshold_unit"] = "TPS"
    elif formatted_rule["rule_key"] in {"price_change_pct_min", "price_change_pct", "max_price_increase_pct"}:
        formatted_rule["threshold_value"] = raw_threshold_value
        formatted_rule["threshold_step"] = "0.1"
        formatted_rule["threshold_unit"] = "%"
    else:
        formatted_rule["threshold_value"] = raw_threshold_value

    return formatted_rule


def _parse_threshold_value(rule_key: str, form_value: str) -> float:
    threshold_value = float(form_value)
    if rule_key in TEN_MILLION_RULE_KEYS:
        return threshold_value * TEN_MILLION_KRW
    return threshold_value


def fetch_strategy_bundle(strategy_key: str):
    with db_conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(FETCH_STRATEGY_SQL, (strategy_key,))
        strategy = cursor.fetchone()
        if strategy is None:
            return None
        cursor.execute(FETCH_STRATEGY_RULES_SQL, (strategy["id"],))
        rules = cursor.fetchall()
        return {"strategy": strategy, "rules": rules}


def fetch_strategy_tabs():
    with db_conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(FETCH_STRATEGIES_SQL)
        rows = cursor.fetchall()
    tabs = []
    for row in rows:
        tabs.append(
            {
                "strategy_key": row["strategy_key"],
                "name": row["name"],
                "path": _strategy_path(row["strategy_key"]),
            }
        )
    existing_keys = {tab["strategy_key"] for tab in tabs}
    for key, definition in STRATEGY_DEFINITIONS.items():
        if key not in existing_keys:
            tabs.append({"strategy_key": key, "name": definition["name"], "path": _strategy_path(key)})
    return tabs


def build_render_context(strategy_key: str):
    bundle = fetch_strategy_bundle(strategy_key)
    strategy_definition = STRATEGY_DEFINITIONS[strategy_key]
    rule_definitions = get_rule_definitions(strategy_key)

    if bundle is None:
        bundle = build_default_strategy_bundle(strategy_key)

    rule_map = {rule["rule_key"]: dict(rule) for rule in bundle["rules"]}
    default_rule_map = {
        rule["rule_key"]: dict(rule)
        for rule in build_default_strategy_bundle(strategy_key)["rules"]
    }
    rules_for_render = []
    for definition in rule_definitions:
        rules_for_render.append(
            _format_rule_for_display(
                rule_map.get(
                    definition["rule_key"],
                    default_rule_map[definition["rule_key"]],
                )
            )
        )

    return {
        "strategy": bundle["strategy"],
        "rules": rules_for_render,
        "rule_definitions": rule_definitions,
        "strategy_definition": strategy_definition,
        "market_status": fetch_market_sync_status(db_conn),
        "tabs": fetch_strategy_tabs(),
        "form_action": _strategy_path(strategy_key),
    }


def _serialize_datetime(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def fetch_active_bot_statuses():
    with db_conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """
            SELECT
                s.market,
                COALESCE(m.korean_name, s.market) AS korean_name,
                COALESCE(m.english_name, '') AS english_name,
                s.first_detected_at,
                s.last_detected_at,
                s.buy_sell_pair_count,
                s.tps,
                s.price_range_pct,
                s.price_increase_pct,
                s.total_trade_value,
                s.reason
            FROM bot_detection_status s
            LEFT JOIN monitored_markets m ON m.market = s.market
            WHERE s.active = TRUE
            ORDER BY s.buy_sell_pair_count DESC, s.tps DESC, s.last_detected_at DESC, s.market ASC
            """
        )
        rows = cursor.fetchall()

    return [
        {
            "market": row["market"],
            "korean_name": row["korean_name"],
            "english_name": row["english_name"],
            "first_detected_at": _serialize_datetime(row["first_detected_at"]),
            "last_detected_at": _serialize_datetime(row["last_detected_at"]),
            "buy_sell_pair_count": float(row["buy_sell_pair_count"] or 0),
            "tps": float(row["tps"] or 0),
            "price_range_pct": float(row["price_range_pct"]) if row["price_range_pct"] is not None else None,
            "price_increase_pct": float(row["price_increase_pct"]) if row["price_increase_pct"] is not None else None,
            "total_trade_value": float(row["total_trade_value"] or 0),
            "reason": row["reason"],
        }
        for row in rows
    ]


def fetch_orderbook_wall_statuses():
    with db_conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """
            SELECT
                s.market,
                COALESCE(m.korean_name, s.market) AS korean_name,
                COALESCE(m.english_name, '') AS english_name,
                s.active,
                s.breached,
                s.first_detected_at,
                s.last_detected_at,
                s.last_breached_at,
                s.breached_until,
                s.ask_price,
                s.ask_size,
                s.ask_value_krw,
                s.total_ask_value_krw,
                s.concentration_ratio,
                s.previous_ask_price,
                s.previous_ask_size,
                s.previous_ask_value_krw,
                s.drop_pct,
                s.bid_trade_value_at_wall,
                s.breach_confirm_ratio,
                s.acc_trade_price_24h,
                s.orderbook_ts,
                s.updated_at
            FROM orderbook_wall_status s
            LEFT JOIN monitored_markets m ON m.market = s.market
            WHERE s.active = TRUE
               OR (s.breached = TRUE AND s.breached_until >= statement_timestamp())
            ORDER BY
                s.breached DESC,
                s.ask_value_krw DESC,
                s.concentration_ratio DESC,
                s.acc_trade_price_24h DESC NULLS LAST,
                s.market ASC
            LIMIT 200
            """
        )
        rows = cursor.fetchall()

    return [
        {
            "market": row["market"],
            "korean_name": row["korean_name"],
            "english_name": row["english_name"],
            "active": bool(row["active"]),
            "breached": bool(row["breached"]),
            "first_detected_at": _serialize_datetime(row["first_detected_at"]),
            "last_detected_at": _serialize_datetime(row["last_detected_at"]),
            "last_breached_at": _serialize_datetime(row["last_breached_at"]),
            "breached_until": _serialize_datetime(row["breached_until"]),
            "ask_price": float(row["ask_price"]) if row["ask_price"] is not None else None,
            "ask_size": float(row["ask_size"]) if row["ask_size"] is not None else None,
            "ask_value_krw": float(row["ask_value_krw"] or 0),
            "total_ask_value_krw": float(row["total_ask_value_krw"] or 0),
            "concentration_ratio": float(row["concentration_ratio"] or 0),
            "previous_ask_price": float(row["previous_ask_price"]) if row["previous_ask_price"] is not None else None,
            "previous_ask_size": float(row["previous_ask_size"]) if row["previous_ask_size"] is not None else None,
            "previous_ask_value_krw": float(row["previous_ask_value_krw"]) if row["previous_ask_value_krw"] is not None else None,
            "drop_pct": float(row["drop_pct"]) if row["drop_pct"] is not None else None,
            "bid_trade_value_at_wall": float(row["bid_trade_value_at_wall"]) if row["bid_trade_value_at_wall"] is not None else None,
            "breach_confirm_ratio": float(row["breach_confirm_ratio"]) if row["breach_confirm_ratio"] is not None else None,
            "acc_trade_price_24h": float(row["acc_trade_price_24h"]) if row["acc_trade_price_24h"] is not None else None,
            "orderbook_ts": _serialize_datetime(row["orderbook_ts"]),
            "updated_at": _serialize_datetime(row["updated_at"]),
        }
        for row in rows
    ]


def fetch_orderbook_wall_settings():
    with db_conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """
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
                cooldown_seconds,
                updated_at
            FROM orderbook_wall_settings
            WHERE id = 1
            """
        )
        row = cursor.fetchone()

    return {
        "enabled": bool(row["enabled"]),
        "orderbook_depth": int(row["orderbook_depth"]),
        "min_wall_value_krw": float(row["min_wall_value_krw"]),
        "min_concentration_ratio": float(row["min_concentration_ratio"]),
        "min_concentration_pct": float(row["min_concentration_ratio"]) * 100,
        "drop_alert_pct": float(row["drop_alert_pct"]),
        "breach_confirm_window_seconds": float(row["breach_confirm_window_seconds"]),
        "breach_confirm_bid_ratio": float(row["breach_confirm_bid_ratio"]),
        "breach_confirm_bid_pct": float(row["breach_confirm_bid_ratio"]) * 100,
        "breach_price_tolerance_pct": float(row["breach_price_tolerance_pct"]),
        "breach_display_seconds": int(row["breach_display_seconds"]),
        "webhook_enabled": bool(row["webhook_enabled"]),
        "webhook_url": row["webhook_url"],
        "cooldown_seconds": int(row["cooldown_seconds"]),
        "updated_at": row["updated_at"],
    }


def save_orderbook_wall_settings(form) -> None:
    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO orderbook_wall_settings (
                id,
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
                cooldown_seconds,
                updated_at
            )
            VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, statement_timestamp())
            ON CONFLICT (id) DO UPDATE SET
                enabled = EXCLUDED.enabled,
                orderbook_depth = EXCLUDED.orderbook_depth,
                min_wall_value_krw = EXCLUDED.min_wall_value_krw,
                min_concentration_ratio = EXCLUDED.min_concentration_ratio,
                drop_alert_pct = EXCLUDED.drop_alert_pct,
                breach_confirm_window_seconds = EXCLUDED.breach_confirm_window_seconds,
                breach_confirm_bid_ratio = EXCLUDED.breach_confirm_bid_ratio,
                breach_price_tolerance_pct = EXCLUDED.breach_price_tolerance_pct,
                breach_display_seconds = EXCLUDED.breach_display_seconds,
                webhook_enabled = EXCLUDED.webhook_enabled,
                webhook_url = EXCLUDED.webhook_url,
                cooldown_seconds = EXCLUDED.cooldown_seconds,
                updated_at = EXCLUDED.updated_at
            """,
            (
                form.get("enabled") == "on",
                max(1, int(form.get("orderbook_depth", 15))),
                float(form.get("min_wall_value_krw", 50000000)),
                float(form.get("min_concentration_pct", 55)) / 100.0,
                float(form.get("drop_alert_pct", 70)),
                max(0.1, float(form.get("breach_confirm_window_seconds", 3))),
                float(form.get("breach_confirm_bid_pct", 50)) / 100.0,
                float(form.get("breach_price_tolerance_pct", 0.1)),
                max(1, int(form.get("breach_display_seconds", 60))),
                form.get("webhook_enabled") == "on",
                form.get("webhook_url", "").strip(),
                max(0, int(form.get("cooldown_seconds", 300))),
            ),
        )
    db_conn.commit()


def save_strategy(strategy_key: str, form) -> None:
    context = build_render_context(strategy_key)
    strategy_definition = STRATEGY_DEFINITIONS[strategy_key]
    current_rule_map = {rule["rule_key"]: rule for rule in context["rules"]}

    with db_conn.cursor() as cursor:
        cursor.execute(
            UPSERT_STRATEGY_SQL,
            (
                strategy_key,
                strategy_definition["name"],
                form.get("enabled") == "on",
                int(form.get("cooldown_seconds", context["strategy"]["cooldown_seconds"])),
                max(1, int(form.get("interval_seconds", context["strategy"]["interval_seconds"]))),
                form.get("webhook_enabled") == "on",
                form.get("webhook_url", context["strategy"]["webhook_url"]).strip(),
            ),
        )
        strategy_id = cursor.fetchone()[0]
        cursor.execute(DELETE_STRATEGY_RULES_SQL, (strategy_id,))

        for definition in get_rule_definitions(strategy_key):
            rule_key = definition["rule_key"]
            current_rule = current_rule_map.get(rule_key, {})
            operator_default = current_rule.get("operator", definition["operator_default"])
            threshold_default = str(current_rule.get("threshold_value", 0))

            cursor.execute(
                INSERT_STRATEGY_RULE_SQL,
                (
                    strategy_id,
                    rule_key,
                    definition["label"],
                    form.get(f"{rule_key}__enabled") == "on",
                    form.get(f"{rule_key}__operator", operator_default),
                    _parse_threshold_value(rule_key, form.get(f"{rule_key}__threshold", threshold_default)),
                    "{}",
                    definition["sort_order"],
                ),
            )
    db_conn.commit()


@app.route("/")
@requires_auth
def root():
    return redirect("/detector-admin/spike")


@app.route("/spike", methods=["GET", "POST"])
@requires_auth
def spike():
    if request.method == "POST":
        save_strategy("spike", request.form)
        return redirect("/detector-admin/spike?saved=1")

    context = build_render_context("spike")
    return render_template(
        "settings.html",
        strategy=context["strategy"],
        rules=context["rules"],
        rule_definitions=context["rule_definitions"],
        strategy_definition=context["strategy_definition"],
        market_status=context["market_status"],
        tabs=context["tabs"],
        form_action=context["form_action"],
        current_strategy_key="spike",
        saved=request.args.get("saved") == "1",
        markets_refreshed=request.args.get("markets_refreshed") == "1",
        market_refresh_error=request.args.get("market_refresh_error", "").strip(),
    )


@app.route("/dip-buying", methods=["GET", "POST"])
@requires_auth
def dip_buying():
    if request.method == "POST":
        save_strategy("dip_buying", request.form)
        return redirect("/detector-admin/dip-buying?saved=1")

    context = build_render_context("dip_buying")
    return render_template(
        "settings.html",
        strategy=context["strategy"],
        rules=context["rules"],
        rule_definitions=context["rule_definitions"],
        strategy_definition=context["strategy_definition"],
        market_status=context["market_status"],
        tabs=context["tabs"],
        form_action=context["form_action"],
        current_strategy_key="dip_buying",
        saved=request.args.get("saved") == "1",
        markets_refreshed=request.args.get("markets_refreshed") == "1",
        market_refresh_error=request.args.get("market_refresh_error", "").strip(),
    )


@app.route("/bot_detection", methods=["GET", "POST"])
@app.route("/bot-detection", methods=["GET", "POST"])
@requires_auth
def bot_detection():
    if request.method == "POST":
        save_strategy("bot_detection", request.form)
        return redirect("/detector-admin/bot-detection?saved=1")

    context = build_render_context("bot_detection")
    return render_template(
        "settings.html",
        strategy=context["strategy"],
        rules=context["rules"],
        rule_definitions=context["rule_definitions"],
        strategy_definition=context["strategy_definition"],
        market_status=context["market_status"],
        tabs=context["tabs"],
        form_action=context["form_action"],
        current_strategy_key="bot_detection",
        saved=request.args.get("saved") == "1",
        markets_refreshed=request.args.get("markets_refreshed") == "1",
        market_refresh_error=request.args.get("market_refresh_error", "").strip(),
    )


@app.route("/save", methods=["POST"])
@requires_auth
def legacy_save():
    save_strategy("spike", request.form)
    return redirect("/detector-admin/spike?saved=1")


@app.route("/refresh-markets", methods=["POST"])
@requires_auth
def refresh_markets():
    result = refresh_market_universe()
    target_strategy = request.args.get("strategy", "spike")
    base = _strategy_path(target_strategy if target_strategy in STRATEGY_DEFINITIONS else "spike")
    if result["ok"]:
        return redirect(f"{base}?markets_refreshed=1")
    return redirect(f"{base}?market_refresh_error={quote(result['error'])}")


@app.route("/bot-dashboard")
@requires_auth
def bot_dashboard():
    return render_template("bot_dashboard.html")


@app.route("/orderbook-dashboard")
@requires_auth
def orderbook_dashboard():
    return render_template("orderbook_dashboard.html")


@app.route("/orderbook-settings", methods=["GET", "POST"])
@requires_auth
def orderbook_settings():
    if request.method == "POST":
        save_orderbook_wall_settings(request.form)
        return redirect("/detector-admin/orderbook-settings?saved=1")

    return render_template(
        "orderbook_settings.html",
        settings=fetch_orderbook_wall_settings(),
        tabs=fetch_strategy_tabs(),
        saved=request.args.get("saved") == "1",
    )


@app.route("/api/bot-status")
@requires_auth
def bot_status_api():
    rows = fetch_active_bot_statuses()
    return jsonify(
        {
            "items": rows,
            "count": len(rows),
        }
    )


@app.route("/api/orderbook-walls")
@requires_auth
def orderbook_walls_api():
    rows = fetch_orderbook_wall_statuses()
    breached_count = sum(1 for row in rows if row["breached"])
    active_count = sum(1 for row in rows if row["active"])
    return jsonify(
        {
            "items": rows,
            "count": len(rows),
            "active_count": active_count,
            "breached_count": breached_count,
        }
    )


def run():
    app.run(host=web_config.host, port=web_config.port, debug=False)
