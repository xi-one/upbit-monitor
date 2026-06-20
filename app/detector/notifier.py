import time

import requests


def _build_embed_fields(strategy_key, row):
    if strategy_key == "spike":
        return [
            {"name": "5분/1시간 비율", "value": f"{row['ratio_5m_vs_1h']:.2f}x", "inline": True},
            {"name": "현재 TPS", "value": f"{row['tps_now']:.3f}", "inline": True},
            {"name": "기준 TPS", "value": f"{row['tps_baseline']:.3f}", "inline": True},
            {"name": "TPS 증가 배수", "value": f"{row['tps_ratio']:.2f}x", "inline": True},
            {"name": "가격 변동률", "value": f"{row['price_change_pct']:.2f}%", "inline": True},
            {
                "name": "최근 5분 내 1초 최대 매수 거래대금",
                "value": f"{row['buy_1s_bid_trade_value']:,.0f}원",
                "inline": False,
            },
        ]

    if strategy_key == "dip_buying":
        return [
            {"name": "가격 하락률", "value": f"{row['price_drop_pct']:.2f}%", "inline": True},
            {"name": "시작가", "value": f"{row['first_price']:,.0f}원", "inline": True},
            {"name": "현재가", "value": f"{row['last_price']:,.0f}원", "inline": True},
            {"name": "누적 매도 거래대금", "value": f"{row['ask_trade_value']:,.0f}원", "inline": False},
        ]

    if strategy_key == "bot_detection":
        return [
            {"name": "매수→매도 페어 수", "value": f"{row['buy_sell_pair_count']:,.0f}건", "inline": True},
            {"name": "TPS", "value": f"{row['tps']:.3f}", "inline": True},
            {"name": "가격 변동폭", "value": f"{row['price_range_pct']:.3f}%", "inline": True},
            {"name": "가격 상승률", "value": f"{row['price_increase_pct']:.3f}%", "inline": True},
            {"name": "총 거래대금", "value": f"{row['total_trade_value']:,.0f}원", "inline": False},
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

    payload = {
        "username": "업비트 모니터",
        "content": f"[{strategy['name']}] 조건 충족 종목 감지: **{row['market']}**",
        "embeds": [
            {
                "title": f"{row['market']} 알림",
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
