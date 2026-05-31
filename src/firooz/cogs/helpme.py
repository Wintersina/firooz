from __future__ import annotations

import discord
from discord.ext import commands


def _render_command(cmd: commands.Command) -> list[str]:
    """Render a top-level command and (if it's a group) its subcommands."""
    lines: list[str] = []
    aliases = (
        f" ({', '.join(f'!{a}' for a in cmd.aliases)})" if cmd.aliases else ""
    )
    desc = cmd.help or cmd.short_doc or "No description"
    lines.append(f"`!{cmd.name}`{aliases} — {desc}")

    if isinstance(cmd, commands.Group):
        for sub in sorted(cmd.commands, key=lambda c: c.name):
            if sub.hidden:
                continue
            sub_aliases = (
                f" ({', '.join(f'!{cmd.name} {a}' for a in sub.aliases)})"
                if sub.aliases else ""
            )
            sub_desc = sub.help or sub.short_doc or "No description"
            lines.append(f"`!{cmd.name} {sub.name}`{sub_aliases} — {sub_desc}")

    # `!poem last` isn't a real subcommand — it's a positional arg — so
    # surface it manually so users can discover it from the help menu.
    if cmd.name == "poem":
        lines.append("`!poem last` — Replay the previous poem")

    return lines


def _render_cog(cog: commands.Cog) -> list[str]:
    lines: list[str] = []
    for cmd in sorted([c for c in cog.get_commands() if not c.hidden], key=lambda c: c.name):
        lines.extend(_render_command(cmd))
    return lines


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

        cog_order = ["Karma", "Music", "Vibe", "Waifu", "Remember", "Translate", "Poetry", "Timer", "Help"]

        for cog_name in cog_order:
            cog = self.bot.get_cog(cog_name)
            if cog is None:
                continue
            lines = _render_cog(cog)
            if not lines:
                continue
            embed.add_field(
                name=f"{'─' * 2} {cog_name} {'─' * 2}",
                value="\n".join(lines),
                inline=False,
            )

        # Add any cogs not in the explicit order
        for cog_name, cog in self.bot.cogs.items():
            if cog_name in cog_order or cog_name == "Health":
                continue
            lines = _render_cog(cog)
            if not lines:
                continue
            embed.add_field(
                name=f"{'─' * 2} {cog_name} {'─' * 2}",
                value="\n".join(lines),
                inline=False,
            )

        embed.set_footer(text="Firooz Bot · Tag @Firooz to chat or ask in plain English")
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    # Remove default help command so ours takes over
    bot.remove_command("help")
    await bot.add_cog(HelpMeCog(bot))
