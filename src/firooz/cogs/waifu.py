from __future__ import annotations

import logging

import aiohttp
import discord
from discord.ext import commands

logger = logging.getLogger("firooz.waifu")

# waifu.im — https://docs.waifu.im
API_URL = "https://api.waifu.im/images"
USER_AGENT = "FireeozBot/1.0 (Discord bot; +https://github.com/Wintersina/firooz)"
NSFW_CHANNEL = "bot_test_zone"

# Tag slugs taken from waifu.im /tags. "Versatile" tags (waifu/maid/etc.)
# can be served as either SFW or NSFW depending on the IsNsfw filter.
SFW_TAGS = (
    "waifu", "maid", "selfies", "uniform",
    "genshin-impact", "raiden-shogun", "marin-kitagawa",
    "mori-calliope", "kamisato-ayaka", "rem",
)

NSFW_TAGS = (
    "ero", "ecchi", "hentai", "oppai", "milf", "ass", "paizuri", "oral",
    # versatile tags also work with IsNsfw=true
    "waifu", "maid", "uniform",
)

DEFAULT_SFW_TAG = "waifu"
DEFAULT_NSFW_TAG = "ecchi"


async def fetch_image(tag: str, nsfw: bool) -> str | None:
    """Fetch one image URL from waifu.im. Returns None on any failure."""
    params = {
        "IncludedTags": tag,
        "IsNsfw": "true" if nsfw else "false",
    }
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                API_URL,
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    logger.warning(
                        "waifu.im returned status %d for tag=%s nsfw=%s",
                        resp.status, tag, nsfw,
                    )
                    return None
                data = await resp.json()
    except Exception:
        logger.exception("Failed to fetch waifu.im image")
        return None

    items = data.get("items") or []
    if not items:
        return None
    return items[0].get("url")


class WaifuCog(commands.Cog, name="Waifu"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="waifu", aliases=["w"])  # type: ignore[arg-type]
    async def waifu(
        self, ctx: commands.Context[commands.Bot], tag: str = DEFAULT_SFW_TAG,
    ) -> None:
        """Get a random SFW waifu image. Try: !waifu maid, !waifu rem"""
        tag = tag.lower()
        if tag not in SFW_TAGS:
            await ctx.send(
                f"Unknown tag **{tag}**. Available: {', '.join(SFW_TAGS)}"
            )
            return

        image_url = await fetch_image(tag, nsfw=False)
        if image_url:
            embed = discord.Embed(color=0xFF69B4)
            embed.set_image(url=image_url)
            embed.set_footer(
                text=f"Tag: {tag} | Powered by waifu.im | Try: !waifu maid, !waifu rem"
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send("Couldn't fetch a waifu right now. Try again later.")

        logger.info("[#%s] %s requested sfw waifu: %s", ctx.channel, ctx.author, tag)

    @commands.command(name="waifunsfw", aliases=["wn"], hidden=True)  # type: ignore[arg-type]
    async def waifunsfw(
        self, ctx: commands.Context[commands.Bot], tag: str = DEFAULT_NSFW_TAG,
    ) -> None:
        """Get a NSFW waifu image. Only works in #bot_test_zone."""
        if not isinstance(ctx.channel, discord.TextChannel) or ctx.channel.name != NSFW_CHANNEL:
            await ctx.send(
                f"NSFW waifu commands can only be used in **#{NSFW_CHANNEL}**."
            )
            return

        tag = tag.lower()
        if tag not in NSFW_TAGS:
            await ctx.send(
                f"Unknown NSFW tag **{tag}**. Available: {', '.join(NSFW_TAGS)}"
            )
            return

        image_url = await fetch_image(tag, nsfw=True)
        if image_url:
            embed = discord.Embed(color=0xFF1493)
            embed.set_image(url=image_url)
            embed.set_footer(
                text=f"NSFW | Tag: {tag} | Powered by waifu.im"
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send("Couldn't fetch a waifu right now. Try again later.")

        logger.info("[#%s] %s requested nsfw waifu: %s", ctx.channel, ctx.author, tag)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WaifuCog(bot))
