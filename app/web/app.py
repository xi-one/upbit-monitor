import base64
from functools import wraps
from urllib.parse import quote

from flask import Flask, Response, redirect, render_template, request, url_for
from psycopg2.extras import RealDictCursor

from app.common.config import DbConfig, DetectorConfig, DetectorWebConfig
from app.common.db import create_connection
from app.common.schema import ensure_market_sync_schema
from app.detector.queries import FETCH_RULES_SQL, FETCH_SETTINGS_SQL, INSERT_RULE_SQL, INSERT_SETTINGS_SQL
from app.detector.rules import RULE_DEFINITIONS, RULE_KEY_ALIASES, build_default_rules, normalize_rule_key
from app.markets.service import fetch_market_sync_status, refresh_market_universe

app = Flask(__name__, template_folder="templates")
db_conn = create_connection(DbConfig())
db_conn.autocommit = True
ensure_market_sync_schema(db_conn)
default_detector_settings = DetectorConfig()
default_rules = build_default_rules(default_detector_settings)
web_config = DetectorWebConfig()
TEN_MILLION_KRW = 10_000_000
TEN_MILLION_RULE_KEYS = {"buy_1s_bid_trade_value"}


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


def fetch_settings_bundle():
    with db_conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(FETCH_SETTINGS_SQL)
        settings = cursor.fetchone()
        if settings is None:
            return None

        cursor.execute(FETCH_RULES_SQL, (settings["id"],))
        rules = cursor.fetchall()
        return {"settings": settings, "rules": rules}


def _format_rule_for_display(rule: dict) -> dict:
    formatted_rule = dict(rule)
    raw_threshold_value = float(formatted_rule["threshold_value"])
    formatted_rule["raw_threshold_value"] = raw_threshold_value
    formatted_rule["threshold_step"] = "0.01"
    formatted_rule["threshold_unit"] = ""

    if formatted_rule["rule_key"] in TEN_MILLION_RULE_KEYS:
        formatted_rule["threshold_value"] = raw_threshold_value / TEN_MILLION_KRW
        formatted_rule["threshold_step"] = "0.1"
        formatted_rule["threshold_unit"] = "천만원"
    else:
        formatted_rule["threshold_value"] = raw_threshold_value

    return formatted_rule


def _parse_threshold_value(rule_key: str, form_value: str) -> float:
    threshold_value = float(form_value)
    if rule_key in TEN_MILLION_RULE_KEYS:
        return threshold_value * TEN_MILLION_KRW
    return threshold_value


def _rule_form_keys(rule_key: str) -> list[str]:
    legacy_rule_keys = [legacy for legacy, current in RULE_KEY_ALIASES.items() if current == rule_key]
    return [rule_key, *legacy_rule_keys]


def _get_rule_form_value(form, rule_key: str, suffix: str, default: str) -> str:
    for candidate_rule_key in _rule_form_keys(rule_key):
        field_name = f"{candidate_rule_key}__{suffix}"
        value = form.get(field_name)
        if value is not None:
            return value
    return default


def _save_settings_snapshot(form) -> None:
    current_context = build_render_context()
    current_rule_map = {rule["rule_key"]: rule for rule in current_context["rules"]}

    with db_conn.cursor() as cursor:
        cursor.execute(
            INSERT_SETTINGS_SQL,
            (
                form.get("enabled") == "on",
                int(form.get("cooldown_seconds", current_context["settings"]["cooldown_seconds"])),
                int(form.get("interval_seconds", current_context["settings"]["interval_seconds"])),
                form.get("webhook_enabled") == "on",
                form.get("webhook_url", current_context["settings"]["webhook_url"]).strip(),
            ),
        )
        settings_id = cursor.fetchone()[0]

        for definition in RULE_DEFINITIONS:
            rule_key = definition["rule_key"]
            current_rule = current_rule_map.get(rule_key, {})
            operator_default = current_rule.get("operator", definition["operator_default"])
            threshold_default = str(current_rule.get("threshold_value", 0))

            cursor.execute(
                INSERT_RULE_SQL,
                (
                    settings_id,
                    rule_key,
                    definition["label"],
                    any(form.get(f"{candidate}__enabled") == "on" for candidate in _rule_form_keys(rule_key)),
                    _get_rule_form_value(form, rule_key, "operator", operator_default),
                    _parse_threshold_value(
                        rule_key,
                        _get_rule_form_value(form, rule_key, "threshold", threshold_default),
                    ),
                    "{}",
                    definition["sort_order"],
                ),
            )
    db_conn.commit()


def build_render_context():
    bundle = fetch_settings_bundle()
    if bundle is None:
        return {
            "settings": {
                "enabled": True,
                "cooldown_seconds": default_detector_settings.cooldown_seconds,
                "interval_seconds": default_detector_settings.interval_seconds,
                "webhook_enabled": True,
                "webhook_url": default_detector_settings.webhook_url,
                "updated_at": None,
            },
            "rules": [_format_rule_for_display(rule) for rule in default_rules],
            "rule_definitions": RULE_DEFINITIONS,
            "market_status": fetch_market_sync_status(db_conn),
        }

    rule_map = {}
    for rule in bundle["rules"]:
        normalized_rule_key = normalize_rule_key(rule["rule_key"])
        rule = dict(rule)
        rule["rule_key"] = normalized_rule_key
        rule_map[normalized_rule_key] = rule
    rules_for_render = []
    for definition in RULE_DEFINITIONS:
        rules_for_render.append(
            _format_rule_for_display(
                rule_map.get(
                definition["rule_key"],
                {
                    "rule_key": definition["rule_key"],
                    "label": definition["label"],
                    "enabled": True,
                    "operator": definition["operator_default"],
                    "threshold_value": 0,
                    "sort_order": definition["sort_order"],
                },
            )
            )
        )

    return {
        "settings": bundle["settings"],
        "rules": rules_for_render,
        "rule_definitions": RULE_DEFINITIONS,
        "market_status": fetch_market_sync_status(db_conn),
    }


@app.route("/", methods=["GET", "POST"])
@requires_auth
def index():
    if request.method == "POST":
        _save_settings_snapshot(request.form)
        return redirect("/detector-admin/?saved=1")

    context = build_render_context()
    return render_template(
        "settings.html",
        settings=context["settings"],
        rules=context["rules"],
        rule_definitions=context["rule_definitions"],
        market_status=context["market_status"],
        saved=request.args.get("saved") == "1",
        markets_refreshed=request.args.get("markets_refreshed") == "1",
        market_refresh_error=request.args.get("market_refresh_error", "").strip(),
    )


@app.route("/save", methods=["POST"])
@requires_auth
def save():
    _save_settings_snapshot(request.form)
    return redirect("/detector-admin/?saved=1")


@app.route("/refresh-markets", methods=["POST"])
@requires_auth
def refresh_markets():
    result = refresh_market_universe()
    if result["ok"]:
        return redirect("/detector-admin/?markets_refreshed=1")
    return redirect(f"/detector-admin/?market_refresh_error={quote(result['error'])}")


def run():
    app.run(host=web_config.host, port=web_config.port, debug=False)
