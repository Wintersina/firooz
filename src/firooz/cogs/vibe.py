from __future__ import annotations

import logging

import discord
from discord.ext import commands

from firooz.ollama import analyze_vibe, analyze_vibe_breakdown

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

LLM_UNAVAILABLE = (
    "Couldn't read the vibe — the LLM didn't respond. Is Ollama running? (`ollama serve`)"
)


def get_vibe_label(score: float) -> tuple[str, str]:
    for threshold, label, emojis in VIBE_LEVELS:
        if score < threshold:
            return label, emojis
    return VIBE_LEVELS[-1][1], VIBE_LEVELS[-1][2]


def _person_arrow(score: float) -> str:
    if score > 0.1:
        return "⬆️"
    if score < -0.1:
        return "⬇️"
    return "➡️"


class VibeCog(commands.Cog, name="Vibe"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _collect(self, ctx: commands.Context[commands.Bot], count: int) -> list[discord.Message]:
        count = max(10, min(count, 100))
        # Bot messages, empty content, and bot-command invocations (which
        # carry no emotional signal) get filtered out, so scan a wider window
        # until we hit `count` real user messages (or exhaust the cap).
        scan_cap = max(count * 4, 200)
        messages: list[discord.Message] = []
        async for msg in ctx.channel.history(limit=scan_cap):
            if msg.author.bot or not msg.content:
                continue
            if msg.content.startswith("!"):
                continue
            messages.append(msg)
            if len(messages) >= count:
                break
        return messages

    @commands.group(name="vibe", aliases=["v"], invoke_without_command=True)  # type: ignore[arg-type]
    async def vibe(self, ctx: commands.Context[commands.Bot], count: int = 50) -> None:
        """Check the vibe of the channel via LLM. Usage: !vibe [10-100]"""
        if ctx.guild is None:
            await ctx.send("This command can only be used in a server.")
            return

        messages = await self._collect(ctx, count)
        if len(messages) < 5:
            await ctx.send("Not enough messages to check the vibe.")
            return

        async with ctx.typing():
            result = await analyze_vibe([m.content for m in messages])

        if result is None:
            await ctx.send(LLM_UNAVAILABLE)
            return

        score, summary = result
        label, emojis = get_vibe_label(score)
        lines = [
            f"{emojis} **Vibe Check** {emojis}",
            f"The energy in here is **{label}** ({score:+.2f})",
        ]
        if summary:
            lines.append(f"> _{summary}_")
        lines.append(f"Based on the last {len(messages)} messages")
        await ctx.send("\n".join(lines))
        logger.info(
            "[#%s] Vibe check: %s (%.2f) from %d msgs",
            ctx.channel, label, score, len(messages),
        )

    @vibe.command(name="breakdown", aliases=["bd", "who"])  # type: ignore[arg-type]
    async def vibe_breakdown(self, ctx: commands.Context[commands.Bot], count: int = 50) -> None:
        """Per-person vibe breakdown via LLM. Usage: !vibe breakdown [10-100]"""
        if ctx.guild is None:
            await ctx.send("This command can only be used in a server.")
            return

        messages = await self._collect(ctx, count)
        if len(messages) < 5:
            await ctx.send("Not enough messages to check the vibe.")
            return

        grouped: dict[str, list[str]] = {}
        for msg in messages:
            grouped.setdefault(msg.author.display_name, []).append(msg.content)

        async with ctx.typing():
            data = await analyze_vibe_breakdown(grouped)

        if data is None:
            await ctx.send(LLM_UNAVAILABLE)
            return

        overall = float(data.get("score", 0.0))
        summary = str(data.get("summary") or "").strip()
        raw_people = data.get("people") or []

        people: list[tuple[str, float, str]] = []
        for p in raw_people:
            if not isinstance(p, dict):
                continue
            try:
                p_score = max(-1.0, min(1.0, float(p.get("score", 0.0))))
            except (TypeError, ValueError):
                continue
            name = str(p.get("name") or "?").strip()
            note = str(p.get("note") or "").strip()
            people.append((name, p_score, note))

        people.sort(key=lambda t: t[1], reverse=True)
        label, emojis = get_vibe_label(overall)
        lines = [
            f"{emojis} **Vibe Breakdown** {emojis}",
            f"Overall: **{label}** ({overall:+.2f})",
        ]
        if summary:
            lines.append(f"> _{summary}_")

        positive = [p for p in people if p[1] > 0.1]
        chill = [p for p in people if -0.1 <= p[1] <= 0.1]
        negative = [p for p in people if p[1] < -0.1]

        if positive:
            lines.append("\n**Bringing the energy:**")
            for name, sc, note in positive:
                tail = f" — {note}" if note else ""
                lines.append(f"{_person_arrow(sc)} **{name}** ({sc:+.2f}){tail}")
        if chill:
            lines.append("\n**Just chillin':**")
            for name, sc, _ in chill:
                lines.append(f"{_person_arrow(sc)} **{name}** ({sc:+.2f})")
        if negative:
            lines.append("\n**Bringing it down:**")
            for name, sc, note in negative:
                tail = f" — {note}" if note else ""
                lines.append(f"{_person_arrow(sc)} **{name}** ({sc:+.2f}){tail}")

        lines.append(f"\nBased on the last {len(messages)} messages")
        await ctx.send("\n".join(lines)[:1990])
        logger.info(
            "[#%s] Vibe breakdown: %s (%.2f), %d people",
            ctx.channel, label, overall, len(people),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VibeCog(bot))
