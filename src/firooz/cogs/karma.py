from __future__ import annotations

import logging

import discord
from discord.ext import commands

from firooz.database import KarmaDB
from firooz.karma import parse_karma_actions
from firooz.responses import (
    format_karma_response,
    format_leaderboard,
    format_self_vote_response,
)

logger = logging.getLogger("firooz.karma")

BOT_ZONE_CHANNEL = "bot_zone"


def _describe_message(message: discord.Message) -> str:
    """Build a text description of a message: content, attachments, or embeds."""
    parts: list[str] = []
    if message.content:
        parts.append(message.content)
    for att in message.attachments:
        parts.append(att.url)
    for embed in message.embeds:
        if embed.url:
            parts.append(embed.url)
    return "\n".join(parts) if parts else "(no text)"

KARMA_REACTIONS: dict[str, int] = {
    "\U0001f44d": 1,   # 👍
    "\U0001f44e": -1,  # 👎
    "\U0001f4af": 1,   # 💯
    "\U0001f923": 2,   # 🤣 (rolling on floor gets 2)
    "\U0001f602": 1,   # 😂 tears of joy
    "\U0001f606": 1,   # 😆 grinning squinting
    "\U0001f605": 1,   # 😅 sweat smile
    "\U0001f604": 1,   # 😄 grinning with eyes
    "\U0001f603": 1,   # 😃 grinning big eyes
    "\U0001f601": 1,   # 😁 beaming grin
    "\U0000263a\ufe0f": 1,  # ☺️ smiling
    "\U0001f61c": 1,   # 😜 winking tongue
    "\U0001f61d": 1,   # 😝 squinting tongue
    "\U0001f911": 1,   # 🤑 money mouth (laughing variant)
}

# Custom server emojis (matched by name)
CUSTOM_KARMA_REACTIONS: dict[str, int] = {
    "pornhub": 2,
}


def _get_reaction_delta(emoji: discord.PartialEmoji) -> int | None:
    """Get karma delta for a reaction emoji (unicode or custom)."""
    if emoji.id is not None:
        # Custom emoji — match by name
        return CUSTOM_KARMA_REACTIONS.get(emoji.name or "")
    # Unicode emoji — match by string
    return KARMA_REACTIONS.get(str(emoji))


def _find_bot_zone(guild: discord.Guild) -> discord.TextChannel | None:
    for channel in guild.text_channels:
        if channel.name == BOT_ZONE_CHANNEL:
            return channel
    return None


