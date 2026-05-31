from __future__ import annotations

import logging

import aiohttp
import discord
from discord.ext import commands

from firooz.ollama import (
    analyze_vibe,
    analyze_vibe_breakdown,
    caption_image,
    drill_down_vibe,
    interpret_reply,
)

# Cap on bytes fetched per image attachment to avoid huge downloads.
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB

logger = logging.getLogger("firooz.vibe")

VIBE_LEVELS: list[tuple[float, str, str]] = [
    (-0.6, "toxic wasteland", "\U0001f480\U0001f480\U0001f480"),
    (-0.3, "pretty rough", "\U0001f629\U0001f629"),
    (-0.1, "kinda mid tbh", "\U0001f611"),
    (0.1,  "neutral", "\U0001f610"),
    (0.3,  "good vibes", "\U0001f60a\U0001f60a"),
    (0.5,  "great energy", "\U0001f525\U0001f525\U0001f525"),
    (0.7,  "hyped", "\U0001f680\U0001f680\U0001f680"),
    (1.1,  "off the charts wholesome", "\U0001f31f\U0001f31f\U0001f31f\U0001f31f\U0001f31f"),
]

LLM_UNAVAILABLE = (
    "Couldn't read the vibe — the LLM didn't respond. Is Ollama running? (`ollama serve`)"
)

VIBE_REPLY_ACTIONS = [
    {
        "name": "drill_down",
        "description": (
            "Answer ANY follow-up question about the prior vibe analysis. "
            "This includes: finding specific messages, explaining or "
            "justifying a person's score, defending the overall vibe rating, "
            "or quoting evidence. Examples: 'when did X express "
            "frustration', 'why was Y scored so low', 'show me the toxic "
            "messages', 'why did you say X', 'explain mike's score', "
            "'what details supported that note'. Pick this for any "
            "question, complaint, or challenge about the breakdown."
        ),
        "params": '{"focus": "<the question or topic in plain words>", '
                  '"person": "<optional display name to filter to, or empty>"}',
    },
]


def get_vibe_label(score: float) -> tuple[str, str]:
    for threshold, label, emojis in VIBE_LEVELS:
        if score < threshold:
            return label, emojis
    return VIBE_LEVELS[-1][1], VIBE_LEVELS[-1][2]


def _person_arrow(score: float) -> str:
    if score > 0.1:
        return "⬆️"
    if score < -0.1:
        return "⬇️"
    return "➡️"


def _find_person_in_payload(query: str, people: list[dict]) -> dict | None:
    """Best-effort match of a name query against a stored people list."""
    if not query or not people:
        return None
    q = query.lower().strip()
    for p in people:
        if str(p.get("name", "")).lower() == q:
            return p
    matches = [p for p in people if q in str(p.get("name", "")).lower()]
    if len(matches) == 1:
        return matches[0]
    return None


