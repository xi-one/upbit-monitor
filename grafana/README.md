# Grafana Panel Setup

## Goal

Show only markets that had at least one second with trade value >= 20,000,000 KRW
inside the currently selected dashboard time range.

Examples:

- Last 5 minutes: only markets that crossed the threshold during the last 5 minutes
- Last 30 minutes: only markets that crossed the threshold during the last 30 minutes

## Queries

Use the SQL in [queries.sql](/Users/yoo/workspace/upbit-monitor/upbit-monitor/grafana/queries.sql),
or use the provisioned dashboard JSON in
[dashboards/upbit-threshold-monitor.json](/Users/yoo/workspace/upbit-monitor/upbit-monitor/grafana/dashboards/upbit-threshold-monitor.json).

Create two Time series panels:

- Buy panel: use the `BID` query
- Sell panel: use the `ASK` query

## Panel Options

- Visualization: `Time series`
- Format: `Time series`
- Legend: use the `market` field
- Unit: `currency -> KRW`

## Color Fixing

Grafana changes colors when the set of visible series changes unless colors are pinned.
To keep colors fixed:

1. Open the panel editor.
2. Click a series in the legend, or go to `Overrides`.
3. Add an override for each market you care about.
4. Match by `Fields with name` and use the exact series name such as `KRW-BTC`.
5. Set `Standard options -> Color` to a fixed color.

If you use the combined panel query, the series names become values like:

- `KRW-BTC BID`
- `KRW-BTC ASK`

In that case, pin colors using those exact names.

## Notes

- The threshold is applied to 1-second summed trade value, not to each individual trade row.
- `BID` is treated as buy-side and `ASK` as sell-side.
- If the `trades` table is large, an index on `(time, side, market)` can help, but on TimescaleDB
  the hypertable layout usually matters more than a plain Postgres index.
- Grafana provisioning is enabled through
  [provisioning/dashboards/dashboards.yaml](/Users/yoo/workspace/upbit-monitor/upbit-monitor/grafana/provisioning/dashboards/dashboards.yaml)
  and
  [provisioning/datasources/timescale.yaml](/Users/yoo/workspace/upbit-monitor/upbit-monitor/grafana/provisioning/datasources/timescale.yaml).
