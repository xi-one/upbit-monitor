# upbit-monitor

Upbit trade collector that stores websocket trade data in PostgreSQL/TimescaleDB
and visualizes it with Grafana.

Grafana query examples for threshold-filtered buy/sell panels are in
[grafana/README.md](/Users/yoo/workspace/upbit-monitor/upbit-monitor/grafana/README.md).

## Runtime

The stack is intended to run with Docker Compose:

- `timescaledb`: stores trade data and initializes the `trades` hypertable
- `collector`: subscribes to Upbit websocket trades and writes batches to TimescaleDB
- `detector`: scans recent trades, records alert events, and optionally sends webhook alerts
- `grafana`: queries TimescaleDB and renders dashboards
- `nginx`: exposes Grafana on port `80`

## Detector

The detector polls the database and records alert events into `market_alerts`.

Default thresholds:

- `ALERT_RATIO_5M_VS_1H=2.2`
- `ALERT_TPS_MULTIPLIER=1.5`
- `ALERT_PRICE_CHANGE_PCT_MAX=2.0`
- `ALERT_1H_AVG_TRADE_VALUE_MIN=1000000000`
- `ALERT_COOLDOWN_SECONDS=300`
- `DETECTOR_INTERVAL_SECONDS=10`

All detector thresholds can be overridden through `.env`.

## Detector Admin

A small Flask-based admin UI can be exposed through nginx at:

- `/detector-admin/`

It writes new rows into `detector_settings`, and the detector reads the latest row
on every loop so threshold changes apply without restarting the detector container.
