from __future__ import annotations

import logging

import discord
from discord.ext import commands

from firooz.database import KarmaDB
from firooz.karma import parse_karma_actions
from firooz.ollama import interpret_reply, summarize_history
from firooz.responses import (
    format_karma_response,
    format_leaderboard,
    format_self_vote_response,
)

HISTORY_REPLY_ACTIONS = [
    {
        "name": "summarize",
        "description": (
            "Answer a follow-up question about the karma history — e.g. "
            "'what's the trend', 'why did X give them karma', 'show me "
            "the negative ones', 'who gives them the most karma'."
        ),
        "params": '{"focus": "<the question or topic in plain words>"}',
    },
]

LLM_UNAVAILABLE = (
    "Couldn't reach the LLM. Is Ollama running? (`ollama serve`)"
)

logger = logging.getLogger("firooz.karma")

BOT_ZONE_CHANNEL = "bot_zone"

# Channel types that can host reaction-bearing messages.
# Includes voice-channel text chat and threads so karma works there too.
REACTABLE_CHANNEL_TYPES = (
    discord.TextChannel,
    discord.VoiceChannel,
    discord.StageChannel,
    discord.Thread,
)


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

# Reactions that REMOVE karma. Anything not in this set grants +1
# (or +2 if it's in SPECIAL_DOUBLES).
NEGATIVE_REACTIONS: set[str] = {
    "\U0001f44e",       # 👎 thumbs down
    "\U0001f621",       # 😡 pouting / anger
    "\U0001f92e",       # 🤮 vomit
    "\U0001f4a9",       # 💩 poop
}

# Reactions that grant +2 instead of the default +1.
SPECIAL_DOUBLES: set[str] = {
    "\U0001f923",       # 🤣 rolling on floor laughing
}

# Custom server emojis matched by name (lowercased).
CUSTOM_NEGATIVE_NAMES: set[str] = set()
CUSTOM_DOUBLE_NAMES: set[str] = {"pornhub"}


def _get_reaction_delta(emoji: discord.PartialEmoji) -> int:
    """Karma delta for a reaction: -1 for negatives, +2 for doubles,
    +1 for everything else."""
    if emoji.id is not None:
        # Custom server emoji — match by name
        name = (emoji.name or "").lower()
        if name in CUSTOM_NEGATIVE_NAMES:
            return -1
        if name in CUSTOM_DOUBLE_NAMES:
            return 2
        return 1
    # Unicode emoji — match by raw string
    emoji_str = str(emoji)
    if emoji_str in NEGATIVE_REACTIONS:
        return -1
    if emoji_str in SPECIAL_DOUBLES:
        return 2
    return 1


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
        if payload.guild_id is None or payload.member is None:
            return
        if payload.member.bot:
            return
        delta = _get_reaction_delta(payload.emoji)

        channel = self.bot.get_channel(payload.channel_id)
        if not isinstance(channel, REACTABLE_CHANNEL_TYPES):
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
        if payload.guild_id is None:
            return
        delta = _get_reaction_delta(payload.emoji)

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        reactor = guild.get_member(payload.user_id)
        if reactor is None or reactor.bot:
            return

        channel = self.bot.get_channel(payload.channel_id)
        if not isinstance(channel, REACTABLE_CHANNEL_TYPES):
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
        structured: list[dict] = []
        for given_by_id, delta, reason, created_at in entries:
            giver = ctx.guild.get_member(given_by_id)
            giver_name = giver.display_name if giver else f"User {given_by_id}"
            sign = "+" if delta > 0 else ""
            reason_text = f" — *{reason}*" if reason else ""
            lines.append(f"`{created_at}` {sign}{delta} from {giver_name}{reason_text}")
            structured.append({
                "giver": giver_name,
                "delta": delta,
                "reason": reason,
                "when": str(created_at),
            })

        sent = await ctx.send("\n".join(lines))
        await self._save_history_context(
            sent, ctx, target_id=member.id,
            target_name=member.display_name, entries=structured,
        )

    async def _save_history_context(
        self,
        sent: discord.Message,
        ctx: commands.Context[commands.Bot],
        target_id: int,
        target_name: str,
        entries: list[dict],
    ) -> None:
        if ctx.guild is None:
            return
        payload = {
            "target_id": target_id,
            "target_name": target_name,
            "entries": entries,
        }
        try:
            await self.bot.db.save_reply_context(  # type: ignore[attr-defined]
                bot_message_id=sent.id,
                channel_id=sent.channel.id,
                guild_id=ctx.guild.id,
                cog="Karma",
                command="history",
                payload=payload,
            )
        except Exception:
            logger.exception("Failed to save history reply context")

    @commands.Cog.listener()
    async def on_firooz_reply(
        self, message: discord.Message, context: dict
    ) -> None:
        if context.get("cog") != "Karma":
            return

        payload = context.get("payload") or {}
        target_name = str(payload.get("target_name") or "?")
        entries = payload.get("entries") or []

        context_summary = (
            f"Command: !history {target_name}\n"
            f"Entries shown: {len(entries)}"
        )

        async with message.channel.typing():
            intent = await interpret_reply(
                reply_text=message.content,
                context_summary=context_summary,
                actions=HISTORY_REPLY_ACTIONS,
            )

        if intent is None:
            await message.reply(LLM_UNAVAILABLE)
            return

        action = intent.get("action", "none")
        if action == "none":
            logger.info(
                "[#%s] History reply ignored — no clear intent (%s)",
                message.channel, intent.get("reason", ""),
            )
            return
        if action != "summarize":
            return

        focus = str((intent.get("params") or {}).get("focus") or message.content).strip()

        async with message.channel.typing():
            result = await summarize_history(entries, target_name, focus)

        if result is None:
            await message.reply(LLM_UNAVAILABLE)
            return

        explanation = result.get("explanation") or ""
        examples = result.get("examples") or []

        lines = [f"🔎 **{focus[:120]}** — _{target_name}_"]
        if explanation:
            lines.append(f"> {explanation}")
        if examples:
            lines.append("")
            for ex in examples[:8]:
                sign = "+" if ex.get("delta", 0) > 0 else ""
                lines.append(
                    f"• {sign}{ex.get('delta', 0)} from **{ex['giver']}**: {ex['reason']}"
                )
                if ex.get("translation"):
                    lines.append(f"   ↳ _{ex['translation']}_")
        elif not explanation:
            lines.append("_(no clear matches found)_")

        reply_msg = await message.reply("\n".join(lines)[:1990])

        try:
            await self.bot.db.save_reply_context(  # type: ignore[attr-defined]
                bot_message_id=reply_msg.id,
                channel_id=reply_msg.channel.id,
                guild_id=message.guild.id if message.guild else 0,
                cog="Karma",
                command="history",
                payload=payload,
            )
        except Exception:
            logger.exception("Failed to save history follow-up reply context")


async def setup(bot: commands.Bot) -> None:
    db = bot.db  # type: ignore[attr-defined]
    await bot.add_cog(KarmaCog(bot, db))
