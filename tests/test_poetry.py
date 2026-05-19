from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from firooz.cogs.poetry import PoetryCog, _format_poem
from firooz.database import KarmaDB
from firooz.models import Poem


@pytest.fixture
async def db() -> KarmaDB:
    karma_db = await KarmaDB.init(":memory:")
    return karma_db


@pytest.fixture
async def db_with_poems(db: KarmaDB) -> KarmaDB:
    """DB pre-loaded with a few poems."""
    from firooz.models import Poem as PoemModel

    poems = [
        {"poet": "حافظ", "book_title": "دیوان حافظ", "poem_title": "غزل ۱", "text": "الا یا ایها الساقی\nادر کاسا و ناولها"},
        {"poet": "مولوی", "book_title": "مثنوی", "poem_title": "دفتر اول", "text": "بشنو از نی چون حکایت می‌کند\nاز جدایی‌ها شکایت می‌کند"},
        {"poet": "سعدی", "book_title": "گلستان", "poem_title": "باب اول", "text": "بنی‌آدم اعضای یکدیگرند\nکه در آفرینش ز یک گوهرند"},
    ]
    async with db._session_factory() as session:
        for p in poems:
            session.add(PoemModel(**p))
        await session.commit()
    return db


def _make_cog(db: KarmaDB) -> PoetryCog:
    bot = MagicMock()
    bot.wait_until_ready = AsyncMock()
    bot.guilds = []
    with patch.object(PoetryCog, "poem_loop"):
        return PoetryCog(bot, db)


# --- DB tests ---

async def test_get_poem_count_empty(db: KarmaDB) -> None:
    assert await db.get_poem_count() == 0


async def test_get_poem_count_with_poems(db_with_poems: KarmaDB) -> None:
    assert await db_with_poems.get_poem_count() == 3


async def test_get_random_poem_empty(db: KarmaDB) -> None:
    assert await db.get_random_poem(guild_id=1) is None


async def test_get_random_poem(db_with_poems: KarmaDB) -> None:
    poem = await db_with_poems.get_random_poem(guild_id=1)
    assert poem is not None
    assert poem.poet in {"حافظ", "مولوی", "سعدی"}
    assert len(poem.text) > 0


async def test_record_shared_poem(db_with_poems: KarmaDB) -> None:
    poem = await db_with_poems.get_random_poem(guild_id=1)
    assert poem is not None
    await db_with_poems.record_shared_poem(guild_id=1, poem_id=poem.id)


async def test_shared_poem_excluded(db_with_poems: KarmaDB) -> None:
    guild_id = 1
    shared_ids = set()
    for _ in range(3):
        poem = await db_with_poems.get_random_poem(guild_id)
        assert poem is not None
        assert poem.id not in shared_ids
        shared_ids.add(poem.id)
        await db_with_poems.record_shared_poem(guild_id, poem.id)

    assert await db_with_poems.get_random_poem(guild_id) is None


async def test_shared_poem_guild_isolation(db_with_poems: KarmaDB) -> None:
    poem = await db_with_poems.get_random_poem(guild_id=1)
    assert poem is not None
    await db_with_poems.record_shared_poem(guild_id=1, poem_id=poem.id)
    assert await db_with_poems.get_random_poem(guild_id=2) is not None


async def test_get_last_shared_time_empty(db: KarmaDB) -> None:
    assert await db.get_last_shared_time(guild_id=1) is None


async def test_get_last_shared_time(db_with_poems: KarmaDB) -> None:
    poem = await db_with_poems.get_random_poem(guild_id=1)
    assert poem is not None
    await db_with_poems.record_shared_poem(guild_id=1, poem_id=poem.id)
    last = await db_with_poems.get_last_shared_time(guild_id=1)
    assert last is not None


async def test_set_and_get_config(db: KarmaDB) -> None:
    assert await db.get_config("test_key") is None
    await db.set_config("test_key", "hello")
    assert await db.get_config("test_key") == "hello"
    await db.set_config("test_key", "updated")
    assert await db.get_config("test_key") == "updated"


# --- format tests ---

def test_format_poem_full() -> None:
    result = _format_poem("حافظ", "دیوان حافظ", "غزل ۱", "line1\nline2")
    assert result == "**حافظ** — دیوان حافظ — غزل ۱\n\nline1\nline2"


def test_format_poem_no_titles() -> None:
    result = _format_poem("حافظ", "", "", "line1\nline2")
    assert result == "**حافظ**\n\nline1\nline2"


