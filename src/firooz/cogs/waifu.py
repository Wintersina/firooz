from __future__ import annotations

import logging

import aiohttp
import discord
from discord.ext import commands

logger = logging.getLogger("firooz.waifu")

SFW_URL = "https://api.waifu.pics/sfw/waifu"
NSFW_URL = "https://api.waifu.pics/nsfw/waifu"
NSFW_CHANNEL = "bot_test_zone"

SFW_CATEGORIES = (
    "waifu", "neko", "shinobu", "megumin", "bully", "cuddle", "cry",
    "hug", "awoo", "kiss", "lick", "pat", "smug", "bonk", "yeet",
    "blush", "smile", "wave", "highfive", "handhold", "nom", "bite",
    "glomp", "slap", "kill", "kick", "happy", "wink", "poke", "dance", "cringe",
)

NSFW_CATEGORIES = (
    "waifu", "neko", "trap", "blowjob",
)


async def fetch_image(url: str) -> str | None:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("url")
    return None


class WaifuCog(commands.Cog, name="Waifu"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="waifu", aliases=["w"])  # type: ignore[arg-type]
    async def waifu(self, ctx: commands.Context[commands.Bot], category: str = "waifu") -> None:
        """Get a random SFW waifu image. Try: !waifu neko, !waifu hug"""
        category = category.lower()
        if category not in SFW_CATEGORIES:
            await ctx.send(
                f"Unknown category **{category}**. Available: {', '.join(SFW_CATEGORIES)}"
            )
            return

        url = f"https://api.waifu.pics/sfw/{category}"
        image_url = await fetch_image(url)
        if image_url:
            embed = discord.Embed(color=0xFF69B4)
            embed.set_image(url=image_url)
            embed.set_footer(text=f"Category: {category} | Try: !waifu neko, !waifu hug, !waifu pat")
            await ctx.send(embed=embed)
        else:
            await ctx.send("Couldn't fetch a waifu right now. Try again later.")

        logger.info("[#%s] %s requested sfw waifu: %s", ctx.channel, ctx.author, category)

    @commands.command(name="waifunsfw", aliases=["wn"], hidden=True)  # type: ignore[arg-type]
    async def waifunsfw(self, ctx: commands.Context[commands.Bot], category: str = "waifu") -> None:
        """Get a NSFW waifu image. Only works in #bot_test_zone."""
        if not isinstance(ctx.channel, discord.TextChannel) or ctx.channel.name != NSFW_CHANNEL:
            await ctx.send(
                f"NSFW waifu commands can only be used in **#{NSFW_CHANNEL}**."
            )
            return

        category = category.lower()
        if category not in NSFW_CATEGORIES:
            await ctx.send(
                f"Unknown NSFW category **{category}**. Available: {', '.join(NSFW_CATEGORIES)}"
            )
            return

        url = f"https://api.waifu.pics/nsfw/{category}"
        image_url = await fetch_image(url)
        if image_url:
            embed = discord.Embed(color=0xFF1493)
            embed.set_image(url=image_url)
            embed.set_footer(text=f"NSFW | Category: {category} | Try: !wn neko, !wn waifu")
            await ctx.send(embed=embed)
        else:
            await ctx.send("Couldn't fetch a waifu right now. Try again later.")

        logger.info("[#%s] %s requested nsfw waifu: %s", ctx.channel, ctx.author, category)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WaifuCog(bot))
