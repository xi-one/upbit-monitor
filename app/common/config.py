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
    markets_file: str = os.getenv("UPBIT_MARKETS_FILE", "markets.txt")
    ping_interval: int = 30
    ping_timeout: int = 10
    reconnect_delay_seconds: int = 5


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
class DetectorWebConfig:
    username: str = os.getenv("DETECTOR_WEB_USERNAME", "admin")
    password: str = os.getenv("DETECTOR_WEB_PASSWORD", "change-me")
    host: str = os.getenv("DETECTOR_WEB_HOST", "0.0.0.0")
    port: int = int(os.getenv("DETECTOR_WEB_PORT", "5000"))


def get_project_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def resolve_path(path: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.join(get_project_dir(), path)
