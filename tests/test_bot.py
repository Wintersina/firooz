from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from firooz.database import KarmaDB
from firooz.cogs.karma import KarmaCog
from firooz.responses import SELF_VOTE_ROASTS


def _make_mock_bot() -> MagicMock:
    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=None)
    return bot


def _make_mock_message(
    content: str,
    author_id: int = 100,
    guild_id: int = 1,
    is_text_channel: bool = False,
) -> MagicMock:
    message = MagicMock()
    message.content = content
    message.author.id = author_id
    message.author.bot = False
    message.author.display_name = f"User{author_id}"
    message.guild.id = guild_id
    message.guild.name = "TestGuild"
    message.guild.get_member = MagicMock(return_value=None)
    message.channel.send = AsyncMock()
    return message


class TestKarmaCog:
    async def test_increment_calls_db_and_replies(self, db: KarmaDB) -> None:
        bot = _make_mock_bot()
        cog = KarmaCog(bot, db)

        message = _make_mock_message("<@200>++")
        target_member = MagicMock()
        target_member.display_name = "Receiver"
        message.guild.get_member = MagicMock(return_value=target_member)

        await cog.on_cog_message(message)

        message.channel.send.assert_called_once()
        call_text = message.channel.send.call_args[0][0]
        assert "Receiver" in call_text
        assert "gained" in call_text

    async def test_decrement_calls_db_and_replies(self, db: KarmaDB) -> None:
        bot = _make_mock_bot()
        cog = KarmaCog(bot, db)

        message = _make_mock_message("<@200>--")
        target_member = MagicMock()
        target_member.display_name = "Receiver"
        message.guild.get_member = MagicMock(return_value=target_member)

        await cog.on_cog_message(message)

        call_text = message.channel.send.call_args[0][0]
        assert "lost" in call_text

    async def test_self_vote_is_roasted(self, db: KarmaDB) -> None:
        bot = _make_mock_bot()
        cog = KarmaCog(bot, db)

        message = _make_mock_message("<@100>++", author_id=100)
        message.author.display_name = "SelfVoter"

        await cog.on_cog_message(message)

        message.channel.send.assert_called_once()
        call_text = message.channel.send.call_args[0][0]
        assert "SelfVoter" in call_text
        assert any(roast in call_text for roast in SELF_VOTE_ROASTS)

        karma = await db.get_karma(guild_id=1, user_id=100)
        assert karma == 0

    async def test_no_karma_pattern_no_reply(self, db: KarmaDB) -> None:
        bot = _make_mock_bot()
        cog = KarmaCog(bot, db)

        message = _make_mock_message("just chatting")

        await cog.on_cog_message(message)

        message.channel.send.assert_not_called()

    async def test_reason_passed_through(self, db: KarmaDB) -> None:
        bot = _make_mock_bot()
        cog = KarmaCog(bot, db)

        message = _make_mock_message("<@200>++ for being awesome")
        target_member = MagicMock()
        target_member.display_name = "Receiver"
        message.guild.get_member = MagicMock(return_value=target_member)

        await cog.on_cog_message(message)

        call_text = message.channel.send.call_args[0][0]
        assert "for being awesome" in call_text
