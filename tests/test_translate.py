from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from firooz.cogs.translate import TranslateCog


def _make_mock_bot() -> MagicMock:
    return MagicMock()


def _make_mock_ctx(
    reference: MagicMock | None = None,
) -> MagicMock:
    ctx = MagicMock()
    ctx.guild.id = 1
    ctx.author.id = 100
    ctx.author.display_name = "User100"
    ctx.send = AsyncMock()
    ctx.reply = AsyncMock()
    ctx.message.reference = reference
    ctx.channel.fetch_message = AsyncMock()
    return ctx


def _make_reply_reference(message_id: int = 5555) -> MagicMock:
    ref = MagicMock()
    ref.message_id = message_id
    return ref


def _make_ref_message(content: str = "hola mundo") -> MagicMock:
    msg = MagicMock()
    msg.content = content
    msg.reply = AsyncMock()
    return msg


class TestTranslateCommand:
    @patch("firooz.cogs.translate.translate", new_callable=AsyncMock, return_value="hello world")
    async def test_translate_reply(self, mock_translate: AsyncMock) -> None:
        """Reply to a non-English message with !tr — translates and replies to original."""
        bot = _make_mock_bot()
        cog = TranslateCog(bot)
        ref = _make_reply_reference()
        ctx = _make_mock_ctx(reference=ref)

        ref_msg = _make_ref_message(content="hola mundo")
        ctx.channel.fetch_message.return_value = ref_msg

        await cog.translate.callback(cog, ctx, text=None)

        ref_msg.reply.assert_called_once()
        call_text = ref_msg.reply.call_args[0][0]
        assert "hello world" in call_text
        assert "Translation" in call_text

    @patch("firooz.cogs.translate.translate", new_callable=AsyncMock, return_value="good morning")
    async def test_translate_inline_text(self, mock_translate: AsyncMock) -> None:
        """Use !tr <text> without replying — translates and replies to command message."""
        bot = _make_mock_bot()
        cog = TranslateCog(bot)
        ctx = _make_mock_ctx()

        await cog.translate.callback(cog, ctx, text="buenos dias")

        ctx.reply.assert_called_once()
        call_text = ctx.reply.call_args[0][0]
        assert "good morning" in call_text

    async def test_translate_no_text_no_reply(self) -> None:
        """!tr with no text and no reply — shows usage."""
        bot = _make_mock_bot()
        cog = TranslateCog(bot)
        ctx = _make_mock_ctx()

        await cog.translate.callback(cog, ctx, text=None)

        ctx.send.assert_called_once()
        call_text = ctx.send.call_args[0][0]
        assert "Usage" in call_text

    async def test_translate_reply_empty_content(self) -> None:
        """Reply to a message with no text — shows error."""
        bot = _make_mock_bot()
        cog = TranslateCog(bot)
        ref = _make_reply_reference()
        ctx = _make_mock_ctx(reference=ref)

        ref_msg = _make_ref_message(content="")
        ctx.channel.fetch_message.return_value = ref_msg

        await cog.translate.callback(cog, ctx, text=None)

        ctx.send.assert_called_once()
        call_text = ctx.send.call_args[0][0]
        assert "no text" in call_text

    @patch("firooz.cogs.translate.translate", new_callable=AsyncMock, return_value=None)
    async def test_translate_failure(self, mock_translate: AsyncMock) -> None:
        """Translation fails — shows error message."""
        bot = _make_mock_bot()
        cog = TranslateCog(bot)
        ctx = _make_mock_ctx()

        await cog.translate.callback(cog, ctx, text="something")

        ctx.send.assert_called_once()
        call_text = ctx.send.call_args[0][0]
        assert "failed" in call_text.lower()

    @patch("firooz.cogs.translate.translate", new_callable=AsyncMock, return_value="translated text")
    async def test_reply_uses_mention_author_false(self, mock_translate: AsyncMock) -> None:
        """Replies should not ping the original author."""
        bot = _make_mock_bot()
        cog = TranslateCog(bot)
        ref = _make_reply_reference()
        ctx = _make_mock_ctx(reference=ref)

        ref_msg = _make_ref_message(content="texto original")
        ctx.channel.fetch_message.return_value = ref_msg

        await cog.translate.callback(cog, ctx, text=None)

        ref_msg.reply.assert_called_once()
        assert ref_msg.reply.call_args[1]["mention_author"] is False
