import logging
import time as time_module
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import requests
from psycopg2.extras import RealDictCursor

from app.markets.service import format_market_label

KST = ZoneInfo("Asia/Seoul")

FETCH_DAILY_MARKET_MOVES_SQL = """
WITH monitored AS (
    SELECT market, korean_name, symbol
    FROM monitored_markets
),
baseline AS (
    SELECT DISTINCT ON (t.market)
        t.market,
        t.price::double precision AS baseline_price
    FROM trades t
    JOIN monitored m ON m.market = t.market
    WHERE t.time >= %(start_at)s - interval '10 minutes'
      AND t.time < %(start_at)s
    ORDER BY t.market, t.time DESC
),
window_trades AS (
    SELECT t.time, t.market, t.price
    FROM trades t
    JOIN monitored m ON m.market = t.market
    WHERE t.time >= %(start_at)s
      AND t.time < %(end_at)s
),
metrics AS (
    SELECT
        m.market,
        m.korean_name,
        m.symbol,
        b.baseline_price,
        MAX(w.price) FILTER (WHERE w.time < %(immediate_end_at)s)::double precision AS immediate_peak_price,
        (ARRAY_AGG(w.price ORDER BY w.time DESC)
            FILTER (WHERE w.time < %(immediate_end_at)s))[1]::double precision AS immediate_close_price,
        MAX(w.price) FILTER (WHERE w.time < %(ten_minute_end_at)s)::double precision AS ten_minute_peak_price,
        MAX(w.price)::double precision AS one_hour_peak_price
    FROM monitored m
    JOIN baseline b ON b.market = m.market
    LEFT JOIN window_trades w ON w.market = m.market
    GROUP BY m.market, m.korean_name, m.symbol, b.baseline_price
)
SELECT
    market,
    korean_name,
    symbol,
    baseline_price,
    immediate_peak_price,
    immediate_close_price,
    ten_minute_peak_price,
    one_hour_peak_price,
    CASE
        WHEN baseline_price = 0 OR immediate_peak_price IS NULL THEN NULL
        ELSE (immediate_peak_price - baseline_price) / baseline_price * 100.0
    END AS immediate_rise_pct,
    CASE
        WHEN immediate_peak_price = 0 OR immediate_close_price IS NULL THEN NULL
        ELSE (immediate_peak_price - immediate_close_price) / immediate_peak_price * 100.0
    END AS immediate_pullback_pct,
    CASE
        WHEN baseline_price = 0 OR ten_minute_peak_price IS NULL THEN NULL
        ELSE (ten_minute_peak_price - baseline_price) / baseline_price * 100.0
    END AS ten_minute_rise_pct,
    CASE
        WHEN baseline_price = 0 OR one_hour_peak_price IS NULL THEN NULL
        ELSE (one_hour_peak_price - baseline_price) / baseline_price * 100.0
    END AS one_hour_rise_pct
FROM metrics
ORDER BY market;
"""


def build_report_period(report_date: date, immediate_window_seconds: int) -> dict:
    start_at = datetime.combine(report_date, time(9, 0), tzinfo=KST)
    return {
        "start_at": start_at,
        "immediate_end_at": start_at + timedelta(seconds=immediate_window_seconds),
        "ten_minute_end_at": start_at + timedelta(minutes=10),
        "end_at": start_at + timedelta(hours=1),
    }


def fetch_daily_market_moves(conn, report_date: date, immediate_window_seconds: int) -> list[dict]:
    params = build_report_period(report_date, immediate_window_seconds)
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(FETCH_DAILY_MARKET_MOVES_SQL, params)
        return [dict(row) for row in cursor.fetchall()]


