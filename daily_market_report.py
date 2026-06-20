import argparse
import json
import logging
from datetime import datetime, timedelta

from app.common.config import DailyMarketReportConfig, DbConfig
from app.common.db import create_connection
from app.reports.daily_market import (
    KST,
    build_discord_payloads,
    classify_market_moves,
    fetch_daily_market_moves,
    send_discord_payloads,
)


def parse_args():
    parser = argparse.ArgumentParser(description="전날 업비트 모니터링 종목 급등 리포트를 전송합니다.")
    parser.add_argument("--date", help="분석할 한국 날짜(YYYY-MM-DD). 기본값은 어제입니다.")
    parser.add_argument("--dry-run", action="store_true", help="Discord로 보내지 않고 결과 JSON만 출력합니다.")
    return parser.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger("daily-market-report")
    report_date = (
        datetime.strptime(args.date, "%Y-%m-%d").date()
        if args.date
        else datetime.now(KST).date() - timedelta(days=1)
    )
    config = DailyMarketReportConfig()

    conn = create_connection(DbConfig())
    try:
        rows = fetch_daily_market_moves(conn, report_date, config.immediate_window_seconds)
    finally:
        conn.close()

    groups = classify_market_moves(rows, config)
    payloads = build_discord_payloads(report_date, groups, config)
    logger.info(
        "daily report calculated: date=%s monitored=%d immediate=%d ten_minute=%d one_hour=%d",
        report_date,
        len(rows),
        len(groups["immediate_spike_and_drop"]),
        len(groups["ten_minute_spike"]),
        len(groups["one_hour_spike"]),
    )

    if args.dry_run:
        print(json.dumps(payloads, ensure_ascii=False, indent=2))
        return

    send_discord_payloads(config.webhook_url, payloads, logger)


if __name__ == "__main__":
    main()
