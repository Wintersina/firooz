from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field

import discord
import yt_dlp
from discord.ext import commands

from firooz.database import KarmaDB

logger = logging.getLogger("firooz.music")

YTDL_OPTIONS: dict[str, object] = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
}

FFMPEG_OPTIONS: dict[str, str] = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

MAX_QUEUE_SIZE = 50
MAX_MIX_SONGS = 50


@dataclass
class Track:
    title: str
    url: str
    stream_url: str
    requested_by: str
    duration: str = ""


@dataclass
class GuildQueue:
    tracks: list[Track] = field(default_factory=list)
    current: Track | None = None
    loop: bool = False
    mix_query: str | None = None  # When set, autoplay keeps finding new songs
    mix_count: int = 0  # How many songs mix mode has played
    played_urls: set[str] = field(default_factory=set)  # Track what's been played to avoid repeats


class MusicCog(commands.Cog, name="Music"):
    """Play music from YouTube in voice channels."""

    def __init__(self, bot: commands.Bot, db: KarmaDB) -> None:
        self.bot = bot
        self.db = db
        self.queues: dict[int, GuildQueue] = {}

    def _get_queue(self, guild_id: int) -> GuildQueue:
        if guild_id not in self.queues:
            self.queues[guild_id] = GuildQueue()
        return self.queues[guild_id]

    async def _record_track(self, guild_id: int, track: Track, query: str = "") -> None:
        """Record a track to DB so it won't repeat for a week."""
        try:
            await self.db.record_played_track(guild_id, track.url, track.title, query)
        except Exception:
            logger.exception("Failed to record played track: %s", track.title)

    async def _excluded_urls(self, guild_id: int) -> set[str]:
        """Return URLs to skip: banned, currently queued, in-session played, and recently played."""
        queue = self._get_queue(guild_id)
        urls: set[str] = set(queue.played_urls)
        if queue.current:
            urls.add(queue.current.url)
        for t in queue.tracks:
            urls.add(t.url)
        # Banned tracks — never play these
        banned_urls = await self.db.get_banned_urls(guild_id)
        urls.update(banned_urls)
        # Recently played in last 7 days
        db_urls = await self.db.get_recently_played_urls(guild_id)
        urls.update(db_urls)
        return urls

    async def _search(self, query: str, guild_id: int | None = None) -> Track | None:
        search_opts = {**YTDL_OPTIONS, "default_search": "ytsearch10"}
        ytdl = yt_dlp.YoutubeDL(search_opts)
        loop = asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(
                None, lambda: ytdl.extract_info(query, download=False)
            )
        except Exception:
            logger.exception("yt-dlp search failed for: %s", query)
            return None

        if data is None:
            return None

        entries = [e for e in data.get("entries", [data]) if e is not None]
        if not entries:
            return None

        used_urls = await self._excluded_urls(guild_id) if guild_id else set()
        banned_urls = await self.db.get_banned_urls(guild_id) if guild_id else set()

        # Shuffle so we don't always pick the same result
        random.shuffle(entries)

        # Pick the first result not excluded
        chosen = None
        for entry in entries:
            url = entry.get("webpage_url", "")
            if url in banned_urls:
                logger.info("Skipping banned track: %s [%s]", entry.get("title", "?"), url)
                continue
            if url not in used_urls:
                chosen = entry
                break
        # Fallback: pick a random non-banned one if all were recently played
        if chosen is None:
            non_banned = [e for e in entries if e.get("webpage_url", "") not in banned_urls]
            if non_banned:
                chosen = random.choice(non_banned)
        if chosen is None:
            return None

        duration_secs = chosen.get("duration", 0)
        mins, secs = divmod(int(duration_secs), 60)
        duration_str = f"{mins}:{secs:02d}"

        return Track(
            title=chosen.get("title", "Unknown"),
            url=chosen.get("webpage_url", ""),
            stream_url=chosen.get("url", ""),
            requested_by="",
            duration=duration_str,
        )

    def _play_next(self, guild_id: int) -> None:
        queue = self._get_queue(guild_id)
        guild = self.bot.get_guild(guild_id)
        if guild is None or guild.voice_client is None:
            return

        vc = guild.voice_client
        assert isinstance(vc, discord.VoiceClient)

        # Track what we just played (in-session + DB)
        if queue.current:
            queue.played_urls.add(queue.current.url)
            asyncio.run_coroutine_threadsafe(
                self._record_track(guild_id, queue.current, queue.mix_query or ""),
                self.bot.loop,
            )

        if queue.loop and queue.current:
            source = discord.FFmpegPCMAudio(queue.current.stream_url, **FFMPEG_OPTIONS)
            vc.play(source, after=lambda e: self._play_next(guild_id))
            return

        if not queue.tracks and queue.mix_query:
            # Mix mode: auto-fetch next song in the background
            asyncio.run_coroutine_threadsafe(
                self._mix_next(guild_id), self.bot.loop
            )
            return

        if not queue.tracks:
            queue.current = None
            return

        track = queue.tracks.pop(0)
        queue.current = track
        source = discord.FFmpegPCMAudio(track.stream_url, **FFMPEG_OPTIONS)
        vc.play(source, after=lambda e: self._play_next(guild_id))
        logger.info("Now playing: %s", track.title)

    async def _mix_next(self, guild_id: int) -> None:
        """Auto-search and play the next song for mix mode."""
        queue = self._get_queue(guild_id)
        guild = self.bot.get_guild(guild_id)
        if guild is None or guild.voice_client is None or queue.mix_query is None:
            return

        vc = guild.voice_client
        assert isinstance(vc, discord.VoiceClient)

        if queue.mix_count >= MAX_MIX_SONGS:
            logger.info("Mix mode: reached %d song limit for '%s'", MAX_MIX_SONGS, queue.mix_query)
            queue.mix_query = None
            queue.current = None
            return

        track = await self._search(queue.mix_query, guild_id=guild_id)
        if track is None:
            logger.warning("Mix mode: no more results for '%s'", queue.mix_query)
            queue.mix_query = None
            queue.current = None
            return

        queue.mix_count += 1
        track.requested_by = "Mix"
        queue.current = track
        source = discord.FFmpegPCMAudio(track.stream_url, **FFMPEG_OPTIONS)
        vc.play(source, after=lambda e: self._play_next(guild_id))
        await self._record_track(guild_id, track, queue.mix_query or "")
        logger.info("Mix auto-playing (%d/%d): %s [%s]", queue.mix_count, MAX_MIX_SONGS, track.title, track.url)

    @commands.command(name="play", aliases=["p"])  # type: ignore[arg-type]
    async def play(self, ctx: commands.Context[commands.Bot], *, query: str) -> None:
        """Play a song from YouTube. Accepts a search query or URL."""
        if ctx.author.voice is None or ctx.author.voice.channel is None:  # type: ignore[union-attr]
            await ctx.send("You need to be in a voice channel.")
            return

        voice_channel = ctx.author.voice.channel  # type: ignore[union-attr]

        # Connect or move to the user's channel
        if ctx.voice_client is None:
            vc = await voice_channel.connect()
        elif ctx.voice_client.channel != voice_channel:
            await ctx.voice_client.move_to(voice_channel)
            vc = ctx.voice_client
        else:
            vc = ctx.voice_client

        assert isinstance(vc, discord.VoiceClient)

        await ctx.send(f"Searching for **{query}**...")
        track = await self._search(query, guild_id=ctx.guild.id if ctx.guild else None)
        if track is None:
            await ctx.send("Couldn't find anything for that query.")
            return

        track.requested_by = ctx.author.display_name
        queue = self._get_queue(ctx.guild.id)  # type: ignore[union-attr]

        if vc.is_playing() or vc.is_paused():
            if len(queue.tracks) >= MAX_QUEUE_SIZE:
                await ctx.send(f"Queue is full ({MAX_QUEUE_SIZE} tracks max).")
                return
            queue.tracks.append(track)
            await ctx.send(
                f"Added to queue: **{track.title}** [{track.duration}] "
                f"(#{len(queue.tracks)} in queue)"
            )
        else:
            queue.current = track
            source = discord.FFmpegPCMAudio(track.stream_url, **FFMPEG_OPTIONS)
            vc.play(source, after=lambda e: self._play_next(ctx.guild.id))  # type: ignore[union-attr]
            await ctx.send(f"Now playing: **{track.title}** [{track.duration}]")
            await self._record_track(ctx.guild.id, track, query)  # type: ignore[union-attr]

        logger.info("[#%s] %s queued: %s", ctx.channel, ctx.author, track.title)

    @commands.command(name="mix")  # type: ignore[arg-type]
    async def mix(self, ctx: commands.Context[commands.Bot], *, query: str) -> None:
        """Start a continuous mix based on a search query. Usage: !mix persian music"""
        if ctx.author.voice is None or ctx.author.voice.channel is None:  # type: ignore[union-attr]
            await ctx.send("You need to be in a voice channel.")
            return

        voice_channel = ctx.author.voice.channel  # type: ignore[union-attr]

        if ctx.voice_client is None:
            vc = await voice_channel.connect()
        elif ctx.voice_client.channel != voice_channel:
            await ctx.voice_client.move_to(voice_channel)
            vc = ctx.voice_client
        else:
            vc = ctx.voice_client

        assert isinstance(vc, discord.VoiceClient)
        guild_id = ctx.guild.id  # type: ignore[union-attr]
        queue = self._get_queue(guild_id)

        # Enable mix mode
        queue.mix_query = query
        queue.mix_count = 0
        queue.played_urls.clear()

        await ctx.send(f"Starting mix for **{query}**... Songs will keep playing automatically.")

        track = await self._search(query, guild_id=guild_id)
        if track is None:
            await ctx.send("Couldn't find anything for that query.")
            queue.mix_query = None
            return

        track.requested_by = ctx.author.display_name

        if vc.is_playing() or vc.is_paused():
            # Stop current playback and start mix
            vc.stop()

        queue.current = track
        source = discord.FFmpegPCMAudio(track.stream_url, **FFMPEG_OPTIONS)
        vc.play(source, after=lambda e: self._play_next(guild_id))
        await ctx.send(f"Now playing: **{track.title}** [{track.duration}]")
        await self._record_track(guild_id, track, query)
        logger.info("[#%s] %s started mix: %s", ctx.channel, ctx.author, query)

    @commands.command(name="skip", aliases=["s"])  # type: ignore[arg-type]
    async def skip(self, ctx: commands.Context[commands.Bot]) -> None:
        """Skip the current track."""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send("Skipped.")
        else:
            await ctx.send("Nothing is playing.")

    @commands.command(name="queue", aliases=["q"])  # type: ignore[arg-type]
    async def queue(self, ctx: commands.Context[commands.Bot]) -> None:
        """Show the current queue."""
        if ctx.guild is None:
            return

        gq = self._get_queue(ctx.guild.id)
        lines: list[str] = []

        if gq.current:
            lines.append(f"**Now playing:** {gq.current.title} [{gq.current.duration}]")
        else:
            lines.append("Nothing is playing.")

        if gq.tracks:
            lines.append("\n**Up next:**")
            for i, track in enumerate(gq.tracks[:10], 1):
                lines.append(f"**{i}.** {track.title} [{track.duration}] — requested by {track.requested_by}")
            if len(gq.tracks) > 10:
                lines.append(f"...and {len(gq.tracks) - 10} more")
        elif gq.current:
            lines.append("Queue is empty.")

        await ctx.send("\n".join(lines))

    @commands.command(name="nowplaying", aliases=["np"])  # type: ignore[arg-type]
    async def nowplaying(self, ctx: commands.Context[commands.Bot]) -> None:
        """Show the currently playing track."""
        if ctx.guild is None:
            return

        gq = self._get_queue(ctx.guild.id)
        if gq.current:
            await ctx.send(
                f"Now playing: **{gq.current.title}** [{gq.current.duration}] "
                f"— requested by {gq.current.requested_by}"
            )
        else:
            await ctx.send("Nothing is playing.")

    @commands.command(name="pause")  # type: ignore[arg-type]
    async def pause(self, ctx: commands.Context[commands.Bot]) -> None:
        """Pause playback."""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("Paused.")
        else:
            await ctx.send("Nothing is playing.")

    @commands.command(name="resume")  # type: ignore[arg-type]
    async def resume(self, ctx: commands.Context[commands.Bot]) -> None:
        """Resume playback."""
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("Resumed.")
        else:
            await ctx.send("Nothing to resume.")

    @commands.command(name="stop")  # type: ignore[arg-type]
    async def stop(self, ctx: commands.Context[commands.Bot]) -> None:
        """Stop playback and clear the queue."""
        if ctx.guild is None:
            return

        gq = self._get_queue(ctx.guild.id)
        gq.tracks.clear()
        gq.current = None
        gq.loop = False
        gq.mix_query = None
        gq.mix_count = 0
        gq.played_urls.clear()

        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
        await ctx.send("Stopped and cleared the queue.")

    @commands.command(name="leave", aliases=["dc", "disconnect"])  # type: ignore[arg-type]
    async def leave(self, ctx: commands.Context[commands.Bot]) -> None:
        """Disconnect from the voice channel."""
        if ctx.guild is None:
            return

        if ctx.voice_client:
            gq = self._get_queue(ctx.guild.id)
            gq.tracks.clear()
            gq.current = None
            gq.loop = False
            gq.mix_query = None
            gq.mix_count = 0
            gq.played_urls.clear()
            await ctx.voice_client.disconnect()
            await ctx.send("Disconnected.")
        else:
            await ctx.send("I'm not in a voice channel.")

    @commands.command(name="loop")  # type: ignore[arg-type]
    async def loop(self, ctx: commands.Context[commands.Bot]) -> None:
        """Toggle looping the current track."""
        if ctx.guild is None:
            return

        gq = self._get_queue(ctx.guild.id)
        gq.loop = not gq.loop
        status = "on" if gq.loop else "off"
        await ctx.send(f"Loop is now **{status}**.")

    @commands.command(name="ban")  # type: ignore[arg-type]
    async def ban_track(self, ctx: commands.Context[commands.Bot]) -> None:
        """Ban the currently playing song — it will never play again."""
        if ctx.guild is None:
            return

        gq = self._get_queue(ctx.guild.id)
        if gq.current is None:
            await ctx.send("Nothing is playing right now.")
            return

        track = gq.current
        added = await self.db.ban_track(ctx.guild.id, track.url, track.title, ctx.author.id)
        if added:
            await ctx.send(f"Banned **{track.title}** — it will never play again. Skipping...\n`{track.url}`")
            logger.info("[#%s] %s banned track: %s [%s]", ctx.channel, ctx.author, track.title, track.url)
            # Auto-skip the banned song
            if ctx.voice_client and ctx.voice_client.is_playing():
                ctx.voice_client.stop()
        else:
            await ctx.send(f"**{track.title}** is already banned.\n`{track.url}`")

    @commands.command(name="unban")  # type: ignore[arg-type]
    async def unban_track(self, ctx: commands.Context[commands.Bot], *, query: str) -> None:
        """Unban a song by title or URL. Usage: !unban persian spring OR !unban <url>"""
        if ctx.guild is None:
            return

        banned = await self.db.list_banned_tracks(ctx.guild.id)
        if not banned:
            await ctx.send("No banned tracks.")
            return

        # Check if it's a URL match first
        for track_title, track_url in banned:
            if query.strip() == track_url:
                await self.db.unban_track(ctx.guild.id, track_url)
                await ctx.send(f"Unbanned **{track_title}**.\n`{track_url}`")
                logger.info("[#%s] %s unbanned track: %s [%s]", ctx.channel, ctx.author, track_title, track_url)
                return

        # Fall back to partial title match
        search = query.lower()
        for track_title, track_url in banned:
            if search in track_title.lower():
                await self.db.unban_track(ctx.guild.id, track_url)
                await ctx.send(f"Unbanned **{track_title}**.\n`{track_url}`")
                logger.info("[#%s] %s unbanned track: %s [%s]", ctx.channel, ctx.author, track_title, track_url)
                return

        await ctx.send(f"No banned track matching **{query}**. Use `!banned` to see the list.")

    @commands.command(name="banned")  # type: ignore[arg-type]
    async def banned_list(self, ctx: commands.Context[commands.Bot]) -> None:
        """Show all banned songs."""
        if ctx.guild is None:
            return

        banned = await self.db.list_banned_tracks(ctx.guild.id)
        if not banned:
            await ctx.send("No banned tracks.")
            return

        lines = ["**Banned tracks:**\n"]
        for i, (title, url) in enumerate(banned, 1):
            lines.append(f"**{i}.** {title}\n   `{url}`")
        await ctx.send("\n".join(lines))


    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Resync audio when someone joins the bot's voice channel."""
        if member.bot:
            return

        # Only care about someone joining the bot's channel
        guild = member.guild
        vc = guild.voice_client
        if not isinstance(vc, discord.VoiceClient) or not vc.is_playing():
            return

        # Someone joined the channel the bot is in
        if after.channel and after.channel == vc.channel and before.channel != after.channel:
            vc.pause()
            await asyncio.sleep(0.5)
            vc.resume()
            logger.info("Audio resync: %s joined voice channel", member.display_name)


async def setup(bot: commands.Bot) -> None:
    db = bot.db  # type: ignore[attr-defined]
    await bot.add_cog(MusicCog(bot, db))
