from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import discord

from firooz.bot import create_bot
from firooz.config import Config
from firooz.database import KarmaDB


def _load_opus() -> None:
    """Load the bundled libopus so voice works without a system install."""
    opus_path = Path(__file__).resolve().parents[2] / "libopus.dylib"
    if opus_path.exists() and not discord.opus.is_loaded():
        discord.opus.load_opus(str(opus_path))


async def main() -> None:
    _load_opus()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    config = Config.from_env()
    db = await KarmaDB.init(config.db_path)

    token = await db.get_config("discord_bot_token")
    if not token:
        print("ERROR: No bot token found in the database.")
        print("Run 'make configure' first to set up your bot token.")
        await db.close()
        sys.exit(1)

    bot = create_bot(config, db)
    try:
        await bot.start(token)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
