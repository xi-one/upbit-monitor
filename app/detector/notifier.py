import time
import json
from datetime import timezone
from zoneinfo import ZoneInfo

import requests

KST = ZoneInfo("Asia/Seoul")


def _format_kst(value):
    if value is None:
        return "-"
    if hasattr(value, "astimezone"):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S KST")
    return str(value)


def _format_float(value, digits=2, suffix=""):
    if value is None:
        return "-"
    return f"{float(value):.{digits}f}{suffix}"


def _format_krw(value):
    if value is None:
        return "-"
    return f"{float(value):,.0f}원"


def _format_price(value):
    if value is None:
        return "-"
    price = float(value)
    digits = 0
    threshold = 100
    while price < threshold and digits < 8:
        digits += 1
        threshold /= 10
    return f"{price:,.{digits}f}원"


def _format_quantity(value):
    if value is None:
        return "-"
    return f"{float(value):,.8f}".rstrip("0").rstrip(".")


def _format_buy_volume_by_price(value):
    if not value:
        return "-"
    if isinstance(value, str):
        value = json.loads(value)

    lines = []
    for item in value:
        line = f"{_format_price(item.get('price'))}: {_format_quantity(item.get('volume'))}개"
        if len("\n".join(lines + [line])) > 1000:
            remaining = len(value) - len(lines)
            lines.append(f"... 외 {remaining}개 가격대")
            break
        lines.append(line)
    return "\n".join(lines)


def _build_embed_fields(strategy_key, row):
    if strategy_key == "spike":
        return [
            {
                "name": "측정 기준 시간",
                "value": f"{_format_kst(row.get('measurement_start_at'))} ~ {_format_kst(row.get('measurement_end_at'))}",
                "inline": False,
            },
            {"name": "최근 1분 매수 거래대금", "value": _format_krw(row.get("buy_1m_bid_trade_value")), "inline": False},
            {"name": "최근 1분 매수 평단가", "value": _format_price(row.get("buy_average_price")), "inline": True},
            {"name": "최근 1분 평균 TPS", "value": _format_float(row.get("tps_now"), 3), "inline": True},
            {"name": "최근 1분 가격 변동률", "value": _format_float(row.get("price_change_pct"), 2, "%"), "inline": True},
            {"name": "가격대별 매수 수량", "value": _format_buy_volume_by_price(row.get("buy_volume_by_price")), "inline": False},
        ]

    if strategy_key == "dip_buying":
        return [
            {"name": "가격 하락률", "value": _format_float(row.get("price_drop_pct"), 2, "%"), "inline": True},
            {"name": "시작가", "value": _format_krw(row.get("first_price")), "inline": True},
            {"name": "현재가", "value": _format_krw(row.get("last_price")), "inline": True},
            {"name": "누적 매도 거래대금", "value": _format_krw(row.get("ask_trade_value")), "inline": False},
            {"name": "최근 1분 매도 평단가", "value": _format_price(row.get("ask_average_price")), "inline": True},
        ]

    if strategy_key == "bot_detection":
        return [
            {"name": "매수→매도 페어 수", "value": f"{float(row.get('buy_sell_pair_count') or 0):,.0f}건", "inline": True},
            {"name": "TPS", "value": _format_float(row.get("tps"), 3), "inline": True},
            {"name": "가격 변동폭", "value": _format_float(row.get("price_range_pct"), 3, "%"), "inline": True},
            {"name": "가격 상승률", "value": _format_float(row.get("price_increase_pct"), 3, "%"), "inline": True},
            {"name": "총 거래대금", "value": _format_krw(row.get("total_trade_value")), "inline": False},
        ]

    return []


def _embed_color(strategy_key):
    if strategy_key == "spike":
        return 16753920
    if strategy_key == "dip_buying":
        return 15158332
    if strategy_key == "bot_detection":
        return 5793266
    return 16777215


def send_discord_alert(logger, webhook_url, strategy, row, reason):
    if not webhook_url:
        logger.info("alert detected without webhook: strategy=%s market=%s %s", strategy["strategy_key"], row["market"], reason)
        return

    market_label = row.get("market_label") or row["market"]
    average_price = _format_price(row.get("buy_average_price"))
    is_spike = strategy["strategy_key"] == "spike"
    notification_title = f"[{strategy['name']}] 조건 충족 종목 감지: **{market_label}**"
    embed_title = f"{market_label} 알림"
    if is_spike:
        notification_title += f" | 매수 평단가: {average_price}"
        embed_title += f" | 평단가 {average_price}"
    payload = {
        "username": "업비트 모니터",
        "content": notification_title,
        "embeds": [
            {
                "title": embed_title,
                "description": reason,
                "color": _embed_color(strategy["strategy_key"]),
                "fields": _build_embed_fields(strategy["strategy_key"], row),
                "footer": {"text": f"업비트 감지기 · {strategy['name']}"},
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        ],
    }
    try:
        response = requests.post(webhook_url, json=payload, timeout=5)
        response.raise_for_status()
        logger.info(
            "alert sent: strategy=%s market=%s status=%s",
            strategy["strategy_key"],
            row["market"],
            response.status_code,
        )
    except requests.RequestException as exc:
        logger.exception("failed to send alert for %s/%s: %s", strategy["strategy_key"], row["market"], exc)
