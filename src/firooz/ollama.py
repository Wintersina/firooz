from __future__ import annotations

import logging

import aiohttp

logger = logging.getLogger("firooz.ollama")

OLLAMA_URL = "http://127.0.0.1:11434"
MODEL = "qwen2.5:3b"


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
                timeout=aiohttp.ClientTimeout(total=60),
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
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    logger.error("Ollama returned status %d", resp.status)
                    return None
                data = await resp.json()
                return data.get("response", "").strip() or None
    except Exception:
        logger.exception("Failed to translate via Ollama")
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
