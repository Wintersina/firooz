from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands, tasks

from firooz.database import KarmaDB
from firooz.ollama import translate_to_english

logger = logging.getLogger("firooz.poetry")

DISCORD_MAX_LEN = 2000
BOT_ZONE_CHANNEL = "bot_zone"

# Config keys stored in the config table
CFG_ENABLED = "poetry_daily_enabled"      # "true" / "false"
CFG_INTERVAL = "poetry_daily_interval_hours"  # e.g. "24"


def _find_bot_zone(guild: discord.Guild) -> discord.TextChannel | None:
    for channel in guild.text_channels:
        if channel.name == BOT_ZONE_CHANNEL:
            return channel
    return None


def _format_poem(poet: str, book_title: str, poem_title: str, text: str) -> str:
    header = f"**{poet}**"
    if book_title:
        header += f" — {book_title}"
    if poem_title:
        header += f" — {poem_title}"
    return f"{header}\n\n{text}"


def _split_message(text: str, limit: int = DISCORD_MAX_LEN) -> list[str]:
    """Split text into chunks that fit within Discord's message limit.

    Splits on newlines first, then hard-wraps if a single line is too long.
    """
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                chunks.append(current)
            # If a single line exceeds the limit, hard-split it
            while len(line) > limit:
                chunks.append(line[:limit])
                line = line[limit:]
            current = line
    if current:
        chunks.append(current)
    return chunks



class PoetryCog(commands.Cog, name="Poetry"):
    def __init__(self, bot: commands.Bot, db: KarmaDB) -> None:
        self.bot = bot
        self.db = db
        self.poem_loop.start()

    def cog_unload(self) -> None:
        self.poem_loop.cancel()

    async def _is_enabled(self) -> bool:
        val = await self.db.get_config(CFG_ENABLED)
        return val == "true"

    async def _get_interval_hours(self) -> int:
        val = await self.db.get_config(CFG_INTERVAL)
        if val is not None:
            try:
                return max(1, int(val))
            except ValueError:
                pass
        return 24

    async def _post_poem(self, guild: discord.Guild, channel: discord.abc.Messageable) -> bool:
        """Post a random poem with translation. Returns True if sent."""
        poem = await self.db.get_random_poem(guild.id)
        if poem is None:
            logger.warning("No unshared poems left for guild %s", guild.id)
            return False

        msg = _format_poem(poem.poet, poem.book_title, poem.poem_title, poem.text)
        header_parts = [poem.poet, poem.book_title, poem.poem_title]
        header_text = " — ".join(p for p in header_parts if p)
        full_text = f"{header_text}\n\n{poem.text}"

        async with channel.typing():
            translation = await translate_to_english(full_text)

        if translation:
            full = f"{msg}\n\n**Translation:**\n{translation}"
        else:
            full = msg

        for chunk in _split_message(full):
            await channel.send(chunk)

        await self.db.record_shared_poem(guild.id, poem.id)
        return True

    @tasks.loop(hours=1)
    async def poem_loop(self) -> None:
        """Check every hour if it's time to post a poem."""
        if not await self._is_enabled():
            return

        interval_hours = await self._get_interval_hours()

        for guild in self.bot.guilds:
            bot_zone = _find_bot_zone(guild)
            if bot_zone is None:
                continue

            last_shared = await self.db.get_last_shared_time(guild.id)
            if last_shared is not None:
                cutoff = datetime.now(timezone.utc) - timedelta(hours=interval_hours)
                if last_shared > cutoff:
                    continue

            if await self._post_poem(guild, bot_zone):
                logger.info("Scheduled poem shared in guild %s", guild.name)

    @poem_loop.before_loop
    async def before_poem_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def _replay_last_poem(self, guild: discord.Guild, channel: discord.abc.Messageable) -> bool:
        """Re-post the last shared poem with a fresh translation."""
        poem = await self.db.get_last_shared_poem(guild.id)
        if poem is None:
            return False

        msg = _format_poem(poem.poet, poem.book_title, poem.poem_title, poem.text)
        header_parts = [poem.poet, poem.book_title, poem.poem_title]
        header_text = " — ".join(p for p in header_parts if p)
        full_text = f"{header_text}\n\n{poem.text}"

        async with channel.typing():
            translation = await translate_to_english(full_text)

        if translation:
            full = f"{msg}\n\n**Translation:**\n{translation}"
        else:
            full = msg

        for chunk in _split_message(full):
            await channel.send(chunk)
        return True

    @commands.command(name="poem", aliases=["faal"])  # type: ignore[arg-type]
    async def poem(self, ctx: commands.Context[commands.Bot], arg: str = "") -> None:
        """Get a random Persian poem. Use !poem last to replay the previous one."""
        if ctx.guild is None:
            await ctx.send("This command can only be used in a server.")
            return

        if arg.lower() == "last":
            if not await self._replay_last_poem(ctx.guild, ctx):
                await ctx.send("No previous poem found!")
            return

        if not await self._post_poem(ctx.guild, ctx):
            await ctx.send("No poems available right now!")

    @commands.command(name="poetry")  # type: ignore[arg-type]
    async def poetry_config(self, ctx: commands.Context[commands.Bot], action: str = "", value: str = "") -> None:
        """Configure daily poem. Usage: !poetry on|off|interval <hours>|status"""
        if ctx.guild is None:
            await ctx.send("This command can only be used in a server.")
            return

        action = action.lower()

        if action == "on":
            await self.db.set_config(CFG_ENABLED, "true")
            interval = await self._get_interval_hours()
            await ctx.send(f"Daily poem **enabled** (every {interval}h).")
        elif action == "off":
            await self.db.set_config(CFG_ENABLED, "false")
            await ctx.send("Daily poem **disabled**.")
        elif action == "interval":
            if not value.isdigit() or int(value) < 1:
                await ctx.send("Usage: `!poetry interval <hours>` (minimum 1)")
                return
            await self.db.set_config(CFG_INTERVAL, value)
            await ctx.send(f"Daily poem interval set to **{value}h**.")
        elif action in ("status", ""):
            enabled = await self._is_enabled()
            interval = await self._get_interval_hours()
            status = "enabled" if enabled else "disabled"
            await ctx.send(f"Daily poem: **{status}** | Interval: **{interval}h**")
        else:
            await ctx.send("Usage: `!poetry on|off|interval <hours>|status`")


async def setup(bot: commands.Bot) -> None:
    db = bot.db  # type: ignore[attr-defined]
    poem_count = await db.get_poem_count()
    if poem_count == 0:
        logger.warning("No poems in database. Run 'make import-poems' to load them.")
    else:
        logger.info("Poetry cog loaded with %d poems", poem_count)
    await bot.add_cog(PoetryCog(bot, db))
