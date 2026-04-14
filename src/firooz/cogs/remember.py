from __future__ import annotations

import logging

import discord
from discord.ext import commands

from firooz.database import KarmaDB

logger = logging.getLogger("firooz.remember")

BOT_ZONE_CHANNEL = "bot_zone"


def _find_bot_zone(guild: discord.Guild) -> discord.TextChannel | None:
    for channel in guild.text_channels:
        if channel.name == BOT_ZONE_CHANNEL:
            return channel
    return None


class RememberCog(commands.Cog, name="Remember"):
    def __init__(self, bot: commands.Bot, db: KarmaDB) -> None:
        self.bot = bot
        self.db = db

    async def _send(self, guild: discord.Guild, msg: str, fallback: discord.abc.Messageable) -> None:
        bot_zone = _find_bot_zone(guild)
        target = bot_zone or fallback
        await target.send(msg)

    @commands.command(name="remember", aliases=["rem"])  # type: ignore[arg-type]
    async def remember(self, ctx: commands.Context[commands.Bot], key: str | None = None, *, value: str | None = None) -> None:
        """Save something. Usage: !rem wifi password123 — or reply to a message with !rem or !rem <key>"""
        if ctx.guild is None:
            await ctx.send("This command can only be used in a server.")
            return

        ref_msg: discord.Message | None = None
        if ctx.message.reference and ctx.message.reference.message_id:
            try:
                ref_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            except discord.NotFound:
                await self._send(ctx.guild, "Couldn't find the original message.", ctx)
                return

        if ref_msg:
            # Build value from text + attachments + embeds
            parts: list[str] = []
            if ref_msg.content:
                parts.append(ref_msg.content)
            for att in ref_msg.attachments:
                parts.append(att.url)
            for embed in ref_msg.embeds:
                if embed.url:
                    parts.append(embed.url)
            if not parts:
                await self._send(ctx.guild, "That message has no text or attachments to save.", ctx)
                return
            value = "\n".join(parts)
            if key is None:
                # Auto-generate key from author name + timestamp
                timestamp = ref_msg.created_at.strftime("%m%d-%H%M")
                key = f"{ref_msg.author.display_name}-{timestamp}"
        else:
            # Normal usage: need both key and value
            if key is None or value is None:
                await self._send(ctx.guild, "Usage: `!rem <key> <value>` or reply to a message with `!rem` or `!rem <key>`", ctx)
                return

        await self.db.save_memory(
            guild_id=ctx.guild.id,
            key=key,
            value=value,
            saved_by=ctx.author.id,
        )
        await self._send(ctx.guild, f"Got it! I'll remember **{key}** = {value}", ctx)
        logger.info("[#%s] %s saved memory: %s = %s", ctx.channel, ctx.author, key, value)

    @commands.command(name="recall", aliases=["r"])  # type: ignore[arg-type]
    async def recall(self, ctx: commands.Context[commands.Bot], key: str) -> None:
        """Recall a saved memory. Usage: !recall wifi"""
        if ctx.guild is None:
            await ctx.send("This command can only be used in a server.")
            return

        value = await self.db.get_memory(ctx.guild.id, key)
        if value is None:
            await self._send(ctx.guild, f"I don't have anything saved for **{key}**.", ctx)
        else:
            await self._send(ctx.guild, f"**{key}** = {value}", ctx)

    @commands.command(name="memories", aliases=["mems"])  # type: ignore[arg-type]
    async def memories(self, ctx: commands.Context[commands.Bot]) -> None:
        """List all saved memories."""
        if ctx.guild is None:
            await ctx.send("This command can only be used in a server.")
            return

        entries = await self.db.list_memories(ctx.guild.id)
        if not entries:
            await self._send(ctx.guild, "No memories saved yet. Use `!remember <key> <value>` to save one.", ctx)
            return

        lines = ["**Saved memories:**\n"]
        for key, value, created_at in entries:
            lines.append(f"**{key}** — {value}")
        await self._send(ctx.guild, "\n".join(lines), ctx)

    @commands.command(name="forget")  # type: ignore[arg-type]
    async def forget(self, ctx: commands.Context[commands.Bot], key: str) -> None:
        """Forget a saved memory. Usage: !forget wifi"""
        if ctx.guild is None:
            await ctx.send("This command can only be used in a server.")
            return

        deleted = await self.db.delete_memory(ctx.guild.id, key)
        if deleted:
            await self._send(ctx.guild, f"Forgot **{key}**.", ctx)
        else:
            await self._send(ctx.guild, f"I don't have anything saved for **{key}**.", ctx)


async def setup(bot: commands.Bot) -> None:
    db = bot.db  # type: ignore[attr-defined]
    await bot.add_cog(RememberCog(bot, db))
