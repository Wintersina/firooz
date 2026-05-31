from __future__ import annotations

import logging

import discord
from discord.ext import commands

from firooz.database import KarmaDB
from firooz.ollama import interpret_reply, query_memories

MEMORIES_REPLY_ACTIONS = [
    {
        "name": "query",
        "description": (
            "Answer a follow-up about saved memories — e.g. 'find ones "
            "about wifi', 'which look like passwords', 'translate this', "
            "'what does this mean'."
        ),
        "params": '{"focus": "<the question or topic in plain words>"}',
    },
]

LLM_UNAVAILABLE = (
    "Couldn't reach the LLM. Is Ollama running? (`ollama serve`)"
)

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

    async def _send(
        self, guild: discord.Guild, msg: str, fallback: discord.abc.Messageable
    ) -> discord.Message:
        bot_zone = _find_bot_zone(guild)
        target = bot_zone or fallback
        return await target.send(msg)

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
            return
        sent = await self._send(ctx.guild, f"**{key}** = {value}", ctx)
        await self._save_memories_context(
            sent, ctx, command="recall",
            memories=[{"key": key, "value": value, "when": ""}],
        )

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
        sent = await self._send(ctx.guild, "\n".join(lines), ctx)
        await self._save_memories_context(
            sent, ctx, command="memories",
            memories=[
                {"key": k, "value": v, "when": str(c)}
                for k, v, c in entries
            ],
        )

    async def _save_memories_context(
        self,
        sent: discord.Message,
        ctx: commands.Context[commands.Bot],
        command: str,
        memories: list[dict],
    ) -> None:
        if ctx.guild is None:
            return
        payload = {"memories": memories, "kind": command}
        try:
            await self.bot.db.save_reply_context(  # type: ignore[attr-defined]
                bot_message_id=sent.id,
                channel_id=sent.channel.id,
                guild_id=ctx.guild.id,
                cog="Remember",
                command=command,
                payload=payload,
            )
        except Exception:
            logger.exception("Failed to save memories reply context")

    @commands.Cog.listener()
    async def on_firooz_reply(
        self, message: discord.Message, context: dict
    ) -> None:
        if context.get("cog") != "Remember":
            return

        payload = context.get("payload") or {}
        memories = payload.get("memories") or []
        kind = payload.get("kind") or "memories"

        if not memories:
            return

        context_summary = (
            f"Command: !{kind}\n"
            f"Memories shown: {len(memories)}"
        )

        async with message.channel.typing():
            intent = await interpret_reply(
                reply_text=message.content,
                context_summary=context_summary,
                actions=MEMORIES_REPLY_ACTIONS,
            )

        if intent is None:
            await message.reply(LLM_UNAVAILABLE)
            return

        action = intent.get("action", "none")
        if action == "none":
            logger.info(
                "[#%s] Memories reply ignored — no clear intent (%s)",
                message.channel, intent.get("reason", ""),
            )
            return
        if action != "query":
            return

        focus = str((intent.get("params") or {}).get("focus") or message.content).strip()

        async with message.channel.typing():
            result = await query_memories(memories, focus)

        if result is None:
            await message.reply(LLM_UNAVAILABLE)
            return

        explanation = result.get("explanation") or ""
        matches = result.get("matches") or []

        lines = [f"🔎 **{focus[:120]}**"]
        if explanation:
            lines.append(f"> {explanation}")
        if matches:
            lines.append("")
            for m in matches[:10]:
                lines.append(f"• **{m['key']}** = {m['value']}")
                if m.get("translation"):
                    lines.append(f"   ↳ _{m['translation']}_")
        elif not explanation:
            lines.append("_(no clear matches found)_")

        reply_msg = await message.reply("\n".join(lines)[:1990])

        try:
            await self.bot.db.save_reply_context(  # type: ignore[attr-defined]
                bot_message_id=reply_msg.id,
                channel_id=reply_msg.channel.id,
                guild_id=message.guild.id if message.guild else 0,
                cog="Remember",
                command=kind,
                payload=payload,
            )
        except Exception:
            logger.exception("Failed to save memories follow-up reply context")

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