def test_format_poem_book_only() -> None:
    result = _format_poem("مولوی", "مثنوی", "", "text")
    assert result == "**مولوی** — مثنوی\n\ntext"


# --- command tests ---

@patch("firooz.cogs.poetry.translate_to_english", new_callable=AsyncMock, return_value="Listen to the reed")
async def test_poem_command_includes_translation(mock_tr: MagicMock, db_with_poems: KarmaDB) -> None:
    cog = _make_cog(db_with_poems)
    ctx = MagicMock()
    ctx.guild = MagicMock()
    ctx.guild.id = 1
    ctx.send = AsyncMock()

    await cog.poem.callback(cog, ctx)
    ctx.send.assert_called_once()
    sent_text = ctx.send.call_args[0][0]
    assert "**Translation:**" in sent_text
    assert "Listen to the reed" in sent_text


@patch("firooz.cogs.poetry.translate_to_english", new_callable=AsyncMock, return_value=None)
async def test_poem_command_translation_fails_gracefully(mock_tr: MagicMock, db_with_poems: KarmaDB) -> None:
    cog = _make_cog(db_with_poems)
    ctx = MagicMock()
    ctx.guild = MagicMock()
    ctx.guild.id = 1
    ctx.send = AsyncMock()

    await cog.poem.callback(cog, ctx)
    ctx.send.assert_called_once()
    assert "**Translation:**" not in ctx.send.call_args[0][0]


async def test_poem_command_no_guild(db_with_poems: KarmaDB) -> None:
    cog = _make_cog(db_with_poems)
    ctx = MagicMock()
    ctx.guild = None
    ctx.send = AsyncMock()

    await cog.poem.callback(cog, ctx)
    ctx.send.assert_called_once_with("This command can only be used in a server.")


async def test_poem_command_empty_db(db: KarmaDB) -> None:
    cog = _make_cog(db)
    ctx = MagicMock()
    ctx.guild = MagicMock()
    ctx.guild.id = 1
    ctx.send = AsyncMock()

    await cog.poem.callback(cog, ctx)
    ctx.send.assert_called_once_with("No poems available right now!")


# --- config command tests ---

async def test_poetry_config_on(db: KarmaDB) -> None:
    cog = _make_cog(db)
    ctx = MagicMock()
    ctx.guild = MagicMock()
    ctx.send = AsyncMock()

    await cog.poetry_config.callback(cog, ctx, "on", "")
    assert await db.get_config("poetry_daily_enabled") == "true"
    assert "enabled" in ctx.send.call_args[0][0].lower()


async def test_poetry_config_off(db: KarmaDB) -> None:
    cog = _make_cog(db)
    ctx = MagicMock()
    ctx.guild = MagicMock()
    ctx.send = AsyncMock()

    await cog.poetry_config.callback(cog, ctx, "off", "")
    assert await db.get_config("poetry_daily_enabled") == "false"
    assert "disabled" in ctx.send.call_args[0][0].lower()


async def test_poetry_config_interval(db: KarmaDB) -> None:
    cog = _make_cog(db)
    ctx = MagicMock()
    ctx.guild = MagicMock()
    ctx.send = AsyncMock()

    await cog.poetry_config.callback(cog, ctx, "interval", "12")
    assert await db.get_config("poetry_daily_interval_hours") == "12"
    assert "12h" in ctx.send.call_args[0][0]


async def test_poetry_config_interval_invalid(db: KarmaDB) -> None:
    cog = _make_cog(db)
    ctx = MagicMock()
    ctx.guild = MagicMock()
    ctx.send = AsyncMock()

    await cog.poetry_config.callback(cog, ctx, "interval", "abc")
    assert "Usage" in ctx.send.call_args[0][0]


async def test_poetry_config_status_default(db: KarmaDB) -> None:
    cog = _make_cog(db)
    ctx = MagicMock()
    ctx.guild = MagicMock()
    ctx.send = AsyncMock()

    await cog.poetry_config.callback(cog, ctx, "status", "")
    sent = ctx.send.call_args[0][0]
    assert "disabled" in sent.lower()
    assert "24h" in sent


async def test_poetry_config_status_after_enable(db: KarmaDB) -> None:
    await db.set_config("poetry_daily_enabled", "true")
    await db.set_config("poetry_daily_interval_hours", "8")

    cog = _make_cog(db)
    ctx = MagicMock()
    ctx.guild = MagicMock()
    ctx.send = AsyncMock()

    await cog.poetry_config.callback(cog, ctx, "", "")
    sent = ctx.send.call_args[0][0]
    assert "enabled" in sent.lower()
    assert "8h" in sent
