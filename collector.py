import websocket
import json
import psycopg2
from psycopg2.extras import execute_values
from datetime import datetime, timezone
from dotenv import load_dotenv
from logging.handlers import TimedRotatingFileHandler
import logging
import os
import re
import signal
import sys
import time

load_dotenv()

LOG_DIR = os.getenv("LOG_DIR", os.path.join(os.path.dirname(__file__), "logs"))
LOG_FILE = os.getenv("LOG_FILE", os.path.join(LOG_DIR, "collector.log"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("upbit_collector")
logger.setLevel(getattr(logging, LOG_LEVEL, logging.WARNING))
logger.handlers.clear()

formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

file_handler = TimedRotatingFileHandler(
    LOG_FILE,
    when="midnight",
    interval=1,
    backupCount=92,
    encoding="utf-8",
)
file_handler.suffix = "%Y%m%d"
file_handler.extMatch = re.compile(r"^\d{8}$", re.ASCII)
file_handler.setFormatter(formatter)

stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)

logger.addHandler(file_handler)
logger.addHandler(stream_handler)
logger.propagate = False

conn = psycopg2.connect(
    host=os.getenv("POSTGRES_HOST", "localhost"),
    database=os.getenv("POSTGRES_DB"),
    user=os.getenv("POSTGRES_USER"),
    password=os.getenv("POSTGRES_PASSWORD"),
    port=os.getenv("POSTGRES_PORT", 5432)
)
cursor = conn.cursor()
batch = []
current_batch_second = None
DEFAULT_MARKETS = ["KRW-BTC", "KRW-ETH"]
shutdown_requested = False


def load_markets():
    """
    Load markets from a text file (one market per line).
    Supports blank lines and '#' comments.
    """
    markets_file = os.getenv("UPBIT_MARKETS_FILE", "markets.txt")
    if not os.path.isabs(markets_file):
        markets_file = os.path.join(os.path.dirname(__file__), markets_file)

    try:
        with open(markets_file, "r", encoding="utf-8") as f:
            markets = []
            for line in f:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                markets.append(s)
    except FileNotFoundError:
        print(f"markets file not found: {markets_file} (using default markets)")
        return DEFAULT_MARKETS
    except Exception as e:
        print(f"failed to read markets file: {markets_file} ({e}) (using default markets)")
        return DEFAULT_MARKETS

    # Deduplicate while preserving order
    unique = []
    seen = set()
    for m in markets:
        if m in seen:
            continue
        seen.add(m)
        unique.append(m)

    if not unique:
        print(f"markets file is empty: {markets_file} (using default markets)")
        return DEFAULT_MARKETS

    return unique

def insert_batch():
    global batch
    if not batch:
        return
    try:
        execute_values(
            cursor,
            """
            INSERT INTO trades
            (time,market,price,volume,trade_value,side)
            VALUES %s
            """,
            batch
        )
        conn.commit()
        logger.debug("inserted %d rows", len(batch))
        batch = []
    except Exception as e:
        conn.rollback()
        logger.exception("DB batch error: %s", e)
        batch = []  # 손상 배치 제거

def on_message(ws, message):
    global batch, current_batch_second
    try:
        if isinstance(message, bytes):
            message = message.decode('utf-8')
        data = json.loads(message)
        trade_second = data['timestamp'] // 1000

        if current_batch_second is None:
            current_batch_second = trade_second
        elif trade_second != current_batch_second:
            insert_batch()
            current_batch_second = trade_second

        row = (
            datetime.fromtimestamp(data['timestamp'] / 1000, tz=timezone.utc),
            data['code'],
            data['trade_price'],
            data['trade_volume'],
            data['trade_price'] * data['trade_volume'],
            data['ask_bid']
        )
        batch.append(row)
    except Exception as e:
        logger.exception("processing error: %s", e)

def on_open(ws):
    markets = load_markets()
    logger.info("collector started: subscribing %d markets", len(markets))
    subscribe = [
        {"ticket": "test"},
        {
            "type": "trade",
            "codes": markets
        }
    ]
    ws.send(json.dumps(subscribe))

def on_error(ws, error):
    logger.error("websocket error: %s", error)

def on_close(ws, close_status_code, close_msg):
    global current_batch_second
    insert_batch()  # 남은 배치 flush
    current_batch_second = None
    if not shutdown_requested:
        logger.warning(
            "websocket closed: status=%s message=%s",
            close_status_code,
            close_msg,
        )

def handle_shutdown(signum, frame):
    global shutdown_requested
    shutdown_requested = True
    logger.info("collector stopping: received signal %s", signum)
    insert_batch()
    conn.close()
    sys.exit(0)

def run_collector():
    while True:
        try:
            ws = websocket.WebSocketApp(
                "wss://api.upbit.com/websocket/v1",
                on_message=on_message,
                on_open=on_open,
                on_error=on_error,
                on_close=on_close
            )
            ws.run_forever(
                ping_interval=30,
                ping_timeout=10
            )
        except Exception as e:
            logger.exception("collector error: %s", e)
        if shutdown_requested:
            break
        logger.warning("reconnecting in 5 seconds...")
        time.sleep(5)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)
    run_collector()
