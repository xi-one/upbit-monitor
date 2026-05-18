import os
import re
import queue
import threading

import discord
import pyttsx3
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
ONLY_BOT_MESSAGES = os.getenv("DISCORD_TTS_ONLY_BOT_MESSAGES", "true").lower() in {"1", "true", "yes", "on"}
USERNAME_PREFIX = os.getenv("DISCORD_TTS_USERNAME_PREFIX", "false").lower() in {"1", "true", "yes", "on"}
WINDOWS_RATE = int(os.getenv("DISCORD_TTS_WINDOWS_RATE", "180"))
UPBIT_MARKET_ALL_URL = os.getenv("UPBIT_MARKET_ALL_URL", "https://api.upbit.com/v1/market/all?is_details=false").strip()

MARKET_PATTERN = re.compile(r"\b([A-Z]{2,5}-[A-Z0-9]{2,10})\b")

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

tts_queue: queue.Queue[str] = queue.Queue()


def load_market_name_map() -> dict[str, str]:
    try:
        response = requests.get(UPBIT_MARKET_ALL_URL, timeout=10)
        response.raise_for_status()
        rows = response.json()
    except Exception:
        return {}

    mapping = {}
    for row in rows:
        market = row.get("market")
        korean_name = row.get("korean_name")
        if market and korean_name:
            mapping[market] = korean_name
    return mapping


MARKET_NAME_MAP = load_market_name_map()


def tts_worker():
    engine = pyttsx3.init()
    engine.setProperty("rate", WINDOWS_RATE)
    while True:
        text = tts_queue.get()
        if text is None:
            break
        engine.say(text)
        engine.runAndWait()
        tts_queue.task_done()


def extract_speech_text(message: discord.Message) -> str:
    content = (message.content or "").strip()
    if not content:
        return ""

    market_match = MARKET_PATTERN.search(content)
    if market_match:
        market = market_match.group(1)
        spoken_market = MARKET_NAME_MAP.get(market, market)
        return f"{message.author.display_name} {spoken_market}" if USERNAME_PREFIX else spoken_market

    return f"{message.author.display_name} {content}" if USERNAME_PREFIX else content


@client.event
async def on_ready():
    print(f"connected: {client.user}")
    print(f"listening channel: {CHANNEL_ID}")


@client.event
async def on_message(message: discord.Message):
    if message.author == client.user:
        return
    if message.channel.id != CHANNEL_ID:
        return
    if ONLY_BOT_MESSAGES and not message.author.bot:
        return

    text = extract_speech_text(message)
    if text:
        print(f"speak: {text}")
        tts_queue.put(text)


def main():
    if not TOKEN:
        raise SystemExit("DISCORD_BOT_TOKEN is required")
    if not CHANNEL_ID:
        raise SystemExit("DISCORD_CHANNEL_ID is required")

    worker = threading.Thread(target=tts_worker, daemon=True)
    worker.start()
    client.run(TOKEN)


if __name__ == "__main__":
    main()
