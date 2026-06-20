import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class DbConfig:
    host: str = os.getenv("POSTGRES_HOST", "localhost")
    database: str = os.getenv("POSTGRES_DB", "")
    user: str = os.getenv("POSTGRES_USER", "")
    password: str = os.getenv("POSTGRES_PASSWORD", "")
    port: int = int(os.getenv("POSTGRES_PORT", 5432))


@dataclass(frozen=True)
class LoggingConfig:
    log_dir: str = os.getenv("LOG_DIR", "")
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
    backup_count: int = 92


@dataclass(frozen=True)
class CollectorConfig:
    ping_interval: int = 30
    ping_timeout: int = 10
    reconnect_delay_seconds: int = 5
    refresh_check_interval_seconds: int = int(os.getenv("MARKET_REFRESH_CHECK_INTERVAL_SECONDS", "5"))


@dataclass(frozen=True)
class MarketSyncConfig:
    upbit_market_all_url: str = os.getenv("UPBIT_MARKET_ALL_URL", "https://api.upbit.com/v1/market/all?is_details=false")
    coinpaprika_tickers_url: str = os.getenv("COINPAPRIKA_TICKERS_URL", "https://api.coinpaprika.com/v1/tickers")
    market_cap_limit_krw: float = float(os.getenv("MARKET_CAP_LIMIT_KRW", "1000000000000"))
    usdkrw_rate: float = float(os.getenv("MARKET_CAP_USDKRW", "1350"))
    include_unknown_markets: bool = os.getenv("MARKET_INCLUDE_UNKNOWN", "true").lower() in {"1", "true", "yes", "on"}
    refresh_interval_seconds: int = int(os.getenv("MARKET_REFRESH_INTERVAL_SECONDS", "86400"))
    failure_retry_seconds: int = int(os.getenv("MARKET_REFRESH_FAILURE_RETRY_SECONDS", "300"))
    request_timeout_seconds: int = int(os.getenv("MARKET_REFRESH_REQUEST_TIMEOUT_SECONDS", "20"))


@dataclass(frozen=True)
class DetectorConfig:
    ratio_5m_vs_1h: float = float(os.getenv("ALERT_RATIO_5M_VS_1H", "2.2"))
    tps_multiplier: float = float(os.getenv("ALERT_TPS_MULTIPLIER", "1.5"))
    price_change_pct_max: float = float(os.getenv("ALERT_PRICE_CHANGE_PCT_MAX", "2.0"))
    buy_1s_bid_trade_value_min: float = float(
        os.getenv("ALERT_BUY_1S_BID_TRADE_VALUE_MIN", os.getenv("ALERT_1H_AVG_TRADE_VALUE_MIN", "20000000"))
    )
    cooldown_seconds: int = int(os.getenv("ALERT_COOLDOWN_SECONDS", "300"))
    interval_seconds: int = int(os.getenv("DETECTOR_INTERVAL_SECONDS", "10"))
    webhook_url: str = os.getenv("ALERT_WEBHOOK_URL", "").strip()
    log_file: str = os.getenv("DETECTOR_LOG_FILE", "")


@dataclass(frozen=True)
class DipBuyingConfig:
    price_drop_pct: float = float(os.getenv("DIP_ALERT_PRICE_DROP_PCT", "3.0"))
    lookback_minutes: int = int(os.getenv("DIP_ALERT_LOOKBACK_MINUTES", "5"))
    ask_trade_value_min: float = float(os.getenv("DIP_ALERT_ASK_TRADE_VALUE_MIN", "20000000"))
    cooldown_seconds: int = int(os.getenv("DIP_ALERT_COOLDOWN_SECONDS", "300"))
    interval_seconds: int = int(os.getenv("DIP_DETECTOR_INTERVAL_SECONDS", "10"))
    webhook_url: str = os.getenv("DIP_ALERT_WEBHOOK_URL", "").strip()


@dataclass(frozen=True)
class BotDetectionConfig:
    lookback_seconds: int = int(os.getenv("BOT_ALERT_LOOKBACK_SECONDS", "30"))
    trade_value_min: float = float(os.getenv("BOT_ALERT_TRADE_VALUE_MIN", "0"))
    trade_value_max: float = float(os.getenv("BOT_ALERT_TRADE_VALUE_MAX", os.getenv("BOT_ALERT_SMALL_TRADE_VALUE_MAX", "50000")))
    max_pair_gap_seconds: float = float(os.getenv("BOT_ALERT_MAX_PAIR_GAP_SECONDS", "3"))
    min_buy_sell_pair_count: float = float(os.getenv("BOT_ALERT_MIN_BUY_SELL_PAIR_COUNT", os.getenv("BOT_ALERT_MIN_SMALL_TRADE_COUNT", "30")))
    min_tps: float = float(os.getenv("BOT_ALERT_MIN_TPS", "1.5"))
    max_tps: float = float(os.getenv("BOT_ALERT_MAX_TPS", "10"))
    price_increase_pct_max: float = float(os.getenv("BOT_ALERT_PRICE_INCREASE_PCT_MAX", "1.0"))
    cooldown_seconds: int = int(os.getenv("BOT_ALERT_COOLDOWN_SECONDS", "300"))
    interval_seconds: int = int(os.getenv("BOT_DETECTOR_INTERVAL_SECONDS", "10"))
    webhook_url: str = os.getenv("BOT_ALERT_WEBHOOK_URL", "").strip()


@dataclass(frozen=True)
class DailyMarketReportConfig:
    webhook_url: str = os.getenv("DAILY_REPORT_WEBHOOK_URL", "").strip()
    immediate_window_seconds: int = int(os.getenv("DAILY_REPORT_IMMEDIATE_WINDOW_SECONDS", "60"))
    immediate_rise_pct: float = float(os.getenv("DAILY_REPORT_IMMEDIATE_RISE_PCT", "1.0"))
    ten_minute_rise_pct: float = float(os.getenv("DAILY_REPORT_10M_RISE_PCT", "2.0"))
    one_hour_rise_pct: float = float(os.getenv("DAILY_REPORT_1H_RISE_PCT", "5.0"))


@dataclass(frozen=True)
class DetectorWebConfig:
    username: str = os.getenv("DETECTOR_WEB_USERNAME", "admin")
    password: str = os.getenv("DETECTOR_WEB_PASSWORD", "change-me")
    host: str = os.getenv("DETECTOR_WEB_HOST", "0.0.0.0")
    port: int = int(os.getenv("DETECTOR_WEB_PORT", "5000"))


def get_project_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
