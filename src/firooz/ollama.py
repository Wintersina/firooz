from __future__ import annotations

import json
import logging

import aiohttp

logger = logging.getLogger("firooz.ollama")

OLLAMA_URL = "http://127.0.0.1:11434"
MODEL = "qwen2.5:7b"


def _clamp(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


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


async def analyze_vibe(messages: list[str]) -> tuple[float, str] | None:
    """Score the overall vibe of a list of chat messages.

    Returns (score in [-1.0, 1.0], one-line summary) or None on failure.
    """
    if not messages:
        return None
    sample = [m[:200] for m in messages[:80]]
    prompt = (
        "You are scoring the emotional vibe of a Discord chat. Messages may "
        "be English, Persian/Farsi, or mixed.\n\n"
        "Scoring rules:\n"
        "- Bot commands (starting with '!'), single words, greetings, and "
        "neutral statements without clear emotion → score 0.0.\n"
        "- Only assign positive scores when messages express genuine "
        "enthusiasm, joy, kindness, hype, or wholesome connection.\n"
        "- Only assign negative scores when messages express frustration, "
        "anger, sadness, hostility, or toxicity.\n"
        "- If unsure, score 0.0 — do NOT invent narratives.\n\n"
        "Respond with a JSON object only:\n"
        '{"score": <number from -1.0 (toxic) to 1.0 (wholesome)>, '
        '"summary": "<one short sentence describing the vibe, max 100 chars, '
        'in English>"}\n\n'
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
    return score, summary


async def analyze_vibe_breakdown(grouped: dict[str, list[str]]) -> dict | None:
    """Per-person vibe breakdown.

    `grouped` is {display_name: [messages]}. Returns a dict with shape
    {"score": float, "summary": str, "people": [{"name", "score", "note"}]}
    or None on failure.
    """
    if not grouped:
        return None
    lines: list[str] = []
    for name, msgs in grouped.items():
        lines.append(f"[{name}]:")
        for m in msgs[:8]:
            lines.append(f"  - {m[:200]}")
    prompt = (
        "Score the emotional vibe of each person in this Discord chat. "
        "Messages may be English, Persian/Farsi, or mixed.\n\n"
        "Scoring rules:\n"
        "- Bot commands (starting with '!'), single words, greetings, and "
        "neutral statements without clear emotion → score 0.0.\n"
        "- Only assign positive scores when messages express genuine "
        "enthusiasm, joy, kindness, hype, or wholesome connection.\n"
        "- Only assign negative scores when messages express frustration, "
        "anger, sadness, hostility, or toxicity.\n"
        "- If a person's messages carry no clear emotion, score them 0.0 "
        "and set note to an empty string. Do NOT invent narratives.\n\n"
        "Respond with a JSON object only:\n"
        '{"score": <overall number from -1.0 to 1.0>, '
        '"summary": "<one short sentence, max 100 chars, in English>", '
        '"people": [{"name": "<display name>", '
        '"score": <number from -1.0 to 1.0>, '
        '"note": "<short reason, max 60 chars, or empty string>"}]}\n\n'
        "Messages grouped by person:\n" + "\n".join(lines)
    )
    data = await _generate_json(prompt)
    if not data or not isinstance(data.get("people"), list):
        return None
    try:
        data["score"] = _clamp(float(data.get("score", 0.0)))
    except (TypeError, ValueError):
        return None
    return data


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
