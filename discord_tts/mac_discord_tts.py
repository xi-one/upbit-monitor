import asyncio
import os
import re
from datetime import datetime

import discord
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
ONLY_BOT_MESSAGES = os.getenv("DISCORD_TTS_ONLY_BOT_MESSAGES", "true").lower() in {"1", "true", "yes", "on"}
MAC_VOICE = os.getenv("DISCORD_TTS_MAC_VOICE", "").strip()
UPBIT_MARKET_ALL_URL = os.getenv("UPBIT_MARKET_ALL_URL", "https://api.upbit.com/v1/market/all?is_details=false").strip()

MARKET_PATTERN = re.compile(r"\b([A-Z]{2,5}-[A-Z0-9]{2,10})\b")
RESET = "\033[0m"
CHANNEL_COLORS = [
    "\033[31m",  # red
    "\033[34m",  # blue
    "\033[32m",  # green
    "\033[35m",  # magenta
    "\033[36m",  # cyan
    "\033[33m",  # yellow
]

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


def load_channel_ids() -> set[int]:
    raw_channel_ids = os.getenv("DISCORD_CHANNEL_IDS", "").strip()
    if not raw_channel_ids:
        raw_channel_ids = os.getenv("DISCORD_CHANNEL_ID", "").strip()

    channel_ids = set()
    for item in raw_channel_ids.split(","):
        item = item.strip()
        if not item:
            continue
        channel_ids.add(int(item))
    return channel_ids


CHANNEL_IDS = load_channel_ids()
CHANNEL_COLOR_MAP = {
    channel_id: CHANNEL_COLORS[index % len(CHANNEL_COLORS)]
    for index, channel_id in enumerate(sorted(CHANNEL_IDS))
}


def color_for_channel(channel_id: int) -> str:
    return CHANNEL_COLOR_MAP.get(channel_id, CHANNEL_COLORS[0])


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


def iter_message_texts(message: discord.Message):
    content = (message.content or "").strip()
    if content:
        yield content

    for embed in message.embeds:
        for value in (embed.title, embed.description):
            if value:
                yield str(value)

        for field in embed.fields:
            if field.name:
                yield str(field.name)
            if field.value:
                yield str(field.value)


def extract_speech_event(message: discord.Message) -> dict:
    for text in iter_message_texts(message):
        market_match = MARKET_PATTERN.search(text)
        if market_match:
            market = market_match.group(1)
            spoken_market = MARKET_NAME_MAP.get(market, market)
            return {
                "market": market,
                "spoken_market": spoken_market,
                "speech_text": spoken_market,
                "content": text,
            }

    return {}


def print_speech_event(message: discord.Message, event: dict) -> None:
    channel_name = getattr(message.channel, "name", "")
    channel_label = f"#{channel_name}" if channel_name else str(message.channel.id)
    market_label = event["spoken_market"] or event["market"] or "종목 없음"
    occurred_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    color = color_for_channel(message.channel.id)
    print(f"\n[{occurred_at}] {color}{channel_label}{RESET} {market_label}\n")


async def resolve_channel_label(channel_id: int) -> str:
    channel = client.get_channel(channel_id)
    if channel is None:
        try:
            channel = await client.fetch_channel(channel_id)
        except discord.DiscordException:
            return "not found"

    channel_name = getattr(channel, "name", "")
    return f"#{channel_name}" if channel_name else str(channel_id)


async def speak(text: str) -> None:
    if not text:
        return

    cmd = ["say"]
    if MAC_VOICE:
        cmd.extend(["-v", MAC_VOICE])
    cmd.append(text)

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await process.communicate()


@client.event
async def on_ready():
    print(f"connected: {client.user}")
    print("listening channel map:")
    for channel_id in sorted(CHANNEL_IDS):
        channel_label = await resolve_channel_label(channel_id)
        print(f"- {channel_id} -> {color_for_channel(channel_id)}{channel_label}{RESET}")


@client.event
async def on_message(message: discord.Message):
    if message.author == client.user:
        return
    if message.channel.id not in CHANNEL_IDS:
        return
    if ONLY_BOT_MESSAGES and not message.author.bot:
        return

    event = extract_speech_event(message)
    if event:
        print_speech_event(message, event)
        await speak(event["speech_text"])


def main():
    if not TOKEN:
        raise SystemExit("DISCORD_BOT_TOKEN is required")
    if not CHANNEL_IDS:
        raise SystemExit("DISCORD_CHANNEL_IDS or DISCORD_CHANNEL_ID is required")
    client.run(TOKEN)


if __name__ == "__main__":
    main()
