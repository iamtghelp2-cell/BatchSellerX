# Copyright (c) 2025 devgagan : https://github.com/devgaganin.  
# Modified & rebranded by iamtghelp (https://t.me/iamtghelp)
# Licensed under the GNU General Public License v3.0.  
# See LICENSE file in the repository root for full license text.

from telethon import TelegramClient
from config import API_ID, API_HASH, BOT_TOKEN, STRING
from pyrogram import Client
import asyncio
import sys

client = TelegramClient(
    "telethonbot",
    int(API_ID),
    API_HASH,
    connection_retries=10,
    retry_delay=3,
    auto_reconnect=True
)
app = Client("pyrogrambot", api_id=int(API_ID), api_hash=API_HASH, bot_token=BOT_TOKEN)
userbot = Client("4gbbot", api_id=int(API_ID), api_hash=API_HASH, session_string=STRING)

async def start_client():
    for attempt in range(5):
        try:
            if not client.is_connected():
                await client.start(bot_token=BOT_TOKEN)
            print("Telethon client started...")
            break
        except Exception as e:
            print(f"Telethon retry {attempt + 1}/5 failed: {e}")
            await asyncio.sleep(5)

    if STRING:
        try:
            await userbot.start()
            print("Userbot started...")
        except Exception as e:
            print(f"Hey honey!! check your premium string session, it may be invalid of expire {e}")
            sys.exit(1)

    await app.start()
    print("Pyro App Started...")
    return client, app, userbot
    
