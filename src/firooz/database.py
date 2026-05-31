from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from firooz.models import (
    Base,
    BannedTrack,
    Config,
    ImageCaption,
    Karma,
    KarmaLog,
    Memory,
    PlayedTrack,
    Poem,
    ReplyContext,
    SharedPoem,
)

MAX_REPLY_CONTEXT_BYTES = 100 * 1024 * 1024  # 100 MB cap; oldest rows are evicted past this.


class KarmaDB:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @classmethod
    async def init(cls, db_path: str) -> KarmaDB:
        url = f"sqlite+aiosqlite:///{db_path}" if db_path != ":memory:" else "sqlite+aiosqlite://"
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        return cls(session_factory)

    async def get_config(self, key: str) -> str | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Config.value).where(Config.key == key)
            )
            row = result.scalar_one_or_none()
            return row

    async def set_config(self, key: str, value: str) -> None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Config).where(Config.key == key)
            )
            existing = result.scalar_one_or_none()
            if existing is None:
                session.add(Config(key=key, value=value))
            else:
                existing.value = value
            await session.commit()

    async def update_karma(
        self,
        guild_id: int,
        user_id: int,
        delta: int,
        given_by: int = 0,
        reason: str = "",
    ) -> int:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Karma).where(
                    Karma.guild_id == guild_id, Karma.user_id == user_id
                )
            )
            karma = result.scalar_one_or_none()

            if karma is None:
                karma = Karma(guild_id=guild_id, user_id=user_id, points=delta)
                session.add(karma)
            else:
                karma.points += delta

            session.add(KarmaLog(
                guild_id=guild_id,
                user_id=user_id,
                given_by=given_by,
                delta=delta,
                reason=reason,
            ))

            await session.commit()
            return karma.points

    async def get_history(
        self, guild_id: int, user_id: int, limit: int = 10
    ) -> list[tuple[int, int, str, str]]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(
                    KarmaLog.given_by,
                    KarmaLog.delta,
                    KarmaLog.reason,
                    KarmaLog.created_at,
                )
                .where(KarmaLog.guild_id == guild_id, KarmaLog.user_id == user_id)
                .order_by(KarmaLog.created_at.desc())
                .limit(limit)
            )
            return [(row[0], row[1], row[2], str(row[3])) for row in result.all()]

    async def get_karma(self, guild_id: int, user_id: int) -> int:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Karma.points).where(
                    Karma.guild_id == guild_id, Karma.user_id == user_id
                )
            )
            points = result.scalar_one_or_none()
            return points if points is not None else 0

    async def get_leaderboard(
        self, guild_id: int, limit: int = 10
    ) -> list[tuple[int, int]]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Karma.user_id, Karma.points)
                .where(Karma.guild_id == guild_id)
                .order_by(Karma.points.desc())
                .limit(limit)
            )
            return [(row[0], row[1]) for row in result.all()]

    async def save_memory(
        self, guild_id: int, key: str, value: str, saved_by: int
    ) -> None:
        async with self._session_factory() as session:
            session.add(Memory(
                guild_id=guild_id,
                key=key.lower(),
                value=value,
                saved_by=saved_by,
            ))
            await session.commit()

    async def get_memory(self, guild_id: int, key: str) -> str | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Memory.value)
                .where(Memory.guild_id == guild_id, Memory.key == key.lower())
                .order_by(Memory.created_at.desc())
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def list_memories(self, guild_id: int, limit: int = 20) -> list[tuple[str, str, str]]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Memory.key, Memory.value, Memory.created_at)
                .where(Memory.guild_id == guild_id)
                .order_by(Memory.created_at.desc())
                .limit(limit)
            )
            return [(row[0], row[1], str(row[2])) for row in result.all()]

    async def delete_memory(self, guild_id: int, key: str) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Memory).where(
                    Memory.guild_id == guild_id, Memory.key == key.lower()
                )
            )
            memories = result.scalars().all()
            if not memories:
                return False
            for m in memories:
                await session.delete(m)
            await session.commit()
            return True

    async def record_played_track(
        self, guild_id: int, url: str, title: str, query: str
    ) -> None:
        async with self._session_factory() as session:
            session.add(PlayedTrack(
                guild_id=guild_id, url=url, title=title, query=query,
            ))
            await session.commit()

    async def get_recently_played_urls(
        self, guild_id: int, days: int = 7
    ) -> set[str]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        async with self._session_factory() as session:
            result = await session.execute(
                select(PlayedTrack.url)
                .where(
                    PlayedTrack.guild_id == guild_id,
                    PlayedTrack.played_at >= cutoff,
                )
            )
            return {row[0] for row in result.all()}

    async def ban_track(
        self, guild_id: int, url: str, title: str, banned_by: int
    ) -> bool:
        """Ban a track. Returns False if already banned."""
        async with self._session_factory() as session:
            existing = await session.execute(
                select(BannedTrack).where(
                    BannedTrack.guild_id == guild_id, BannedTrack.url == url
                )
            )
            if existing.scalar_one_or_none():
                return False
            session.add(BannedTrack(
                guild_id=guild_id, url=url, title=title, banned_by=banned_by,
            ))
            await session.commit()
            return True

    async def unban_track(self, guild_id: int, url: str) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(
                select(BannedTrack).where(
                    BannedTrack.guild_id == guild_id, BannedTrack.url == url
                )
            )
            track = result.scalar_one_or_none()
            if not track:
                return False
            await session.delete(track)
            await session.commit()
            return True

    async def get_banned_urls(self, guild_id: int) -> set[str]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(BannedTrack.url).where(BannedTrack.guild_id == guild_id)
            )
            return {row[0] for row in result.all()}

    async def list_banned_tracks(self, guild_id: int) -> list[tuple[str, str]]:
        """Return (title, url) pairs of banned tracks."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(BannedTrack.title, BannedTrack.url)
                .where(BannedTrack.guild_id == guild_id)
                .order_by(BannedTrack.banned_at.desc())
            )
            return [(row[0], row[1]) for row in result.all()]

    async def get_poem_count(self) -> int:
        async with self._session_factory() as session:
            result = await session.execute(select(func.count(Poem.id)))
            return result.scalar_one()

    async def get_random_poem(self, guild_id: int) -> Poem | None:
        """Get a random poem not shared in this guild in the past year."""
        one_year_ago = datetime.now(timezone.utc) - timedelta(days=365)
        async with self._session_factory() as session:
            recently_shared = (
                select(SharedPoem.poem_id)
                .where(
                    SharedPoem.guild_id == guild_id,
                    SharedPoem.shared_at >= one_year_ago,
                )
            )
            result = await session.execute(
                select(Poem)
                .where(Poem.id.not_in(recently_shared))
                .order_by(func.random())
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def record_shared_poem(self, guild_id: int, poem_id: int) -> None:
        async with self._session_factory() as session:
            session.add(SharedPoem(guild_id=guild_id, poem_id=poem_id))
            await session.commit()

    async def get_last_shared_time(self, guild_id: int) -> datetime | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(SharedPoem.shared_at)
                .where(SharedPoem.guild_id == guild_id)
                .order_by(SharedPoem.shared_at.desc())
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def get_last_shared_poem(self, guild_id: int) -> Poem | None:
        """Get the most recently shared poem for a guild."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(Poem)
                .join(SharedPoem, SharedPoem.poem_id == Poem.id)
                .where(SharedPoem.guild_id == guild_id)
                .order_by(SharedPoem.shared_at.desc())
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def save_reply_context(
        self,
        bot_message_id: int,
        channel_id: int,
        guild_id: int,
        cog: str,
        command: str,
        payload: dict,
    ) -> None:
        payload_str = json.dumps(payload)
        async with self._session_factory() as session:
            existing = await session.get(ReplyContext, bot_message_id)
            if existing is None:
                session.add(ReplyContext(
                    bot_message_id=bot_message_id,
                    channel_id=channel_id,
                    guild_id=guild_id,
                    cog=cog,
                    command=command,
                    payload=payload_str,
                ))
            else:
                existing.cog = cog
                existing.command = command
                existing.payload = payload_str
            await session.commit()
        await self._enforce_reply_context_cap()

    async def get_reply_context(self, bot_message_id: int) -> dict | None:
        """Return {cog, command, payload, ...} or None if missing/corrupt."""
        async with self._session_factory() as session:
            row = await session.get(ReplyContext, bot_message_id)
            if row is None:
                return None
            try:
                payload = json.loads(row.payload)
            except json.JSONDecodeError:
                return None
            return {
                "cog": row.cog,
                "command": row.command,
                "payload": payload,
                "created_at": row.created_at,
                "channel_id": row.channel_id,
                "guild_id": row.guild_id,
            }

    async def _enforce_reply_context_cap(self) -> int:
        """Delete oldest reply contexts until total payload size is under the cap.
        Returns the number of rows evicted."""
        async with self._session_factory() as session:
            total_result = await session.execute(
                select(func.coalesce(func.sum(func.length(ReplyContext.payload)), 0))
            )
            total = int(total_result.scalar() or 0)
            if total <= MAX_REPLY_CONTEXT_BYTES:
                return 0

            result = await session.execute(
                select(ReplyContext).order_by(ReplyContext.created_at.asc())
            )
            evicted = 0
            for row in result.scalars():
                if total <= MAX_REPLY_CONTEXT_BYTES:
                    break
                total -= len(row.payload)
                await session.delete(row)
                evicted += 1
            await session.commit()
            return evicted

    async def save_image_caption(
        self,
        attachment_id: int,
        message_id: int,
        content_type: str,
        caption: str,
    ) -> None:
        async with self._session_factory() as session:
            existing = await session.get(ImageCaption, attachment_id)
            if existing is None:
                session.add(ImageCaption(
                    attachment_id=attachment_id,
                    message_id=message_id,
                    content_type=content_type or "",
                    caption=caption,
                ))
            else:
                existing.caption = caption
                existing.content_type = content_type or existing.content_type
                existing.message_id = message_id
            await session.commit()

    async def get_image_captions(
        self, attachment_ids: list[int]
    ) -> dict[int, str]:
        """Bulk lookup: {attachment_id: caption} for the ones we have."""
        if not attachment_ids:
            return {}
        async with self._session_factory() as session:
            result = await session.execute(
                select(ImageCaption.attachment_id, ImageCaption.caption)
                .where(ImageCaption.attachment_id.in_(attachment_ids))
            )
            return {row[0]: row[1] for row in result.all()}

    async def close(self) -> None:
        pass
