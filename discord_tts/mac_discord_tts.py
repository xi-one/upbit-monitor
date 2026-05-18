import asyncio
import os
import re
import subprocess

import discord
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
ONLY_BOT_MESSAGES = os.getenv("DISCORD_TTS_ONLY_BOT_MESSAGES", "true").lower() in {"1", "true", "yes", "on"}
USERNAME_PREFIX = os.getenv("DISCORD_TTS_USERNAME_PREFIX", "false").lower() in {"1", "true", "yes", "on"}
MAC_VOICE = os.getenv("DISCORD_TTS_MAC_VOICE", "").strip()

MARKET_PATTERN = re.compile(r"\b([A-Z]{2,5}-[A-Z0-9]{2,10})\b")

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


def extract_speech_text(message: discord.Message) -> str:
    content = (message.content or "").strip()
    if not content:
        return ""

    market_match = MARKET_PATTERN.search(content)
    if market_match:
        market = market_match.group(1)
        return f"{message.author.display_name} {market}" if USERNAME_PREFIX else market

    return f"{message.author.display_name} {content}" if USERNAME_PREFIX else content


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
        await speak(text)


def main():
    if not TOKEN:
        raise SystemExit("DISCORD_BOT_TOKEN is required")
    if not CHANNEL_ID:
        raise SystemExit("DISCORD_CHANNEL_ID is required")
    client.run(TOKEN)


if __name__ == "__main__":
    main()
