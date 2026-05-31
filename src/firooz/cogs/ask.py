from __future__ import annotations

import logging
import re

import discord
from discord.ext import commands

from firooz.ollama import chat_reply, route_ask

logger = logging.getLogger("firooz.ask")

ASK_ACTIONS = [
    {
        "name": "chat",
        "description": "general conversation, greetings, or knowledge questions",
        "params": '{"question": "<the question or message>"}',
    },
    {
        "name": "vibe",
        "description": "check the channel's overall emotional vibe",
        "params": "{}",
    },
    {
        "name": "vibe_breakdown",
        "description": "per-person vibe breakdown of the channel",
        "params": "{}",
    },
    {
        "name": "karma_history",
        "description": "show karma history for a specific user",
        "params": '{"name": "<display name of the user>"}',
    },
    {
        "name": "karma_leaderboard",
        "description": "show top karma holders in the server",
        "params": "{}",
    },
    {
        "name": "recall",
        "description": "recall a saved memory by key",
        "params": '{"key": "<memory key>"}',
    },
    {
        "name": "memories",
        "description": "list all saved memories",
        "params": "{}",
    },
    {
        "name": "none",
        "description": "the message is empty or truly unparseable",
        "params": "{}",
    },
]

GREETING_FALLBACK = (
    "Yo. Tag me with a question, or try `!cmds` to see what I can do."
)


def _strip_bot_mention(content: str, bot_id: int) -> str:
    """Remove explicit <@id> / <@!id> mentions of the bot from the content."""
    patterns = [f"<@{bot_id}>", f"<@!{bot_id}>"]
    out = content
    for p in patterns:
        out = out.replace(p, "")
    return re.sub(r"\s+", " ", out).strip()


def _find_member(guild: discord.Guild, query: str) -> discord.Member | None:
    """Resolve a name to a single Member. Exact match wins; otherwise unique
    case-insensitive substring match on display_name or username."""
    if not query:
        return None
    q = query.lower().strip().lstrip("@")
    for m in guild.members:
        if m.display_name.lower() == q or m.name.lower() == q:
            return m
    matches = [
        m for m in guild.members
        if q in m.display_name.lower() or q in m.name.lower()
    ]
    if len(matches) == 1:
        return matches[0]
    return None


class AskCog(commands.Cog, name="Ask"):
    """Routes free-form @Firooz mentions to a cog action or a chat reply."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_cog_message(self, message: discord.Message) -> None:
        if self.bot.user is None or message.guild is None:
            return
        # Skip commands and karma actions — those have their own handlers.
        if message.content.startswith("!"):
            return
        if "++" in message.content or "--" in message.content:
            return
        # Only fire on EXPLICIT mentions (raw <@id>) — not Discord's
        # auto-mention from a reply chain.
        bot_id = self.bot.user.id
        if f"<@{bot_id}>" not in message.content and f"<@!{bot_id}>" not in message.content:
            return

        text = _strip_bot_mention(message.content, bot_id)
        if not text:
            await message.reply(GREETING_FALLBACK)
            return

        guild_name = message.guild.name if message.guild else ""

        async with message.channel.typing():
            intent = await route_ask(text, guild_name, ASK_ACTIONS)

        # If the router failed entirely or returned 'none', fall back to chat.
        action = (intent or {}).get("action") or "chat"
        if action == "none":
            action = "chat"
        params = (intent or {}).get("params") or {}

        logger.info(
            "[#%s] Ask routed → %s (%s)",
            message.channel, action,
            (intent or {}).get("reason", "fallback to chat"),
        )

        try:
            await self._dispatch(message, text, action, params, guild_name)
        except Exception:
            logger.exception("Ask dispatch failed for action=%s", action)
            await message.reply(
                "Something went wrong handling that. Try again or use `!cmds`."
            )

    async def _dispatch(
        self,
        message: discord.Message,
        original_text: str,
        action: str,
        params: dict,
        guild_name: str,
    ) -> None:
        if action == "chat":
            question = str(params.get("question") or original_text).strip()
            async with message.channel.typing():
                reply = await chat_reply(question, guild_name)
            await message.reply((reply or GREETING_FALLBACK)[:1900])
            return

        ctx = await self.bot.get_context(message)

        if action == "vibe":
            cmd = self.bot.get_command("vibe")
            if cmd:
                await ctx.invoke(cmd)
            return

        if action == "vibe_breakdown":
            vibe_group = self.bot.get_command("vibe")
            sub = vibe_group.get_command("breakdown") if vibe_group else None  # type: ignore[union-attr]
            if sub:
                await ctx.invoke(sub)
            return

        if action == "karma_history":
            name = str(params.get("name") or "").strip()
            if not name:
                await message.reply("Who's karma history? Try `@Firooz history for <name>`.")
                return
            if message.guild is None:
                return
            member = _find_member(message.guild, name)
            if member is None:
                await message.reply(f"Couldn't find a member matching **{name}**.")
                return
            cmd = self.bot.get_command("history")
            if cmd:
                await ctx.invoke(cmd, member=member)
            return

        if action == "karma_leaderboard":
            cmd = self.bot.get_command("leaderboard")
            if cmd:
                await ctx.invoke(cmd)
            return

        if action == "recall":
            key = str(params.get("key") or "").strip()
            if not key:
                await message.reply("Which memory? e.g. `@Firooz what's the wifi password`.")
                return
            cmd = self.bot.get_command("recall")
            if cmd:
                await ctx.invoke(cmd, key=key)
            return

        if action == "memories":
            cmd = self.bot.get_command("memories")
            if cmd:
                await ctx.invoke(cmd)
            return

        # Unknown action — fall back to chat
        logger.warning("Unknown ask action: %s — falling back to chat", action)
        async with message.channel.typing():
            reply = await chat_reply(original_text, guild_name)
        await message.reply((reply or GREETING_FALLBACK)[:1900])


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AskCog(bot))
