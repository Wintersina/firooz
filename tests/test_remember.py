from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from firooz.database import KarmaDB
from firooz.cogs.remember import RememberCog


def _make_mock_bot() -> MagicMock:
    return MagicMock()


def _make_mock_ctx(
    guild_id: int = 1,
    author_id: int = 100,
    reference: MagicMock | None = None,
) -> MagicMock:
    ctx = MagicMock()
    ctx.guild.id = guild_id
    ctx.guild.text_channels = []  # No bot_zone, so _send falls back to ctx
    ctx.author.id = author_id
    ctx.author.display_name = f"User{author_id}"
    ctx.send = AsyncMock()
    ctx.message.reference = reference
    ctx.channel.fetch_message = AsyncMock()
    return ctx


def _make_reply_reference(message_id: int = 5555) -> MagicMock:
    ref = MagicMock()
    ref.message_id = message_id
    return ref


def _make_ref_message(
    content: str = "the original message",
    author_name: str = "OriginalAuthor",
    created_at: datetime | None = None,
    attachment_urls: list[str] | None = None,
) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    msg.author.display_name = author_name
    msg.created_at = created_at or datetime(2026, 4, 4, 15, 30, tzinfo=timezone.utc)
    attachments = []
    for url in (attachment_urls or []):
        att = MagicMock()
        att.url = url
        attachments.append(att)
    msg.attachments = attachments
    return msg


class TestRememberCommand:
    async def test_normal_remember(self, db: KarmaDB) -> None:
        bot = _make_mock_bot()
        cog = RememberCog(bot, db)
        ctx = _make_mock_ctx()

        await cog.remember.callback(cog, ctx, key="wifi", value="hunter2")

        ctx.send.assert_called_once()
        call_text = ctx.send.call_args[0][0]
        assert "wifi" in call_text
        assert "hunter2" in call_text

        # Verify stored in DB
        stored = await db.get_memory(1, "wifi")
        assert stored == "hunter2"

    async def test_missing_key_and_value_no_reply(self, db: KarmaDB) -> None:
        bot = _make_mock_bot()
        cog = RememberCog(bot, db)
        ctx = _make_mock_ctx()

        await cog.remember.callback(cog, ctx, key=None, value=None)

        call_text = ctx.send.call_args[0][0]
        assert "Usage" in call_text

    async def test_missing_value_no_reply(self, db: KarmaDB) -> None:
        bot = _make_mock_bot()
        cog = RememberCog(bot, db)
        ctx = _make_mock_ctx()

        await cog.remember.callback(cog, ctx, key="wifi", value=None)

        call_text = ctx.send.call_args[0][0]
        assert "Usage" in call_text

    async def test_reply_with_key(self, db: KarmaDB) -> None:
        """Reply to a message with !rem mykey — saves replied content under 'mykey'."""
        bot = _make_mock_bot()
        cog = RememberCog(bot, db)
        ref = _make_reply_reference()
        ctx = _make_mock_ctx(reference=ref)

        ref_msg = _make_ref_message(content="important info here")
        ctx.channel.fetch_message.return_value = ref_msg

        await cog.remember.callback(cog, ctx, key="mykey", value=None)

        call_text = ctx.send.call_args[0][0]
        assert "mykey" in call_text
        assert "important info here" in call_text

        stored = await db.get_memory(1, "mykey")
        assert stored == "important info here"

    async def test_reply_no_key_auto_generates(self, db: KarmaDB) -> None:
        """Reply to a message with just !rem — auto-generates key from author + timestamp."""
        bot = _make_mock_bot()
        cog = RememberCog(bot, db)
        ref = _make_reply_reference()
        ctx = _make_mock_ctx(reference=ref)

        ref_msg = _make_ref_message(
            content="save this please",
            author_name="gooznamak",
            created_at=datetime(2026, 4, 4, 15, 30, tzinfo=timezone.utc),
        )
        ctx.channel.fetch_message.return_value = ref_msg

        await cog.remember.callback(cog, ctx, key=None, value=None)

        call_text = ctx.send.call_args[0][0]
        assert "gooznamak-0404-1530" in call_text
        assert "save this please" in call_text

        stored = await db.get_memory(1, "gooznamak-0404-1530")
        assert stored == "save this please"

    async def test_reply_empty_content_no_attachments(self, db: KarmaDB) -> None:
        """Reply to a message with no text and no attachments — should error."""
        bot = _make_mock_bot()
        cog = RememberCog(bot, db)
        ref = _make_reply_reference()
        ctx = _make_mock_ctx(reference=ref)

        ref_msg = _make_ref_message(content="", attachment_urls=[])
        ctx.channel.fetch_message.return_value = ref_msg

        await cog.remember.callback(cog, ctx, key="test", value=None)

        call_text = ctx.send.call_args[0][0]
        assert "no text or attachments" in call_text

    async def test_reply_with_attachment(self, db: KarmaDB) -> None:
        """Reply to a message with a video/image — saves the attachment URL."""
        bot = _make_mock_bot()
        cog = RememberCog(bot, db)
        ref = _make_reply_reference()
        ctx = _make_mock_ctx(reference=ref)

        ref_msg = _make_ref_message(
            content="",
            attachment_urls=["https://cdn.discord.com/attachments/123/video.mp4"],
        )
        ctx.channel.fetch_message.return_value = ref_msg

        await cog.remember.callback(cog, ctx, key="funny-vid", value=None)

        stored = await db.get_memory(1, "funny-vid")
        assert stored == "https://cdn.discord.com/attachments/123/video.mp4"

    async def test_reply_with_text_and_attachment(self, db: KarmaDB) -> None:
        """Reply to a message with text + attachment — saves both."""
        bot = _make_mock_bot()
        cog = RememberCog(bot, db)
        ref = _make_reply_reference()
        ctx = _make_mock_ctx(reference=ref)

        ref_msg = _make_ref_message(
            content="check this out",
            attachment_urls=["https://cdn.discord.com/attachments/123/pic.png"],
        )
        ctx.channel.fetch_message.return_value = ref_msg

        await cog.remember.callback(cog, ctx, key="cool", value=None)

        stored = await db.get_memory(1, "cool")
        assert stored == "check this out\nhttps://cdn.discord.com/attachments/123/pic.png"

    async def test_reply_with_embed_url(self, db: KarmaDB) -> None:
        """Reply to a message with an embedded link (e.g. YouTube) — saves the embed URL."""
        bot = _make_mock_bot()
        cog = RememberCog(bot, db)
        ref = _make_reply_reference()
        ctx = _make_mock_ctx(reference=ref)

        embed = MagicMock()
        embed.url = "https://www.youtube.com/watch?v=abc123"
        ref_msg = _make_ref_message(content="", attachment_urls=[])
        ref_msg.embeds = [embed]
        ctx.channel.fetch_message.return_value = ref_msg

        await cog.remember.callback(cog, ctx, key="yt-vid", value=None)

        stored = await db.get_memory(1, "yt-vid")
        assert stored == "https://www.youtube.com/watch?v=abc123"


