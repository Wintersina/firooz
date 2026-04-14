from __future__ import annotations

import pytest

from firooz.database import KarmaDB


class TestUpdateKarma:
    async def test_new_user_increment(self, db: KarmaDB) -> None:
        result = await db.update_karma(guild_id=1, user_id=100, delta=1)
        assert result == 1

    async def test_new_user_decrement(self, db: KarmaDB) -> None:
        result = await db.update_karma(guild_id=1, user_id=100, delta=-1)
        assert result == -1

    async def test_accumulates(self, db: KarmaDB) -> None:
        await db.update_karma(guild_id=1, user_id=100, delta=1)
        await db.update_karma(guild_id=1, user_id=100, delta=1)
        result = await db.update_karma(guild_id=1, user_id=100, delta=1)
        assert result == 3

    async def test_mixed_deltas(self, db: KarmaDB) -> None:
        await db.update_karma(guild_id=1, user_id=100, delta=1)
        await db.update_karma(guild_id=1, user_id=100, delta=1)
        result = await db.update_karma(guild_id=1, user_id=100, delta=-1)
        assert result == 1


class TestGetKarma:
    async def test_nonexistent_user(self, db: KarmaDB) -> None:
        result = await db.get_karma(guild_id=1, user_id=999)
        assert result == 0

    async def test_existing_user(self, db: KarmaDB) -> None:
        await db.update_karma(guild_id=1, user_id=100, delta=1)
        result = await db.get_karma(guild_id=1, user_id=100)
        assert result == 1


class TestGetLeaderboard:
    async def test_empty(self, db: KarmaDB) -> None:
        result = await db.get_leaderboard(guild_id=1)
        assert result == []

    async def test_ordering(self, db: KarmaDB) -> None:
        await db.update_karma(guild_id=1, user_id=1, delta=1)
        await db.update_karma(guild_id=1, user_id=2, delta=1)
        await db.update_karma(guild_id=1, user_id=2, delta=1)
        await db.update_karma(guild_id=1, user_id=3, delta=1)
        await db.update_karma(guild_id=1, user_id=3, delta=1)
        await db.update_karma(guild_id=1, user_id=3, delta=1)
        result = await db.get_leaderboard(guild_id=1)
        assert result == [(3, 3), (2, 2), (1, 1)]

    async def test_limit(self, db: KarmaDB) -> None:
        for uid in range(1, 6):
            await db.update_karma(guild_id=1, user_id=uid, delta=uid)
        result = await db.get_leaderboard(guild_id=1, limit=3)
        assert len(result) == 3

    async def test_guild_isolation(self, db: KarmaDB) -> None:
        await db.update_karma(guild_id=1, user_id=100, delta=1)
        await db.update_karma(guild_id=2, user_id=100, delta=1)
        await db.update_karma(guild_id=2, user_id=100, delta=1)
        assert await db.get_karma(guild_id=1, user_id=100) == 1
        assert await db.get_karma(guild_id=2, user_id=100) == 2
        lb1 = await db.get_leaderboard(guild_id=1)
        assert lb1 == [(100, 1)]
        lb2 = await db.get_leaderboard(guild_id=2)
        assert lb2 == [(100, 2)]
