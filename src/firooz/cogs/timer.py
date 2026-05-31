from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass

import discord
from discord.ext import commands

logger = logging.getLogger("firooz.timer")

MAX_DURATION_SECS = 24 * 3600
_TOKEN_RE = re.compile(r"(\d+)\s*([a-z]*)", re.IGNORECASE)


def parse_duration(text: str) -> int | None:
    """Parse '5m', '1h30m', '90s', '5 minutes', or a bare '5' (treated as minutes)."""
    text = text.strip().lower()
    if not text:
        return None

    total = 0
    matched = False
    for m in _TOKEN_RE.finditer(text):
        value = int(m.group(1))
        unit = m.group(2)
        if unit.startswith("h"):
            total += value * 3600
        elif unit.startswith("s"):
            total += value
        else:
            # 'm', 'min', 'minute', 'minutes', or no unit at all → minutes
            total += value * 60
        matched = True

    return total if matched and total > 0 else None


def format_duration(secs: int) -> str:
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    parts: list[str] = []
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if s and h == 0:
        parts.append(f"{s}s")
    return " ".join(parts) or "0s"


@dataclass
class Timer:
    id: int
    user_id: int
    channel_id: int
    reason: str
    expires_at: float
    task: asyncio.Task[None]


class TimerCog(commands.Cog, name="Timer"):
    """Set timers that ping you when they're up."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.timers: dict[int, Timer] = {}
        self._next_id = 1

    def cog_unload(self) -> None:
        for t in list(self.timers.values()):
            if not t.task.done():
                t.task.cancel()
        self.timers.clear()

    @commands.group(name="timer", aliases=["t"], invoke_without_command=True)  # type: ignore[arg-type]
    async def timer(
        self,
        ctx: commands.Context[commands.Bot],
        duration: str,
        *,
        reason: str = "",
    ) -> None:
        """Set a timer. Usage: !timer 5m [reason] / !timer 1h30m / !timer 90s"""
        secs = parse_duration(duration)
        if secs is None:
            await ctx.reply(
                "Usage: `!timer <duration> [reason]` — e.g. `!timer 5m tea`, "
                "`!timer 1h30m`, `!timer 90s`.",
                mention_author=False,
            )
            return
        if secs > MAX_DURATION_SECS:
            await ctx.reply(
                f"Max timer is {format_duration(MAX_DURATION_SECS)}.",
                mention_author=False,
            )
            return

        timer_id = self._next_id
        self._next_id += 1
        expires_at = time.time() + secs

        task = asyncio.create_task(
            self._run_timer(timer_id, ctx.channel.id, ctx.author.id, secs, reason)
        )
        self.timers[timer_id] = Timer(
            id=timer_id,
            user_id=ctx.author.id,
            channel_id=ctx.channel.id,
            reason=reason,
            expires_at=expires_at,
            task=task,
        )

        reason_text = f" for **{reason}**" if reason else ""
        await ctx.reply(
            f"⏲️ Timer #{timer_id} set for **{format_duration(secs)}**{reason_text}. "
            f"I'll ping you when it's up.",
            mention_author=False,
        )
        logger.info(
            "[#%s] %s set timer #%d for %ds%s",
            ctx.channel, ctx.author, timer_id, secs,
            f" ({reason})" if reason else "",
        )

    async def _run_timer(
        self,
        timer_id: int,
        channel_id: int,
        user_id: int,
        secs: int,
        reason: str,
    ) -> None:
        try:
            await asyncio.sleep(secs)
        except asyncio.CancelledError:
            return
        finally:
            self.timers.pop(timer_id, None)

        channel = self.bot.get_channel(channel_id)
        if channel is None or not isinstance(
            channel,
            (discord.TextChannel, discord.VoiceChannel, discord.StageChannel, discord.Thread),
        ):
            logger.warning("Timer #%d: channel %d unavailable", timer_id, channel_id)
            return

        reason_text = f" — **{reason}**" if reason else ""
        try:
            await channel.send(
                f"⏰ <@{user_id}> your **{format_duration(secs)}** timer is up!{reason_text}"
            )
        except discord.HTTPException:
            logger.exception("Failed to send timer #%d notification", timer_id)

    @timer.command(name="list", aliases=["ls"])  # type: ignore[arg-type]
    async def timer_list(self, ctx: commands.Context[commands.Bot]) -> None:
        """Show your active timers."""
        now = time.time()
        mine = [t for t in self.timers.values() if t.user_id == ctx.author.id]
        if not mine:
            await ctx.reply("You have no active timers.", mention_author=False)
            return

        lines = [f"**Your active timers ({len(mine)}):**"]
        for t in sorted(mine, key=lambda x: x.expires_at):
            remaining = max(0, int(t.expires_at - now))
            tail = f" — *{t.reason}*" if t.reason else ""
            lines.append(f"`#{t.id}` — {format_duration(remaining)} left{tail}")
        await ctx.reply("\n".join(lines), mention_author=False)

    @timer.command(name="cancel", aliases=["c", "stop"])  # type: ignore[arg-type]
    async def timer_cancel(
        self, ctx: commands.Context[commands.Bot], timer_id: int
    ) -> None:
        """Cancel one of your timers. Usage: !timer cancel <id>"""
        t = self.timers.get(timer_id)
        if t is None:
            await ctx.reply(f"No timer with id {timer_id}.", mention_author=False)
            return
        if t.user_id != ctx.author.id:
            await ctx.reply("You can only cancel your own timers.", mention_author=False)
            return
        if not t.task.done():
            t.task.cancel()
        self.timers.pop(timer_id, None)
        await ctx.reply(f"Cancelled timer #{timer_id}.", mention_author=False)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TimerCog(bot))
