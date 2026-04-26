import time

import requests


def send_discord_alert(logger, webhook_url, row, reason):
    if not webhook_url:
        logger.info("alert detected without webhook: %s %s", row["market"], reason)
        return

    payload = {
        "username": "Upbit Monitor",
        "content": f"Alert detected for **{row['market']}**",
        "embeds": [
            {
                "title": f"{row['market']} alert",
                "description": reason,
                "color": 16753920,
                "fields": [
                    {"name": "5m / 1h ratio", "value": f"{row['ratio_5m_vs_1h']:.2f}x", "inline": True},
                    {"name": "TPS now", "value": f"{row['tps_now']:.3f}", "inline": True},
                    {"name": "TPS baseline", "value": f"{row['tps_baseline']:.3f}", "inline": True},
                    {"name": "TPS ratio", "value": f"{row['tps_ratio']:.2f}x", "inline": True},
                    {"name": "Price change", "value": f"{row['price_change_pct']:.2f}%", "inline": True},
                    {"name": "1h avg trade value", "value": f"{row['avg_1h_trade_value']:.0f} KRW", "inline": False},
                ],
                "footer": {"text": "Upbit detector"},
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
