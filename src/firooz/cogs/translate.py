from __future__ import annotations

import logging

import discord
from deep_translator import GoogleTranslator
from discord.ext import commands

logger = logging.getLogger("firooz.translate")


class TranslateCog(commands.Cog, name="Translate"):
    """Translate messages to English."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="translate", aliases=["tr"])  # type: ignore[arg-type]
    async def translate(self, ctx: commands.Context[commands.Bot], *, text: str | None = None) -> None:
        """Translate text to English. Reply to a message with !tr, or use !tr <text>."""
        # Get text from replied message or command argument
        ref_msg: discord.Message | None = None
        if ctx.message.reference and ctx.message.reference.message_id:
            try:
                ref_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            except discord.NotFound:
                await ctx.send("Couldn't find the original message.")
                return

        if ref_msg:
            source_text = ref_msg.content
            if not source_text:
                await ctx.send("That message has no text to translate.")
                return
        elif text:
            source_text = text
            ref_msg = None
        else:
            await ctx.send("Usage: reply to a message with `!tr` or use `!tr <text>`")
            return

        try:
            translator = GoogleTranslator(source="auto", target="en")
            translated = translator.translate(source_text)
        except Exception:
            logger.exception("Translation failed for: %s", source_text[:50])
            await ctx.send("Translation failed. Try again later.")
            return

        if not translated or translated.strip().lower() == source_text.strip().lower():
            await ctx.send("Already in English (or couldn't detect a different language).")
            return

        reply_text = f"**Translation:** {translated}"

        # Reply directly to the original message
        if ref_msg:
            await ref_msg.reply(reply_text, mention_author=False)
        else:
            await ctx.reply(reply_text, mention_author=False)

        logger.info("[#%s] %s translated: %s", ctx.channel, ctx.author, source_text[:50])


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TranslateCog(bot))
