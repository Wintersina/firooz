from __future__ import annotations

import logging
import re
from typing import NamedTuple

import aiohttp

logger = logging.getLogger("firooz.apple_music")

ITUNES_LOOKUP_URL = "https://itunes.apple.com/lookup"
_HOST_RE = re.compile(r"^https?://(?:[a-z]+\.)?music\.apple\.com/", re.IGNORECASE)
_SONG_ID_QUERY_RE = re.compile(r"[?&]i=(\d+)")
_SONG_PATH_RE = re.compile(r"/song/(\d+)")
_ALBUM_PATH_RE = re.compile(r"/album/(?:[^/?#]+/)?(\d+)")


class AppleTrack(NamedTuple):
    title: str
    artist: str

    @property
    def search_query(self) -> str:
        return f"{self.title} {self.artist}".strip()


def is_apple_music_url(value: str) -> bool:
    return bool(_HOST_RE.match(value.strip()))


def _extract_song_id(url: str) -> str | None:
    m = _SONG_ID_QUERY_RE.search(url) or _SONG_PATH_RE.search(url)
    return m.group(1) if m else None


def _extract_album_id(url: str) -> str | None:
    m = _ALBUM_PATH_RE.search(url)
    return m.group(1) if m else None


async def _lookup(params: dict[str, str]) -> list[dict]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                ITUNES_LOOKUP_URL,
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    logger.warning("iTunes lookup returned %d for %s", resp.status, params)
                    return []
                data = await resp.json(content_type=None)
    except Exception:
        logger.exception("iTunes lookup failed for params %s", params)
        return []
    return data.get("results", []) or []


def _as_track(entry: dict) -> AppleTrack | None:
    if entry.get("wrapperType") != "track" and entry.get("kind") != "song":
        return None
    title = (entry.get("trackName") or "").strip()
    artist = (entry.get("artistName") or "").strip()
    if not title:
        return None
    return AppleTrack(title=title, artist=artist)


async def resolve_url(url: str) -> list[AppleTrack]:
    """Resolve an Apple Music URL to one or more tracks.

    Single-track URLs return a list of length 1. Album URLs return every song
    on the album in order. Empty list if the URL can't be resolved.
    """
    song_id = _extract_song_id(url)
    if song_id:
        for entry in await _lookup({"id": song_id}):
            track = _as_track(entry)
            if track:
                return [track]
        return []

    album_id = _extract_album_id(url)
    if album_id:
        tracks: list[AppleTrack] = []
        for entry in await _lookup({"id": album_id, "entity": "song"}):
            track = _as_track(entry)
            if track:
                tracks.append(track)
        return tracks

    return []