def classify_market_moves(rows: list[dict], config) -> dict[str, list[dict]]:
    immediate_spike_and_drop = []
    ten_minute_spike = []
    one_hour_spike = []

    for row in rows:
        immediate_rise = row.get("immediate_rise_pct")
        immediate_peak = row.get("immediate_peak_price")
        immediate_close = row.get("immediate_close_price")
        if (
            immediate_rise is not None
            and immediate_rise >= config.immediate_rise_pct
            and immediate_peak is not None
            and immediate_close is not None
            and immediate_close < immediate_peak
        ):
            immediate_spike_and_drop.append(row)

        ten_minute_rise = row.get("ten_minute_rise_pct")
        if ten_minute_rise is not None and ten_minute_rise >= config.ten_minute_rise_pct:
            ten_minute_spike.append(row)

        one_hour_rise = row.get("one_hour_rise_pct")
        if one_hour_rise is not None and one_hour_rise >= config.one_hour_rise_pct:
            one_hour_spike.append(row)

    immediate_spike_and_drop.sort(key=lambda row: row["immediate_rise_pct"], reverse=True)
    ten_minute_spike.sort(key=lambda row: row["ten_minute_rise_pct"], reverse=True)
    one_hour_spike.sort(key=lambda row: row["one_hour_rise_pct"], reverse=True)
    return {
        "immediate_spike_and_drop": immediate_spike_and_drop,
        "ten_minute_spike": ten_minute_spike,
        "one_hour_spike": one_hour_spike,
    }


def _market_label(row: dict) -> str:
    label = format_market_label(row["market"], row.get("korean_name"), row.get("symbol"))
    return f"**{label}**"


def _format_immediate_row(row: dict) -> str:
    return (
        f"{_market_label(row)} · 상승 `{row['immediate_rise_pct']:.2f}%`"
        f" · 고점 대비 하락 `{row['immediate_pullback_pct']:.2f}%`"
    )


def _format_rise_row(row: dict, metric_key: str) -> str:
    return f"{_market_label(row)} · 상승 `{row[metric_key]:.2f}%`"


def _chunked(items: list[str], size: int = 20) -> list[list[str]]:
    return [items[index:index + size] for index in range(0, len(items), size)] or [[]]


def build_discord_payloads(report_date: date, groups: dict[str, list[dict]], config) -> list[dict]:
    sections = [
        (
            f"09:00 직후 {config.immediate_rise_pct:g}% 이상 급등 후 하락",
            [_format_immediate_row(row) for row in groups["immediate_spike_and_drop"]],
            15158332,
        ),
        (
            f"09:00~09:10 {config.ten_minute_rise_pct:g}% 이상 급등",
            [_format_rise_row(row, "ten_minute_rise_pct") for row in groups["ten_minute_spike"]],
            16753920,
        ),
        (
            f"09:00~10:00 {config.one_hour_rise_pct:g}% 이상 급등",
            [_format_rise_row(row, "one_hour_rise_pct") for row in groups["one_hour_spike"]],
            15548997,
        ),
    ]

    payloads = []
    for title, lines, color in sections:
        chunks = _chunked(lines)
        for page, chunk in enumerate(chunks, start=1):
            page_suffix = f" ({page}/{len(chunks)})" if len(chunks) > 1 else ""
            payloads.append(
                {
                    "username": "업비트 일일 리포트",
                    "embeds": [
                        {
                            "title": f"{report_date.isoformat()} {title}{page_suffix}",
                            "description": "\n".join(chunk) if chunk else "조건을 만족한 종목이 없습니다.",
                            "color": color,
                            "footer": {"text": "기준가: 09:00 직전 마지막 체결가 · 한국시간"},
                        }
                    ],
                }
            )
    return payloads


def send_discord_payloads(webhook_url: str, payloads: list[dict], logger: logging.Logger) -> None:
    if not webhook_url:
        raise ValueError("DAILY_REPORT_WEBHOOK_URL is required")

    for index, payload in enumerate(payloads):
        response = requests.post(webhook_url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info("daily report message sent: title=%s", payload["embeds"][0]["title"])
        if index < len(payloads) - 1:
            time_module.sleep(0.5)
