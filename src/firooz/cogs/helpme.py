from __future__ import annotations

import discord
from discord.ext import commands


class HelpMeCog(commands.Cog, name="Help"):
    """Shows all available commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="commands", aliases=["cmds", "help"])  # type: ignore[arg-type]
    async def show_commands(self, ctx: commands.Context[commands.Bot]) -> None:
        """Show all available commands grouped by feature."""
        embed = discord.Embed(
            title="Firooz — Commands",
            color=0x5865F2,
        )

        cog_order = ["Karma", "Music", "Vibe", "Waifu", "Remember", "Translate", "Help"]

        for cog_name in cog_order:
            cog = self.bot.get_cog(cog_name)
            if cog is None:
                continue

            cmds = [c for c in cog.get_commands() if not c.hidden]
            if not cmds:
                continue

            lines: list[str] = []
            for cmd in sorted(cmds, key=lambda c: c.name):
                aliases = ""
                if cmd.aliases:
                    aliases = f" ({', '.join(f'!{a}' for a in cmd.aliases)})"
                desc = cmd.help or cmd.short_doc or "No description"
                lines.append(f"`!{cmd.name}`{aliases} — {desc}")

            embed.add_field(
                name=f"{'─' * 2} {cog_name} {'─' * 2}",
                value="\n".join(lines),
                inline=False,
            )

        # Add any cogs not in the explicit order
        for cog_name, cog in self.bot.cogs.items():
            if cog_name in cog_order or cog_name == "Health":
                continue
            cmds = [c for c in cog.get_commands() if not c.hidden]
            if not cmds:
                continue
            lines = []
            for cmd in sorted(cmds, key=lambda c: c.name):
                aliases = ""
                if cmd.aliases:
                    aliases = f" ({', '.join(f'!{a}' for a in cmd.aliases)})"
                desc = cmd.help or cmd.short_doc or "No description"
                lines.append(f"`!{cmd.name}`{aliases} — {desc}")
            embed.add_field(
                name=f"{'─' * 2} {cog_name} {'─' * 2}",
                value="\n".join(lines),
                inline=False,
            )

        embed.set_footer(text="Firooz Bot")
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    # Remove default help command so ours takes over
    bot.remove_command("help")
    await bot.add_cog(HelpMeCog(bot))
