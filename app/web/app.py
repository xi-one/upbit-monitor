import base64
from functools import wraps

from flask import Flask, Response, redirect, render_template, request, url_for
from psycopg2.extras import RealDictCursor

from app.common.config import DbConfig, DetectorConfig, DetectorWebConfig
from app.common.db import create_connection
from app.common.schema import ensure_runtime_schema
from app.detector.queries import FETCH_SETTINGS_SQL, INSERT_SETTINGS_SQL

app = Flask(__name__, template_folder="templates")
db_conn = create_connection(DbConfig())
default_detector_settings = DetectorConfig()
web_config = DetectorWebConfig()
ensure_runtime_schema(db_conn, default_detector_settings)


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


def fetch_settings():
    with db_conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(FETCH_SETTINGS_SQL)
        return cursor.fetchone()


@app.route("/")
@requires_auth
def index():
    settings = fetch_settings()
    return render_template("settings.html", settings=settings, saved=request.args.get("saved") == "1")


@app.route("/save", methods=["POST"])
@requires_auth
def save():
    form = request.form
    with db_conn.cursor() as cursor:
        cursor.execute(
            INSERT_SETTINGS_SQL,
            (
                float(form["ratio_5m_vs_1h"]),
                float(form["tps_multiplier"]),
                float(form["price_change_pct_max"]),
                float(form["avg_1h_trade_value_min"]),
                int(form["cooldown_seconds"]),
                int(form["interval_seconds"]),
                form.get("webhook_url", "").strip(),
            ),
        )
    db_conn.commit()
    return redirect(url_for("index", saved=1))


def run():
    app.run(host=web_config.host, port=web_config.port, debug=False)