class TestRecallCommand:
    async def test_recall_existing(self, db: KarmaDB) -> None:
        bot = _make_mock_bot()
        cog = RememberCog(bot, db)

        await db.save_memory(guild_id=1, key="wifi", value="hunter2", saved_by=100)

        ctx = _make_mock_ctx()
        await cog.recall.callback(cog, ctx, key="wifi")

        call_text = ctx.send.call_args[0][0]
        assert "wifi" in call_text
        assert "hunter2" in call_text

    async def test_recall_nonexistent(self, db: KarmaDB) -> None:
        bot = _make_mock_bot()
        cog = RememberCog(bot, db)
        ctx = _make_mock_ctx()

        await cog.recall.callback(cog, ctx, key="nope")

        call_text = ctx.send.call_args[0][0]
        assert "don't have anything" in call_text


class TestForgetCommand:
    async def test_forget_existing(self, db: KarmaDB) -> None:
        bot = _make_mock_bot()
        cog = RememberCog(bot, db)

        await db.save_memory(guild_id=1, key="wifi", value="hunter2", saved_by=100)

        ctx = _make_mock_ctx()
        await cog.forget.callback(cog, ctx, key="wifi")

        call_text = ctx.send.call_args[0][0]
        assert "Forgot" in call_text

        stored = await db.get_memory(1, "wifi")
        assert stored is None

    async def test_forget_nonexistent(self, db: KarmaDB) -> None:
        bot = _make_mock_bot()
        cog = RememberCog(bot, db)
        ctx = _make_mock_ctx()

        await cog.forget.callback(cog, ctx, key="nope")

        call_text = ctx.send.call_args[0][0]
        assert "don't have anything" in call_text


class TestMemoriesCommand:
    async def test_list_memories(self, db: KarmaDB) -> None:
        bot = _make_mock_bot()
        cog = RememberCog(bot, db)

        await db.save_memory(guild_id=1, key="wifi", value="hunter2", saved_by=100)
        await db.save_memory(guild_id=1, key="lunch", value="pizza place", saved_by=100)

        ctx = _make_mock_ctx()
        await cog.memories.callback(cog, ctx)

        call_text = ctx.send.call_args[0][0]
        assert "wifi" in call_text
        assert "lunch" in call_text

    async def test_list_empty(self, db: KarmaDB) -> None:
        bot = _make_mock_bot()
        cog = RememberCog(bot, db)
        ctx = _make_mock_ctx()

        await cog.memories.callback(cog, ctx)

        call_text = ctx.send.call_args[0][0]
        assert "No memories saved" in call_text
