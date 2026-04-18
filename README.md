# upbit-monitor

Upbit trade collector that stores websocket trade data in PostgreSQL/TimescaleDB
and visualizes it with Grafana.

Grafana query examples for threshold-filtered buy/sell panels are in
[grafana/README.md](/Users/yoo/workspace/upbit-monitor/upbit-monitor/grafana/README.md).

## Runtime

The stack is intended to run with Docker Compose:

- `timescaledb`: stores trade data and initializes the `trades` hypertable
- `collector`: subscribes to Upbit websocket trades and writes batches to TimescaleDB
- `grafana`: queries TimescaleDB and renders dashboards
- `nginx`: exposes Grafana on port `80`