class KarmaCog(commands.Cog, name="Karma"):
    def __init__(self, bot: commands.Bot, db: KarmaDB) -> None:
        self.bot = bot
        self.db = db

    async def _send_karma_update(
        self, guild: discord.Guild, response: str, fallback_channel: discord.abc.Messageable
    ) -> None:
        bot_zone = _find_bot_zone(guild)
        if bot_zone:
            await bot_zone.send(response, suppress_embeds=True)
        else:
            await fallback_channel.send(response, suppress_embeds=True)

    @commands.Cog.listener()
    async def on_cog_message(self, message: discord.Message) -> None:
        if message.guild is None:
            return

        actions = parse_karma_actions(message.content)
        for action in actions:
            if action.user_id == message.author.id:
                response = format_self_vote_response(message.author.display_name)
                await message.channel.send(response)
                continue

            new_total = await self.db.update_karma(
                guild_id=message.guild.id,
                user_id=action.user_id,
                delta=action.delta,
                given_by=message.author.id,
                reason=action.reason,
            )

            member = message.guild.get_member(action.user_id)
            username = member.display_name if member else f"User {action.user_id}"
            response = format_karma_response(
                username, new_total, action.delta, action.reason,
                given_by=message.author.display_name,
            )
            await self._send_karma_update(message.guild, response, message.channel)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        delta = _get_reaction_delta(payload.emoji)
        if delta is None or payload.guild_id is None or payload.member is None:
            return
        if payload.member.bot:
            return

        channel = self.bot.get_channel(payload.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        message = await channel.fetch_message(payload.message_id)

        if message.author.bot or message.author.id == payload.member.id:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return

        emoji_str = str(payload.emoji)
        msg_text = _describe_message(message)
        reason = f"{emoji_str} reaction for: {msg_text}"
        display_reason = f"{emoji_str} reaction for: {msg_text[:100]}"

        new_total = await self.db.update_karma(
            guild_id=payload.guild_id,
            user_id=message.author.id,
            delta=delta,
            given_by=payload.member.id,
            reason=reason,
        )
        username = message.author.display_name
        reactor_name = payload.member.display_name
        response = format_karma_response(
            username, new_total, delta, display_reason, given_by=reactor_name,
        )
        await self._send_karma_update(guild, response, channel)
        logger.info(
            "[#%s] %s reacted %s on %s's message → %d karma",
            channel.name, payload.member, emoji_str, message.author, new_total,
        )

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        delta = _get_reaction_delta(payload.emoji)
        if delta is None or payload.guild_id is None:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        reactor = guild.get_member(payload.user_id)
        if reactor is None or reactor.bot:
            return

        channel = self.bot.get_channel(payload.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        message = await channel.fetch_message(payload.message_id)

        if message.author.bot or message.author.id == payload.user_id:
            return

        emoji_str = str(payload.emoji)
        reverse_delta = -delta
        msg_text = _describe_message(message)
        reason = f"{emoji_str} reaction removed for: {msg_text}"
        display_reason = f"{emoji_str} reaction removed for: {msg_text[:100]}"

        new_total = await self.db.update_karma(
            guild_id=payload.guild_id,
            user_id=message.author.id,
            delta=reverse_delta,
            given_by=payload.user_id,
            reason=reason,
        )
        username = message.author.display_name
        reactor_name = reactor.display_name
        response = format_karma_response(
            username, new_total, reverse_delta, display_reason, given_by=reactor_name,
        )
        await self._send_karma_update(guild, response, channel)
        logger.info(
            "[#%s] %s removed %s on %s's message → %d karma",
            channel.name, reactor, emoji_str, message.author, new_total,
        )

    @commands.command(name="leaderboard", aliases=["lb"])  # type: ignore[arg-type]
    async def leaderboard(self, ctx: commands.Context[commands.Bot]) -> None:
        """Show the top karma holders in the server."""
        if ctx.guild is None:
            await ctx.send("This command can only be used in a server.")
            return

        entries = await self.db.get_leaderboard(ctx.guild.id)
        resolved: list[tuple[str, int]] = []
        for user_id, points in entries:
            member = ctx.guild.get_member(user_id)
            name = member.display_name if member else f"User {user_id}"
            resolved.append((name, points))

        response = format_leaderboard(resolved, ctx.guild.name)
        await ctx.send(response)

    @commands.command(name="history", aliases=["h"])  # type: ignore[arg-type]
    async def history(self, ctx: commands.Context[commands.Bot], member: discord.Member) -> None:
        """Show karma history for a user. Usage: !history @user"""
        if ctx.guild is None:
            await ctx.send("This command can only be used in a server.")
            return

        entries = await self.db.get_history(ctx.guild.id, member.id)
        if not entries:
            await ctx.send(f"No karma history for **{member.display_name}**.")
            return

        lines = [f"**Karma history for {member.display_name}:**\n"]
        for given_by_id, delta, reason, created_at in entries:
            giver = ctx.guild.get_member(given_by_id)
            giver_name = giver.display_name if giver else f"User {given_by_id}"
            sign = "+" if delta > 0 else ""
            reason_text = f" — *{reason}*" if reason else ""
            lines.append(f"`{created_at}` {sign}{delta} from {giver_name}{reason_text}")

        await ctx.send("\n".join(lines))


async def setup(bot: commands.Bot) -> None:
    db = bot.db  # type: ignore[attr-defined]
    await bot.add_cog(KarmaCog(bot, db))
