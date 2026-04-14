from __future__ import annotations

from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest

from firooz.database import KarmaDB


@pytest.fixture
async def db() -> AsyncGenerator[KarmaDB, None]:
    karma_db = await KarmaDB.init(":memory:")
    yield karma_db
    await karma_db.close()


def make_mock_message(
    content: str = "",
    author_id: int = 1000,
    guild_id: int = 9999,
    guild_name: str = "Test Guild",
    is_bot: bool = False,
) -> MagicMock:
    message = MagicMock()
    message.content = content
    message.author.id = author_id
    message.author.bot = is_bot
    message.author.display_name = f"User{author_id}"
    message.guild.id = guild_id
    message.guild.name = guild_name
    message.guild.get_member = MagicMock(return_value=None)
    message.channel.send = AsyncMock()
    return message
