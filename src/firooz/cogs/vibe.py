from __future__ import annotations

import logging

import discord
from discord.ext import commands
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

logger = logging.getLogger("firooz.vibe")

VIBE_LEVELS: list[tuple[float, str, str]] = [
    (-0.6, "toxic wasteland", "\U0001f480\U0001f480\U0001f480"),
    (-0.3, "pretty rough", "\U0001f629\U0001f629"),
    (-0.1, "kinda mid tbh", "\U0001f611"),
    (0.1,  "neutral", "\U0001f610"),
    (0.3,  "good vibes", "\U0001f60a\U0001f60a"),
    (0.5,  "great energy", "\U0001f525\U0001f525\U0001f525"),
    (0.7,  "hyped", "\U0001f680\U0001f680\U0001f680"),
    (1.1,  "off the charts wholesome", "\U0001f31f\U0001f31f\U0001f31f\U0001f31f\U0001f31f"),
]


def get_vibe_label(score: float) -> tuple[str, str]:
    for threshold, label, emojis in VIBE_LEVELS:
        if score < threshold:
            return label, emojis
    return VIBE_LEVELS[-1][1], VIBE_LEVELS[-1][2]


class VibeCog(commands.Cog, name="Vibe"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.analyzer = SentimentIntensityAnalyzer()

    @commands.command(name="vibe", aliases=["v"])  # type: ignore[arg-type]
    async def vibe(self, ctx: commands.Context[commands.Bot], count: int = 50) -> None:
        """Check the vibe of the channel. Optional: !vibe 100 (10-100 messages)"""
        if ctx.guild is None:
            await ctx.send("This command can only be used in a server.")
            return

        count = max(10, min(count, 100))

        messages: list[discord.Message] = []
        async for msg in ctx.channel.history(limit=count):
            if not msg.author.bot and msg.content:
                messages.append(msg)

        if len(messages) < 5:
            await ctx.send("Not enough messages to check the vibe.")
            return

        scores: list[float] = []
        for msg in messages:
            sentiment = self.analyzer.polarity_scores(msg.content)
            scores.append(sentiment["compound"])

        avg_score = sum(scores) / len(scores)
        label, emojis = get_vibe_label(avg_score)

        response = (
            f"{emojis} **Vibe Check** {emojis}\n"
            f"The energy in here is **{label}** ({avg_score:+.2f})\n"
            f"Based on the last {len(messages)} messages"
        )
        await ctx.send(response)
        logger.info("[#%s] Vibe check: %s (%.2f) from %d messages",
                     ctx.channel, label, avg_score, len(messages))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VibeCog(bot))
