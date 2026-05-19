from __future__ import annotations

import random

SELF_VOTE_ROASTS: tuple[str, ...] = (
    "Nice try. You can't boost your own karma. That's just sad. \U0001f921",
    "Awarding yourself points? The audacity. \U0001f612",
    "Self-voting detected. Deploying shame protocol. \U0001f6a8",
    "You must be fun at parties... where you vote for yourself. \U0001f389",
    "Error 403: Self-karma forbidden. Have some dignity. \U0001f6ab",
    "Imagine needing your own approval that badly. \U0001f480",
    "That's not how this works. That's not how any of this works. \U0001f926",
    "I'd let you, but my therapist said I need to set boundaries. \U0001f9d1\u200d\u2695\ufe0f",
    "Bold strategy. Let's see if it pays off. Spoiler: it won't. \U0001f4a8",
    "You just tried to high-five yourself. Think about that. \U0001f590\ufe0f",
    "Self-karma? In THIS economy? Denied. \U0001f4b8",
    "The lion does not concern himself with his own karma. Be the lion. \U0001f981",
    "Plot twist: the karma was inside you all along. But no. \U0001f52e",
)

MILESTONE_EMOJIS: dict[int, str] = {
    5: "\u2b50",
    10: "\U0001f525\U0001f525",
    25: "\U0001f680",
    50: "\U0001f3c6",
    100: "\U0001f48e\U0001f48e\U0001f48e",
    250: "\U0001f451",
    500: "\U0001f31f\U0001f31f\U0001f31f\U0001f31f",
    1000: "\U0001f386\U0001f386\U0001f386\U0001f386\U0001f386",
}


def format_karma_response(
    username: str, points: int, delta: int, reason: str = "", given_by: str = ""
) -> str:
    abs_delta = abs(delta)
    direction = "gained" if delta > 0 else "lost"
    point_word = "point" if abs_delta == 1 else "points"
    msg = f"**{username}** {direction} **{abs_delta}** {point_word}! They now have **{points}** karma."
    if given_by:
        action = "from" if delta > 0 else "by"
        msg += f" ({action} **{given_by}**)"
    if reason:
        msg += f"\n> *{reason}*"
    milestone_emoji = MILESTONE_EMOJIS.get(points)
    if milestone_emoji:
        msg += f"\n{milestone_emoji} **MILESTONE: {points} karma!** {milestone_emoji}"
    return msg


def format_self_vote_response(username: str) -> str:
    roast = random.choice(SELF_VOTE_ROASTS)
    return f"**{username}**, {roast}"


def format_leaderboard(entries: list[tuple[str, int]], guild_name: str) -> str:
    if not entries:
        return "No karma has been given yet. Be the change you wish to see."
    medals = ["\U0001f947", "\U0001f948", "\U0001f949"]
    lines = [f"**{guild_name} Karma Leaderboard**\n"]
    for i, (name, points) in enumerate(entries):
        prefix = medals[i] if i < len(medals) else f"**{i + 1}.**"
        lines.append(f"{prefix} {name} \u2014 **{points}** karma")
    return "\n".join(lines)
