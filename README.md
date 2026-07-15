# upbit-monitor

Upbit trade collector that stores websocket trade data in PostgreSQL/TimescaleDB
and visualizes it with Grafana.

Grafana query examples for threshold-filtered buy/sell panels are in
[grafana/README.md](/Users/yoo/workspace/upbit-monitor/upbit-monitor/grafana/README.md).

## Runtime

The stack is intended to run with Docker Compose:

- `timescaledb`: stores trade data and initializes the `trades` hypertable
- `collector`: subscribes to Upbit websocket trades and writes batches to TimescaleDB
- `orderbook-collector`: subscribes to Upbit websocket orderbooks/tickers and tracks ask-wall concentration
- `detector`: scans recent trades, records alert events, and optionally sends webhook alerts
- `grafana`: queries TimescaleDB and renders dashboards
- `nginx`: exposes Grafana on port `80`

## Detector

The detector polls the database and records alert events into `market_alerts`.

Default thresholds:

- `ALERT_BUY_1M_BID_TRADE_VALUE_MIN=100000000`
- `ALERT_TPS_MIN=3.0`
- `ALERT_TPS_MAX=9999`
- `ALERT_PRICE_CHANGE_PCT_MIN=0.0`
- `ALERT_PRICE_CHANGE_PCT_MAX=2.0`
- `ALERT_COOLDOWN_SECONDS=300`
- `DETECTOR_INTERVAL_SECONDS=10`

All detector thresholds can be overridden through `.env`.

## Orderbook Wall Dashboard

호가벽 감지 현황은 nginx를 통해 아래 경로에서 확인한다.

- `/detector-admin/orderbook-dashboard`

`orderbook-collector`는 모니터링 종목의 Upbit 호가창과 ticker를 구독한다. 상위 매도호가 중 특정 가격대에 매도 거래대금이 집중되면 목록에 표시한다. 기존 매도벽 물량이 급감하더라도, 같은 가격대의 `BID` 체결 거래대금이 감소분 대비 기준 비율 이상 확인된 경우만 뚫림 상태로 별도 강조한다. 화면은 1초마다 자동 갱신된다.

`.env` 설정:

```env
ORDERBOOK_WALL_DEPTH=15
ORDERBOOK_WALL_MIN_VALUE_KRW=50000000
ORDERBOOK_WALL_MIN_CONCENTRATION_RATIO=0.55
ORDERBOOK_WALL_DROP_ALERT_PCT=70
ORDERBOOK_WALL_BREACH_CONFIRM_WINDOW_SECONDS=3
ORDERBOOK_WALL_BREACH_CONFIRM_BID_RATIO=0.5
ORDERBOOK_WALL_BREACH_PRICE_TOLERANCE_PCT=0.1
ORDERBOOK_WALL_BREACH_DISPLAY_SECONDS=60
```

## Detector Admin

A small Flask-based admin UI can be exposed through nginx at:

- `/detector-admin/`

It writes new rows into `detector_settings`, and the detector reads the latest row
on every loop so threshold changes apply without restarting the detector container.

## 전날 급등 종목 일일 리포트

한국시간 기준 전날 09:00 직전 체결가를 기준으로 모니터링 종목의 급등 패턴을 분석해 Discord로 전송한다.

- 09:00 직후 기본 60초 안에 1% 이상 상승한 뒤 고점보다 내려온 종목
- 09:00~09:10 사이 2% 이상 상승한 종목
- 09:00~10:00 사이 5% 이상 상승한 종목

`.env` 설정:

```env
DAILY_REPORT_WEBHOOK_URL=https://discord.com/api/webhooks/...
DAILY_REPORT_IMMEDIATE_WINDOW_SECONDS=60
DAILY_REPORT_IMMEDIATE_RISE_PCT=1.0
DAILY_REPORT_10M_RISE_PCT=2.0
DAILY_REPORT_1H_RISE_PCT=5.0
```

Discord 전송 없이 확인:

```bash
docker compose --profile jobs run --rm daily-report python daily_market_report.py --dry-run
docker compose --profile jobs run --rm daily-report python daily_market_report.py --date 2026-06-19 --dry-run
```

전송:

```bash
docker compose --profile jobs run --rm daily-report
```

서버에서 `crontab -e`로 매일 08:00에 전날 리포트를 전송하는 예:

```bash
mkdir -p /srv/upbit-monitor/logs
```

```cron
CRON_TZ=Asia/Seoul
0 8 * * * cd /srv/upbit-monitor && /usr/bin/docker compose --profile jobs run --rm --no-deps daily-report >> /srv/upbit-monitor/logs/daily-report-cron.log 2>&1
```
