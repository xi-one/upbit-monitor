import time

import requests


def send_discord_alert(logger, webhook_url, row, reason):
    if not webhook_url:
        logger.info("alert detected without webhook: %s %s", row["market"], reason)
        return

    payload = {
        "username": "업비트 모니터",
        "content": f"조건 충족 종목 감지: **{row['market']}**",
        "embeds": [
            {
                "title": f"{row['market']} 알림",
                "description": reason,
                "color": 16753920,
                "fields": [
                    {"name": "5분/1시간 비율", "value": f"{row['ratio_5m_vs_1h']:.2f}x", "inline": True},
                    {"name": "현재 TPS", "value": f"{row['tps_now']:.3f}", "inline": True},
                    {"name": "기준 TPS", "value": f"{row['tps_baseline']:.3f}", "inline": True},
                    {"name": "TPS 증가 배수", "value": f"{row['tps_ratio']:.2f}x", "inline": True},
                    {"name": "가격 변동률", "value": f"{row['price_change_pct']:.2f}%", "inline": True},
                    {
                        "name": "최근 5분 내 1초 최대 매수 거래대금",
                        "value": f"{row['buy_1s_bid_trade_value']:.0f} KRW",
                        "inline": False,
                    },
                ],
                "footer": {"text": "업비트 감지기"},
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        ],
    }
    try:
        response = requests.post(webhook_url, json=payload, timeout=5)
        response.raise_for_status()
        logger.info("alert sent: market=%s status=%s", row["market"], response.status_code)
    except requests.RequestException as exc:
        logger.exception("failed to send alert for %s: %s", row["market"], exc)
