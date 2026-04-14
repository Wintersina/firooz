from __future__ import annotations

import re
from typing import NamedTuple

GROUP_PATTERN: re.Pattern[str] = re.compile(
    r"((?:<@!?\d+>\s*)+)(\+\+|--)\s*((?:(?!<@).)*)"
)
MENTION_PATTERN: re.Pattern[str] = re.compile(r"<@!?(\d+)>")

MILESTONES: frozenset[int] = frozenset({5, 10, 25, 50, 100, 250, 500, 1000})


class KarmaAction(NamedTuple):
    user_id: int
    delta: int
    reason: str


def parse_karma_actions(content: str) -> list[KarmaAction]:
    actions: list[KarmaAction] = []
    seen: set[int] = set()
    delta_map = {"++": 1, "--": -1}

    for match in GROUP_PATTERN.finditer(content):
        mentions_block = match.group(1)
        op = match.group(2)
        reason = match.group(3).strip()
        delta = delta_map[op]
        for uid_match in MENTION_PATTERN.finditer(mentions_block):
            uid = int(uid_match.group(1))
            if uid not in seen:
                actions.append(KarmaAction(user_id=uid, delta=delta, reason=reason))
                seen.add(uid)

    return actions


def is_milestone(points: int) -> bool:
    return points in MILESTONES


def get_milestone_tier(points: int) -> int | None:
    return points if points in MILESTONES else None
