import base64
from functools import wraps
from urllib.parse import quote

from flask import Flask, Response, redirect, render_template, request
from psycopg2.extras import RealDictCursor

from app.common.config import DbConfig, DetectorWebConfig
from app.common.db import create_connection
from app.common.schema import ensure_market_sync_schema
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
web_config = DetectorWebConfig()
TEN_MILLION_KRW = 10_000_000
TEN_MILLION_RULE_KEYS = {"buy_1s_bid_trade_value", "ask_trade_value"}
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
                int(form.get("interval_seconds", context["strategy"]["interval_seconds"])),
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


def run():
    app.run(host=web_config.host, port=web_config.port, debug=False)