def _looks_like_question(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    if t.endswith("?"):
        return True
    starters = (
        "why", "how", "what", "when", "where", "who",
        "explain", "tell me", "show me", "which",
    )
    return any(t.startswith(s) for s in starters)


class VibeCog(commands.Cog, name="Vibe"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _collect(self, ctx: commands.Context[commands.Bot], count: int) -> list[discord.Message]:
        count = max(1, min(count, 100))
        # Bot messages and bot-command invocations carry no emotional
        # signal, so they get skipped. Image-only messages (no text but
        # with image attachments) are kept — they'll get captioned later.
        scan_cap = max(count * 4, 200)
        messages: list[discord.Message] = []
        async for msg in ctx.channel.history(limit=scan_cap):
            if msg.author.bot:
                continue
            if msg.content.startswith("!"):
                continue
            has_image = any(
                (att.content_type or "").startswith("image/")
                for att in msg.attachments
            )
            if not msg.content and not has_image:
                continue
            messages.append(msg)
            if len(messages) >= count:
                break
        return messages

    async def _render_contents(self, messages: list[discord.Message]) -> list[str]:
        """Return a list of LLM-ready content strings, same length and order
        as `messages`. Image attachments are captioned via the vision model
        (caching results in the DB) and spliced in as `[image: <caption>]`."""
        # Collect all image attachments across all messages, do one bulk
        # cache lookup, then caption misses individually.
        image_atts: list[tuple[discord.Message, discord.Attachment]] = []
        for msg in messages:
            for att in msg.attachments:
                if (att.content_type or "").startswith("image/"):
                    image_atts.append((msg, att))

        if not image_atts:
            return [m.content for m in messages]

        att_ids = [att.id for _, att in image_atts]
        cached = await self.bot.db.get_image_captions(att_ids)  # type: ignore[attr-defined]

        misses = [
            (msg, att) for msg, att in image_atts
            if att.id not in cached
        ]
        new_captions: dict[int, str] = {}
        if misses:
            logger.info(
                "vibe: captioning %d uncached image(s) (%d cached)",
                len(misses), len(cached),
            )
            async with aiohttp.ClientSession() as session:
                for msg, att in misses:
                    caption = await self._caption_one(session, msg, att)
                    if caption:
                        new_captions[att.id] = caption

        # Merge cached + newly-captioned. Persist new ones.
        captions = {**cached, **new_captions}
        for (msg, att) in misses:
            if att.id in new_captions:
                try:
                    await self.bot.db.save_image_caption(  # type: ignore[attr-defined]
                        attachment_id=att.id,
                        message_id=msg.id,
                        content_type=att.content_type or "",
                        caption=new_captions[att.id],
                    )
                except Exception:
                    logger.exception("Failed to save image caption")

        # Build the enriched content for each message.
        contents: list[str] = []
        for msg in messages:
            parts: list[str] = []
            if msg.content:
                parts.append(msg.content)
            for att in msg.attachments:
                if not (att.content_type or "").startswith("image/"):
                    continue
                cap = captions.get(att.id)
                if cap:
                    parts.append(f"[image: {cap}]")
            contents.append(" ".join(parts) if parts else "")
        return contents

    async def _caption_one(
        self,
        session: aiohttp.ClientSession,
        msg: discord.Message,
        att: discord.Attachment,
    ) -> str | None:
        if att.size and att.size > MAX_IMAGE_BYTES:
            logger.info(
                "Skipping caption for %d byte image (over %d cap)",
                att.size, MAX_IMAGE_BYTES,
            )
            return None
        try:
            async with session.get(
                att.url,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    logger.warning(
                        "Failed to fetch image (status %d): %s",
                        resp.status, att.url[:120],
                    )
                    return None
                data = await resp.read()
        except Exception:
            logger.exception("Failed to download attachment %s", att.id)
            return None
        if len(data) > MAX_IMAGE_BYTES:
            return None
        return await caption_image(data)

    @commands.group(name="vibe", aliases=["v"], invoke_without_command=True)  # type: ignore[arg-type]
    async def vibe(self, ctx: commands.Context[commands.Bot], count: int = 50) -> None:
        """Check the vibe of the channel via LLM. Usage: !vibe [10-100]"""
        if ctx.guild is None:
            await ctx.send("This command can only be used in a server.")
            return

        messages = await self._collect(ctx, count)
        if not messages:
            await ctx.send("No messages to check the vibe on yet.")
            return

        async with ctx.typing():
            contents = await self._render_contents(messages)
            result = await analyze_vibe(contents)

        if result is None:
            await ctx.send(LLM_UNAVAILABLE)
            return

        score, summary = result
        label, emojis = get_vibe_label(score)
        lines = [
            f"{emojis} **Vibe Check** {emojis}",
            f"The energy in here is **{label}** ({score:+.2f})",
        ]
        if summary:
            lines.append(f"> _{summary}_")
        lines.append(f"Based on the last {len(messages)} messages")
        sent = await ctx.send("\n".join(lines))
        await self._save_context(
            sent, ctx, command="vibe",
            overall={"score": score, "summary": summary},
            messages=messages,
            contents=contents,
        )
        logger.info(
            "[#%s] Vibe check: %s (%.2f) from %d msgs",
            ctx.channel, label, score, len(messages),
        )

    @vibe.command(name="breakdown", aliases=["bd", "who"])  # type: ignore[arg-type]
    async def vibe_breakdown(self, ctx: commands.Context[commands.Bot], count: int = 50) -> None:
        """Per-person vibe breakdown via LLM. Usage: !vibe breakdown [10-100]"""
        if ctx.guild is None:
            await ctx.send("This command can only be used in a server.")
            return

        messages = await self._collect(ctx, count)
        if not messages:
            await ctx.send("No messages to check the vibe on yet.")
            return

        async with ctx.typing():
            contents = await self._render_contents(messages)

        grouped: dict[str, list[str]] = {}
        for msg, content in zip(messages, contents):
            grouped.setdefault(msg.author.display_name, []).append(content)

        async with ctx.typing():
            data = await analyze_vibe_breakdown(grouped)

        if data is None:
            await ctx.send(LLM_UNAVAILABLE)
            return

        overall = float(data.get("score", 0.0))
        summary = str(data.get("summary") or "").strip()
        raw_people = data.get("people") or []

        people: list[dict] = []
        for p in raw_people:
            if not isinstance(p, dict):
                continue
            try:
                p_score = max(-1.0, min(1.0, float(p.get("score", 0.0))))
            except (TypeError, ValueError):
                continue
            people.append({
                "name": str(p.get("name") or "?").strip(),
                "score": p_score,
                "note": str(p.get("note") or "").strip(),
                "evidence": str(p.get("evidence") or "").strip(),
                "evidence_translation": str(p.get("evidence_translation") or "").strip(),
            })

        people.sort(key=lambda p: p["score"], reverse=True)
        label, emojis = get_vibe_label(overall)
        lines = [
            f"{emojis} **Vibe Breakdown** {emojis}",
            f"Overall: **{label}** ({overall:+.2f})",
        ]
        if summary:
            lines.append(f"> _{summary}_")

        positive = [p for p in people if p["score"] > 0.1]
        chill = [p for p in people if -0.1 <= p["score"] <= 0.1]
        negative = [p for p in people if p["score"] < -0.1]

        def _row(p: dict) -> str:
            tail = f" — {p['note']}" if p["note"] else ""
            return f"{_person_arrow(p['score'])} **{p['name']}** ({p['score']:+.2f}){tail}"

        if positive:
            lines.append("\n**Bringing the energy:**")
            lines.extend(_row(p) for p in positive)
        if chill:
            lines.append("\n**Just chillin':**")
            lines.extend(_row(p) for p in chill)
        if negative:
            lines.append("\n**Bringing it down:**")
            lines.extend(_row(p) for p in negative)

        lines.append(f"\nBased on the last {len(messages)} messages")
        sent = await ctx.send("\n".join(lines)[:1990])
        await self._save_context(
            sent, ctx, command="breakdown",
            overall={"score": overall, "summary": summary},
            messages=messages,
            contents=contents,
            people=people,
        )
        logger.info(
            "[#%s] Vibe breakdown: %s (%.2f), %d people",
            ctx.channel, label, overall, len(people),
        )


    async def _save_context(
        self,
        sent: discord.Message,
        ctx: commands.Context[commands.Bot],
        command: str,
        overall: dict,
        messages: list[discord.Message],
        contents: list[str],
        people: list[dict] | None = None,
    ) -> None:
        if ctx.guild is None:
            return
        payload = {
            "kind": command,
            "channel_name": str(ctx.channel),
            "overall": overall,
            "people": people or [],
            "messages": [
                {"author": m.author.display_name, "content": c}
                for m, c in zip(messages, contents)
            ],
            "count": len(messages),
        }
        try:
            await self.bot.db.save_reply_context(  # type: ignore[attr-defined]
                bot_message_id=sent.id,
                channel_id=sent.channel.id,
                guild_id=ctx.guild.id,
                cog="Vibe",
                command=command,
                payload=payload,
            )
        except Exception:
            logger.exception("Failed to save vibe reply context")

    @commands.Cog.listener()
    async def on_firooz_reply(
        self, message: discord.Message, context: dict
    ) -> None:
        if context.get("cog") != "Vibe":
            return

        payload = context.get("payload") or {}
        overall = payload.get("overall") or {}
        people = payload.get("people") or []
        raw_messages = payload.get("messages") or []

        # Compact summary the LLM uses to understand what was discussed.
        summary_parts = [
            f"Command: !vibe {payload.get('kind', '')}".strip(),
            f"Channel: #{payload.get('channel_name', '?')}",
            f"Overall score: {overall.get('score', 0.0):+.2f} — "
            f"{overall.get('summary', '') or 'no summary'}",
            f"Messages analyzed: {payload.get('count', 0)}",
        ]
        if people:
            top = ", ".join(
                f"{p['name']} ({float(p.get('score', 0.0)):+.2f})"
                for p in people[:10]
            )
            summary_parts.append(f"People scored: {top}")
        context_summary = "\n".join(summary_parts)

        async with message.channel.typing():
            intent = await interpret_reply(
                reply_text=message.content,
                context_summary=context_summary,
                actions=VIBE_REPLY_ACTIONS,
            )

        # Treat any question-shaped reply as a drill-down request, even if
        # the router returned 'none' or failed entirely. Stops the bot from
        # silently dropping reasonable follow-ups like "why did you say X".
        action = (intent or {}).get("action", "none")
        params = (intent or {}).get("params") or {}
        is_question = _looks_like_question(message.content)

        if intent is None and not is_question:
            await message.reply(LLM_UNAVAILABLE)
            return

        if action == "none":
            if is_question:
                logger.info(
                    "[#%s] Vibe reply: router said 'none' but content "
                    "looks like a question — forcing drill_down",
                    message.channel,
                )
                action = "drill_down"
                params = {"focus": message.content, "person": ""}
            else:
                logger.info(
                    "[#%s] Vibe reply ignored — no clear intent (%s)",
                    message.channel, (intent or {}).get("reason", ""),
                )
                return

        if action != "drill_down":
            logger.warning(
                "[#%s] Vibe reply produced unknown action: %s",
                message.channel, action,
            )
            return

        focus = str(params.get("focus") or message.content).strip()
        person = str(params.get("person") or "").strip() or None

        # Fast path: if we can pin the question to a specific person from
        # the prior breakdown, serve the stored evidence directly. The
        # quote was already verified to appear in the source during
        # analyze_vibe_breakdown — no second LLM round trip needed, and no
        # risk of the two calls disagreeing.
        target = None
        if person:
            target = _find_person_in_payload(person, people)
        if target is None:
            for p in people:
                pname = str(p.get("name") or "")
                if pname and pname.lower() in focus.lower():
                    target = p
                    break

        if target is not None:
            await self._reply_with_stored_evidence(message, target, payload)
            return

        # Broader question (no specific person) — fall through to drill_down.
        grouped: dict[str, list[str]] = {}
        for m in raw_messages:
            grouped.setdefault(m.get("author", "?"), []).append(m.get("content", ""))

        async with message.channel.typing():
            result = await drill_down_vibe(grouped, focus=focus, person=None)

        if result is None:
            await message.reply(LLM_UNAVAILABLE)
            return

        explanation = result.get("explanation") or ""
        examples = result.get("examples") or []

        lines = [f"🔎 **{focus[:120]}**"]
        if explanation:
            lines.append(f"> {explanation}")
        if examples:
            lines.append("")
            for ex in examples[:8]:
                lines.append(f"• **{ex['author']}**: {ex['excerpt']}")
                translation = ex.get("translation") or ""
                if translation:
                    lines.append(f"   ↳ _{translation}_")
        elif not explanation:
            lines.append("_(no clear matches found)_")

        reply_msg = await message.reply("\n".join(lines)[:1990])
        await self._save_followup_context(reply_msg, message, payload)

    async def _reply_with_stored_evidence(
        self, message: discord.Message, target: dict, payload: dict,
    ) -> None:
        """Answer a person-specific reply directly from the breakdown's
        captured evidence — no LLM call."""
        name = str(target.get("name") or "?")
        try:
            score = float(target.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        note = str(target.get("note") or "").strip()
        evidence = str(target.get("evidence") or "").strip()
        evidence_tr = str(target.get("evidence_translation") or "").strip()

        lines = [f"🔎 **{name}** ({score:+.2f})"]

        if evidence:
            if note:
                lines.append(f"> _{note}_")
            lines.append("")
            lines.append(f"• {evidence}")
            if evidence_tr:
                lines.append(f"   ↳ _{evidence_tr}_")
        elif abs(score) > 0.1:
            # Shouldn't happen post-fix-#1, but be defensive.
            lines.append(
                f"⚠️ The original score for **{name}** was likely off — "
                f"there's no quote in their messages that supports it."
            )
        else:
            lines.append(
                f"_{name}'s messages didn't carry clear emotion in the "
                f"analyzed window — score is neutral._"
            )

        reply_msg = await message.reply("\n".join(lines)[:1990])
        await self._save_followup_context(reply_msg, message, payload)

    async def _save_followup_context(
        self,
        reply_msg: discord.Message,
        original: discord.Message,
        payload: dict,
    ) -> None:
        """Re-register context against the bot's follow-up reply so the
        user can keep drilling."""
        try:
            await self.bot.db.save_reply_context(  # type: ignore[attr-defined]
                bot_message_id=reply_msg.id,
                channel_id=reply_msg.channel.id,
                guild_id=original.guild.id if original.guild else 0,
                cog="Vibe",
                command=payload.get("kind", "vibe"),
                payload=payload,
            )
        except Exception:
            logger.exception("Failed to save vibe follow-up reply context")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VibeCog(bot))
