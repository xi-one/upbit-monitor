import websocket
import json
import psycopg2
from psycopg2.extras import execute_values
from datetime import datetime, timezone
from dotenv import load_dotenv
import os
import time

load_dotenv()

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
        print(f"inserted {len(batch)} rows")
        batch = []
    except Exception as e:
        conn.rollback()
        print(f"DB batch error: {e}")
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
        print(f"processing error: {e}")

def on_open(ws):
    print("websocket connected")
    subscribe = [
        {"ticket": "test"},
        {
            "type": "trade",
            "codes": ["KRW-BTC", "KRW-ETH"]
        }
    ]
    ws.send(json.dumps(subscribe))

def on_error(ws, error):
    print(f"websocket error: {error}")

def on_close(ws, close_status_code, close_msg):
    global current_batch_second
    print("websocket closed")
    insert_batch()  # 남은 배치 flush
    current_batch_second = None

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
            print(f"collector error: {e}")
        print("reconnecting in 5 seconds...")
        time.sleep(5)

if __name__ == "__main__":
    run_collector()
