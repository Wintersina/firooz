from __future__ import annotations

import base64
import json
import logging
import re

import aiohttp

logger = logging.getLogger("firooz.ollama")

OLLAMA_URL = "http://127.0.0.1:11434"
MODEL = "qwen2.5:7b"
VISION_MODEL = "qwen2.5vl:7b"


def _clamp(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _normalize_for_match(text: str) -> str:
    """Lowercase + collapse whitespace, for substring-quote matching."""
    return re.sub(r"\s+", " ", text.lower()).strip()


async def _generate_json(prompt: str, timeout_secs: float = 120) -> dict | None:
    """POST to Ollama with format=json and return the parsed object."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": MODEL,
                    "stream": False,
                    "prompt": prompt,
                    "format": "json",
                    # temperature=0 → deterministic output across runs.
                    "options": {"temperature": 0, "seed": 0},
                },
                timeout=aiohttp.ClientTimeout(total=timeout_secs),
            ) as resp:
                if resp.status != 200:
                    logger.error("Ollama returned status %d", resp.status)
                    return None
                payload = await resp.json()
    except Exception:
        logger.exception("Ollama JSON call failed")
        return None

    raw = (payload.get("response") or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Ollama returned non-JSON despite format=json: %r", raw[:200])
        return None


async def translate_to_english(text: str) -> str | None:
    """Translate text to English using local Ollama + Qwen2.5."""
    prompt = (
        "Translate the following Persian (Farsi) poem to English. "
        "Output ONLY the English translation, nothing else.\n\n"
        f"{text}"
    )
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": MODEL, "stream": False, "prompt": prompt},
                timeout=aiohttp.ClientTimeout(total=300),
            ) as resp:
                if resp.status != 200:
                    logger.error("Ollama returned status %d", resp.status)
                    return None
                data = await resp.json()
                return data.get("response", "").strip() or None
    except Exception:
        logger.exception("Failed to translate via Ollama")
        return None


async def translate(text: str, target: str = "English") -> str | None:
    """General-purpose translation using local Ollama + Qwen2.5."""
    prompt = (
        f"Translate the following text to {target}. "
        "Output ONLY the translation, nothing else.\n\n"
        f"{text}"
    )
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": MODEL, "stream": False, "prompt": prompt},
                timeout=aiohttp.ClientTimeout(total=300),
            ) as resp:
                if resp.status != 200:
                    logger.error("Ollama returned status %d", resp.status)
                    return None
                data = await resp.json()
                return data.get("response", "").strip() or None
    except Exception:
        logger.exception("Failed to translate via Ollama")
        return None


async def analyze_vibe(messages: list[str]) -> dict | None:
    """Score the overall vibe of a list of chat messages.

    Returns {"score": float, "summary": str, "evidence": str,
    "evidence_translation": str} or None on failure. Non-zero scores
    without a verifiable verbatim quote from the source are forced to 0.0.
    """
    if not messages:
        return None
    sample = [m[:200] for m in messages[:80]]
    source_normalized = _normalize_for_match(" ".join(sample))

    prompt = (
        "You are scoring the emotional vibe of a Discord chat. Messages may "
        "be English, Persian/Farsi, or mixed.\n\n"
        "CRITICAL RULES:\n"
        "- For ANY non-zero score you assign, you MUST supply an 'evidence' "
        "field containing a VERBATIM short quote (max 120 chars) from the "
        "messages below. The quote must appear word-for-word in the source — "
        "do NOT paraphrase, translate, or summarize.\n"
        "- If you cannot find such a quote, the score MUST be 0.0, the "
        "summary MUST be empty, and evidence MUST be empty.\n"
        "- Bot commands ('!...'), single words, greetings, and neutral "
        "statements have no emotional signal — score them 0.0.\n"
        "- Positive scores are for genuine enthusiasm, joy, kindness, hype, "
        "or wholesome connection. Negative scores are for frustration, "
        "anger, sadness, hostility, or toxicity.\n"
        "- Do NOT invent narratives. If the messages don't clearly express "
        "emotion, score them 0.0.\n\n"
        "Respond with a JSON object only:\n"
        '{"score": <number from -1.0 (toxic) to 1.0 (wholesome)>, '
        '"summary": "<one short sentence in English, max 100 chars, or '
        'empty string if score is 0.0>", '
        '"evidence": "<verbatim quote from the messages, max 120 chars, or '
        'empty string if score is 0.0>", '
        '"evidence_translation": "<English translation of evidence if it '
        'is NOT English, else empty string, max 120 chars>"}\n\n'
        "Messages:\n" + "\n".join(f"- {m}" for m in sample)
    )
    data = await _generate_json(prompt)
    if not data:
        return None
    try:
        score = _clamp(float(data.get("score", 0.0)))
    except (TypeError, ValueError):
        return None
    summary = str(data.get("summary") or "").strip()[:200]
    evidence = str(data.get("evidence") or "").strip()
    evidence_tr = str(data.get("evidence_translation") or "").strip()

    if abs(score) > 0.1:
        quote_ok = bool(evidence) and (
            _normalize_for_match(evidence) in source_normalized
        )
        if not quote_ok:
            logger.info(
                "vibe: dropping unsubstantiated score %.2f (evidence=%r)",
                score, evidence[:80],
            )
            score = 0.0
            summary = ""
            evidence = ""
            evidence_tr = ""

    return {
        "score": score,
        "summary": summary,
        "evidence": evidence,
        "evidence_translation": evidence_tr,
    }


async def analyze_vibe_breakdown(grouped: dict[str, list[str]]) -> dict | None:
    """Per-person vibe breakdown.

    `grouped` is {display_name: [messages]}. Returns a dict with shape
    {"score": float, "summary": str, "people": [{"name", "score", "note", "evidence"}]}
    or None on failure. Non-zero scores without a verifiable verbatim quote
    from the source messages are forced back to 0.0.
    """
    if not grouped:
        return None

    # Build prompt source AND keep the same truncated text around so we can
    # later verify the model only quotes things it actually saw.
    truncated_by_name: dict[str, str] = {}
    lines: list[str] = []
    for name, msgs in grouped.items():
        truncated = [m[:200] for m in msgs[:20]]
        truncated_by_name[name.lower()] = _normalize_for_match(" ".join(truncated))
        lines.append(f"[{name}]:")
        for m in truncated:
            lines.append(f"  - {m}")

    prompt = (
        "Score the emotional vibe of each person in this Discord chat. "
        "Messages may be English, Persian/Farsi, or mixed.\n\n"
        "CRITICAL RULES:\n"
        "- For ANY non-zero score you assign, you MUST supply an 'evidence' "
        "field containing a VERBATIM short quote (max 120 chars) from that "
        "person's messages below. The quote must appear word-for-word in "
        "the source — do NOT paraphrase, translate, or summarize.\n"
        "- If you cannot find such a quote, the score MUST be 0.0, the "
        "note MUST be an empty string, and evidence MUST be an empty string.\n"
        "- Bot commands ('!...'), single words, greetings, and neutral "
        "statements have no emotional signal — score them 0.0.\n"
        "- Positive scores are for genuine enthusiasm, joy, kindness, hype, "
        "or wholesome connection. Negative scores are for frustration, "
        "anger, sadness, hostility, or toxicity.\n"
        "- Do NOT invent narratives. If a person's messages don't clearly "
        "express emotion, score them 0.0.\n\n"
        "Respond with a JSON object only:\n"
        '{"score": <overall number from -1.0 to 1.0>, '
        '"summary": "<one short sentence, max 100 chars, in English>", '
        '"people": [{"name": "<display name>", '
        '"score": <number from -1.0 to 1.0>, '
        '"note": "<short reason, max 60 chars, or empty string>", '
        '"evidence": "<verbatim quote from this person\'s messages, '
        'max 120 chars, or empty string if score is 0.0>", '
        '"evidence_translation": "<English translation of evidence if it '
        'is NOT English, else empty string, max 120 chars>"}]}\n\n'
        "Messages grouped by person:\n" + "\n".join(lines)
    )
    data = await _generate_json(prompt)
    if not data or not isinstance(data.get("people"), list):
        return None
    try:
        data["score"] = _clamp(float(data.get("score", 0.0)))
    except (TypeError, ValueError):
        return None

    # Evidence validation pass — strip unsubstantiated scores back to 0.
    validated: list[dict] = []
    for p in data.get("people") or []:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name") or "").strip()
        try:
            score = _clamp(float(p.get("score", 0.0)))
        except (TypeError, ValueError):
            score = 0.0
        note = str(p.get("note") or "").strip()
        evidence = str(p.get("evidence") or "").strip()
        evidence_translation = str(p.get("evidence_translation") or "").strip()

        if abs(score) > 0.1:
            source = truncated_by_name.get(name.lower(), "")
            quote_ok = bool(evidence) and (
                _normalize_for_match(evidence) in source
            )
            if not quote_ok:
                logger.info(
                    "vibe.breakdown: dropping unsubstantiated score for %r "
                    "(score=%.2f, evidence=%r)",
                    name, score, evidence[:80],
                )
                score = 0.0
                note = ""
                evidence = ""
                evidence_translation = ""

        validated.append({
            "name": name,
            "score": score,
            "note": note,
            "evidence": evidence,
            "evidence_translation": evidence_translation,
        })

    data["people"] = validated
    return data


async def interpret_reply(
    reply_text: str,
    context_summary: str,
    actions: list[dict],
) -> dict | None:
    """Classify a user reply into one of the supplied actions.

    `actions` is a list of {"name": str, "description": str, "params": str}
    where params is a human-readable hint about the param schema.

    Returns {"action": str, "params": dict, "reason": str} or None on failure.
    The action will always be one of the supplied names or the literal "none".
    """
    if not reply_text.strip() or not actions:
        return None

    action_lines = []
    for a in actions:
        action_lines.append(
            f'- "{a["name"]}": {a["description"]} '
            f'(params: {a.get("params", "none")})'
        )
    action_lines.append('- "none": the reply does not clearly map to any action')

    prompt = (
        "You are an intent router for a Discord bot. A user replied to a "
        "previous bot message. Pick the single best action from the list, "
        "or 'none' if nothing fits clearly. Be conservative — if unsure, "
        "return 'none'. Do not invent actions.\n\n"
        f"Bot's previous message (context):\n{context_summary}\n\n"
        f"User's reply:\n\"{reply_text[:500]}\"\n\n"
        "Available actions:\n" + "\n".join(action_lines) + "\n\n"
        "Respond with JSON only:\n"
        '{"action": "<name or none>", '
        '"params": {<key-value pairs matching the chosen action>}, '
        '"reason": "<one short sentence, max 80 chars>"}'
    )
    data = await _generate_json(prompt, timeout_secs=60)
    if not data:
        return None
    action = str(data.get("action") or "").strip()
    if not action:
        return None
    params = data.get("params") or {}
    if not isinstance(params, dict):
        params = {}
    reason = str(data.get("reason") or "").strip()[:200]
    return {"action": action, "params": params, "reason": reason}


async def drill_down_vibe(
    grouped: dict[str, list[str]],
    focus: str,
    person: str | None = None,
) -> dict | None:
    """Re-analyze previously-scored messages focused on a specific topic/emotion.

    Returns {"explanation": str, "examples": [{"author": str, "excerpt": str}]}
    or None on failure.
    """
    if not grouped or not focus.strip():
        return None

    if person:
        filtered = {k: v for k, v in grouped.items() if k.lower() == person.lower()}
        if not filtered:
            filtered = grouped
    else:
        filtered = grouped

    lines: list[str] = []
    for name, msgs in filtered.items():
        lines.append(f"[{name}]:")
        for m in msgs[:20]:
            lines.append(f"  - {m[:250]}")

    person_clause = f"Focus only on messages from: {person}\n" if person else ""

    prompt = (
        "You previously analyzed these Discord messages for emotional vibe. "
        "A user is asking a follow-up question. Find the messages most "
        "relevant to their question and quote them VERBATIM in their "
        "original language. Be specific. If no messages clearly match, "
        "say so honestly — do NOT invent quotes. Messages may be English, "
        "Persian/Farsi, or mixed.\n\n"
        f"User's question: \"{focus[:300]}\"\n"
        f"{person_clause}\n"
        f"Messages:\n" + "\n".join(lines) + "\n\n"
        "For each quoted excerpt, if the original is NOT English, also "
        "provide an English translation. If it IS English, leave the "
        "translation field as an empty string.\n\n"
        "Respond with JSON only:\n"
        '{"explanation": "<2-4 sentences in English answering the question, max 500 chars>", '
        '"examples": [{"author": "<name>", '
        '"excerpt": "<short verbatim quote in original language, max 200 chars>", '
        '"translation": "<English translation if original is not English, else empty string, max 200 chars>"}]}\n\n'
        "If nothing matches, return examples=[] and explain that in the explanation."
    )
    data = await _generate_json(prompt, timeout_secs=180)
    if not data:
        return None

    explanation = str(data.get("explanation") or "").strip()[:600]
    raw_examples = data.get("examples") or []
    examples: list[dict] = []
    if isinstance(raw_examples, list):
        for ex in raw_examples[:10]:
            if not isinstance(ex, dict):
                continue
            author = str(ex.get("author") or "?").strip()[:60]
            excerpt = str(ex.get("excerpt") or "").strip()[:250]
            translation = str(ex.get("translation") or "").strip()[:250]
            if excerpt:
                examples.append({
                    "author": author,
                    "excerpt": excerpt,
                    "translation": translation,
                })

    if not explanation and not examples:
        return None
    return {"explanation": explanation, "examples": examples}


async def summarize_history(
    entries: list[dict],
    target_name: str,
    focus: str,
) -> dict | None:
    """Answer a follow-up question about a user's karma history.

    `entries` is a list of {"giver": str, "delta": int, "reason": str, "when": str}.
    Returns {"explanation": str, "examples": [{"giver": str, "delta": int,
    "reason": str, "translation": str}]} or None on failure.
    """
    if not entries or not focus.strip():
        return None

    lines = []
    for e in entries[:50]:
        sign = "+" if e.get("delta", 0) > 0 else ""
        lines.append(
            f"- [{e.get('when', '?')}] {sign}{e.get('delta', 0)} "
            f"from {e.get('giver', '?')}: {str(e.get('reason') or '')[:300]}"
        )

    prompt = (
        f"You are answering a follow-up question about {target_name}'s karma "
        "history on a Discord server. Entries may include reasons in English, "
        "Persian/Farsi, or mixed. Quote actual entries verbatim — do NOT "
        "invent. If nothing relevant exists, say so.\n\n"
        f"User's question: \"{focus[:300]}\"\n\n"
        f"Karma history for {target_name}:\n" + "\n".join(lines) + "\n\n"
        "For each cited entry, if the reason is NOT in English, include an "
        "English translation; otherwise leave translation as an empty string.\n\n"
        "Respond with JSON only:\n"
        '{"explanation": "<2-4 sentences in English, max 500 chars>", '
        '"examples": [{"giver": "<name>", "delta": <int>, '
        '"reason": "<verbatim reason, max 250 chars>", '
        '"translation": "<English translation if needed, else empty, max 250 chars>"}]}'
    )
    data = await _generate_json(prompt, timeout_secs=180)
    if not data:
        return None

    explanation = str(data.get("explanation") or "").strip()[:600]
    raw_examples = data.get("examples") or []
    examples: list[dict] = []
    if isinstance(raw_examples, list):
        for ex in raw_examples[:10]:
            if not isinstance(ex, dict):
                continue
            try:
                delta = int(ex.get("delta", 0))
            except (TypeError, ValueError):
                delta = 0
            giver = str(ex.get("giver") or "?").strip()[:60]
            reason = str(ex.get("reason") or "").strip()[:300]
            translation = str(ex.get("translation") or "").strip()[:300]
            if reason:
                examples.append({
                    "giver": giver,
                    "delta": delta,
                    "reason": reason,
                    "translation": translation,
                })

    if not explanation and not examples:
        return None
    return {"explanation": explanation, "examples": examples}


async def query_memories(
    memories: list[dict],
    focus: str,
) -> dict | None:
    """Answer a follow-up question about saved memories.

    `memories` is a list of {"key": str, "value": str, "when": str}.
    Returns {"explanation": str, "matches": [{"key": str, "value": str,
    "translation": str}]} or None on failure.
    """
    if not memories or not focus.strip():
        return None

    lines = []
    for m in memories[:60]:
        lines.append(
            f"- **{m.get('key', '?')}** = {str(m.get('value') or '')[:300]} "
            f"(saved {m.get('when', '?')})"
        )

    prompt = (
        "You are answering a follow-up question about saved 'remember' "
        "entries from a Discord server. Entries may be in English, "
        "Persian/Farsi, or mixed. Return ONLY entries from the list — do "
        "NOT invent. If nothing matches, say so.\n\n"
        f"User's question: \"{focus[:300]}\"\n\n"
        "Saved memories:\n" + "\n".join(lines) + "\n\n"
        "For each matched entry, if the value is NOT in English, include "
        "an English translation; otherwise leave translation empty.\n\n"
        "Respond with JSON only:\n"
        '{"explanation": "<2-4 sentences in English, max 500 chars>", '
        '"matches": [{"key": "<key>", "value": "<verbatim value, max 300 chars>", '
        '"translation": "<English translation if needed, else empty, max 300 chars>"}]}'
    )
    data = await _generate_json(prompt, timeout_secs=180)
    if not data:
        return None

    explanation = str(data.get("explanation") or "").strip()[:600]
    raw_matches = data.get("matches") or []
    matches: list[dict] = []
    if isinstance(raw_matches, list):
        for m in raw_matches[:15]:
            if not isinstance(m, dict):
                continue
            key = str(m.get("key") or "?").strip()[:80]
            value = str(m.get("value") or "").strip()[:400]
            translation = str(m.get("translation") or "").strip()[:400]
            if value:
                matches.append({
                    "key": key,
                    "value": value,
                    "translation": translation,
                })

    if not explanation and not matches:
        return None
    return {"explanation": explanation, "matches": matches}


async def route_ask(
    text: str,
    guild_name: str,
    actions: list[dict],
) -> dict | None:
    """Classify a free-form @mention into one of the supplied bot actions,
    a 'chat' fallback, or 'none' if unparseable.

    Returns {"action": str, "params": dict, "reason": str} or None on failure.
    """
    if not text.strip() or not actions:
        return None

    action_lines = []
    for a in actions:
        action_lines.append(
            f'- "{a["name"]}": {a["description"]} '
            f'(params: {a.get("params", "{}")})'
        )

    prompt = (
        "You are routing a user's message addressed to a Discord bot named "
        "Firooz. Pick the single best action from the list. Use 'chat' for "
        "general conversation, greetings, or knowledge questions that don't "
        "fit a specific action. Use 'none' only if the message is empty or "
        "truly unparseable.\n\n"
        f"Server: {guild_name or 'unknown'}\n"
        f"User said: \"{text[:500]}\"\n\n"
        "Available actions:\n" + "\n".join(action_lines) + "\n\n"
        "Examples:\n"
        '"what\'s the vibe in here" → {"action":"vibe","params":{},"reason":"asking for channel vibe"}\n'
        '"how is sara doing on karma" → {"action":"karma_history","params":{"name":"sara"},"reason":"karma history for sara"}\n'
        '"what\'s the wifi password" → {"action":"recall","params":{"key":"wifi"},"reason":"recall wifi memory"}\n'
        '"yo what\'s up" → {"action":"chat","params":{"question":"what\'s up"},"reason":"casual greeting"}\n'
        '"what\'s the capital of france" → {"action":"chat","params":{"question":"what\'s the capital of france"},"reason":"general knowledge"}\n\n'
        "Respond with JSON only:\n"
        '{"action": "<name>", "params": {<extracted params>}, '
        '"reason": "<one sentence, max 80 chars>"}'
    )
    data = await _generate_json(prompt, timeout_secs=60)
    if not data:
        return None
    action = str(data.get("action") or "").strip()
    if not action:
        return None
    params = data.get("params") or {}
    if not isinstance(params, dict):
        params = {}
    reason = str(data.get("reason") or "").strip()[:200]
    return {"action": action, "params": params, "reason": reason}


async def chat_reply(question: str, guild_name: str = "") -> str | None:
    """Conversational reply from Firooz. Short, 1-3 sentences."""
    if not question.strip():
        return None
    where = f"in the '{guild_name}' Discord server " if guild_name else ""
    prompt = (
        f"You are Firooz, a friendly Discord bot {where}helping a small group of "
        "friends. The user is chatting with you directly. Respond conversationally "
        "and concisely (1-3 sentences max). If you don't know something, say so "
        "honestly — don't make things up. You can reply in English or Persian/Farsi "
        "depending on what the user used.\n\n"
        f"User: {question[:800]}\n\n"
        "Firooz:"
    )
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": MODEL,
                    "stream": False,
                    "prompt": prompt,
                    "options": {"temperature": 0.7},
                },
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status != 200:
                    logger.error("Ollama returned status %d", resp.status)
                    return None
                data = await resp.json()
                reply = (data.get("response") or "").strip()
                return reply or None
    except Exception:
        logger.exception("chat_reply failed")
        return None


async def caption_image(image_bytes: bytes) -> str | None:
    """One-sentence caption (with emotional tone) of an image.

    Returns the caption text, or None on failure. Uses the vision model
    configured at VISION_MODEL.
    """
    if not image_bytes:
        return None
    b64 = base64.b64encode(image_bytes).decode("ascii")
    prompt = (
        "Describe this image in ONE short sentence (max 100 chars). "
        "Focus on what's depicted AND any emotional tone the image carries "
        "(funny, frustrating, celebratory, sad, sarcastic, neutral, etc.). "
        "Examples: 'a frustrated person holding a broken phone', "
        "'screenshot of an error message — looks annoying', "
        "'celebratory group photo with confetti', "
        "'sarcastic meme about meetings', 'a cute cat — wholesome'."
    )
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": VISION_MODEL,
                    "stream": False,
                    "prompt": prompt,
                    "images": [b64],
                    "options": {"temperature": 0, "seed": 0},
                },
                timeout=aiohttp.ClientTimeout(total=180),
            ) as resp:
                if resp.status != 200:
                    logger.error(
                        "Vision model returned status %d (is %s pulled?)",
                        resp.status, VISION_MODEL,
                    )
                    return None
                data = await resp.json()
                caption = (data.get("response") or "").strip()
                # Collapse whitespace and trim hard cap
                caption = re.sub(r"\s+", " ", caption)[:240]
                return caption or None
    except Exception:
        logger.exception("caption_image failed")
        return None


async def is_ollama_running() -> bool:
    """Check if Ollama is reachable."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                OLLAMA_URL,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                return resp.status == 200
    except Exception:
        return False
