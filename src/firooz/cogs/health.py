from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime

from discord.ext import commands, tasks

logger = logging.getLogger("firooz.health")

# Thresholds in bytes
WARN_SIZE = 1 * 1024 * 1024 * 1024   # 1 GB
ALERT_SIZE = 5 * 1024 * 1024 * 1024  # 5 GB


def format_size(bytes_: int | float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if bytes_ < 1024:
            return f"{bytes_:.1f} {unit}"
        bytes_ /= 1024
    return f"{bytes_:.1f} TB"


def get_table_counts(db_path: str) -> list[tuple[str, int]]:
    conn = sqlite3.connect(db_path)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    counts = []
    for (name,) in tables:
        count = conn.execute(f"SELECT COUNT(*) FROM [{name}]").fetchone()[0]
        counts.append((name, count))
    conn.close()
    return counts


class HealthCog(commands.Cog, name="Health"):
    def __init__(self, bot: commands.Bot, db_path: str) -> None:
        self.bot = bot
        self.db_path = db_path

    async def cog_load(self) -> None:
        self.health_check.start()

    async def cog_unload(self) -> None:
        self.health_check.cancel()

    @tasks.loop(hours=1)
    async def health_check(self) -> None:
        await self.bot.wait_until_ready()
        self._print_status()

    def _print_status(self) -> None:
        if not os.path.exists(self.db_path):
            logger.warning("Database file not found: %s", self.db_path)
            return

        file_size = os.path.getsize(self.db_path)
        table_counts = get_table_counts(self.db_path)
        total_rows = sum(c for _, c in table_counts)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Determine status
        if file_size >= ALERT_SIZE:
            status = "RED ALERT"
            icon = "\U0001f6a8"
        elif file_size >= WARN_SIZE:
            status = "WARNING"
            icon = "\u26a0\ufe0f"
        else:
            status = "HEALTHY"
            icon = "\u2705"

        logger.info("=" * 55)
        logger.info(" %s  HEALTH CHECK — %s [%s]", icon, status, now)
        logger.info("=" * 55)
        logger.info("  DB file:     %s", self.db_path)
        logger.info("  DB size:     %s", format_size(file_size))
        logger.info("  Total rows:  %d", total_rows)

        for name, count in table_counts:
            logger.info("    %-20s %8d rows", name, count)

        logger.info("  Guilds:      %d", len(self.bot.guilds))
        logger.info("  Latency:     %.0f ms", self.bot.latency * 1000)

        if file_size >= ALERT_SIZE:
            logger.error(
                "  \U0001f6a8 DATABASE IS %s — OVER 5 GB! Consider pruning old karma_log entries.",
                format_size(file_size),
            )
        elif file_size >= WARN_SIZE:
            logger.warning(
                "  \u26a0\ufe0f  Database is %s — over 1 GB. Run 'make db-vacuum' or prune old data.",
                format_size(file_size),
            )

        logger.info("=" * 55)


async def setup(bot: commands.Bot) -> None:
    config = bot.config  # type: ignore[attr-defined]
    await bot.add_cog(HealthCog(bot, config.db_path))
