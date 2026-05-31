from __future__ import annotations

import logging
import time
from collections import defaultdict

import discord
from discord.ext import commands

from firooz.config import Config
from firooz.database import KarmaDB

logger = logging.getLogger("firooz")

COGS: list[str] = [
    "firooz.cogs.karma",
    "firooz.cogs.vibe",
    "firooz.cogs.remember",
    "firooz.cogs.health",
    "firooz.cogs.waifu",
    "firooz.cogs.music",
    "firooz.cogs.translate",
    "firooz.cogs.poetry",
    "firooz.cogs.timer",
    "firooz.cogs.ask",
    "firooz.cogs.helpme",
]

# Rate limit: max N commands per user within WINDOW seconds
RATE_LIMIT_MAX = 10
RATE_LIMIT_WINDOW = 30  # seconds


class RateLimiter:
    def __init__(self, max_requests: int, window: float) -> None:
        self.max_requests = max_requests
        self.window = window
        self._requests: defaultdict[int, list[float]] = defaultdict(list)

    def is_limited(self, user_id: int) -> bool:
        now = time.monotonic()
        timestamps = self._requests[user_id]

        # Prune old entries
        self._requests[user_id] = [t for t in timestamps if now - t < self.window]

        if len(self._requests[user_id]) >= self.max_requests:
            return True

        self._requests[user_id].append(now)
        return False

    def remaining(self, user_id: int) -> int:
        now = time.monotonic()
        active = [t for t in self._requests[user_id] if now - t < self.window]
        return max(0, self.max_requests - len(active))


def create_bot(config: Config, db: KarmaDB) -> commands.Bot:
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    intents.reactions = True
    bot = commands.Bot(command_prefix="!", intents=intents)

    # Store on bot so cogs can access during setup
    bot.db = db  # type: ignore[attr-defined]
    bot.config = config  # type: ignore[attr-defined]

    rate_limiter = RateLimiter(RATE_LIMIT_MAX, RATE_LIMIT_WINDOW)

    @bot.event
    async def on_ready() -> None:
        logger.info("Bot is online as %s (ID: %s)", bot.user, bot.user.id if bot.user else "?")
        logger.info("Connected to %d guild(s)", len(bot.guilds))
        logger.info("Loaded cogs: %s", ", ".join(bot.cogs.keys()))
        logger.info("Rate limit: %d requests per %ds per user", RATE_LIMIT_MAX, RATE_LIMIT_WINDOW)

    async def _maybe_dispatch_reply(message: discord.Message) -> bool:
        """If this message is a reply to a tracked Firooz message, dispatch
        a firooz_reply event and return True. Otherwise return False."""
        ref = message.reference
        if ref is None or ref.message_id is None:
            return False

        # Cheap pre-filter: only fetch if the referenced author is our bot.
        # message.reference.resolved is populated when the referenced message
        # is in cache; otherwise we fetch.
        resolved = ref.resolved if isinstance(ref.resolved, discord.Message) else None
        if resolved is None:
            try:
                resolved = await message.channel.fetch_message(ref.message_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return False
        if bot.user is None or resolved.author.id != bot.user.id:
            return False

        context = await db.get_reply_context(ref.message_id)
        if context is None:
            return False

        if rate_limiter.is_limited(message.author.id):
            await message.channel.send(
                f"**{message.author.display_name}**, slow down! "
                f"Max {RATE_LIMIT_MAX} requests per {RATE_LIMIT_WINDOW}s."
            )
            return True

        logger.info(
            "[#%s] Reply by %s to %s/%s (msg %d)",
            message.channel, message.author,
            context["cog"], context["command"], ref.message_id,
        )
        bot.dispatch("firooz_reply", message, context)
        return True

    @bot.event
    async def on_message(message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return

        display_content = message.content
        for mentioned in message.mentions:
            display_content = display_content.replace(
                f"<@{mentioned.id}>", f"@{mentioned.display_name}"
            ).replace(
                f"<@!{mentioned.id}>", f"@{mentioned.display_name}"
            )
        logger.info("[#%s] %s: %s", message.channel, message.author, display_content)

        # Replies to tracked Firooz messages get routed through the LLM
        # intent system instead of normal command handling.
        if await _maybe_dispatch_reply(message):
            return

        # Check rate limit for commands, karma actions, and explicit bot mentions.
        is_command = message.content.startswith("!")
        has_karma = "++" in message.content or "--" in message.content
        is_explicit_mention = bot.user is not None and (
            f"<@{bot.user.id}>" in message.content
            or f"<@!{bot.user.id}>" in message.content
        )
        if is_command or has_karma or is_explicit_mention:
            if rate_limiter.is_limited(message.author.id):
                remaining_wait = int(RATE_LIMIT_WINDOW)
                await message.channel.send(
                    f"**{message.author.display_name}**, slow down! "
                    f"Max {RATE_LIMIT_MAX} requests per {remaining_wait}s. Try again shortly."
                )
                logger.warning("Rate limited: %s (%d)", message.author, message.author.id)
                return

        # Dispatch to cog listeners manually since we override on_message
        bot.dispatch("cog_message", message)

        await bot.process_commands(message)

    @bot.event
    async def on_command_error(ctx: commands.Context[commands.Bot], error: commands.CommandError) -> None:
        if isinstance(error, commands.MemberNotFound):
            await ctx.send(f"Member not found: **{error.argument}**. Use an @mention instead.")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"Missing argument: **{error.param.name}**. Example: `!history @user`")
        elif isinstance(error, commands.CommandNotFound):
            pass
        else:
            logger.error("Command error: %s", error)

    @bot.event
    async def setup_hook() -> None:
        for cog_path in COGS:
            await bot.load_extension(cog_path)
            logger.info("Loaded extension: %s", cog_path)

    return bot
