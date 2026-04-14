# Firooz

A multi-feature Discord bot that runs locally on macOS. Built with Python, discord.py, and SQLite.

## Features

### Karma
- Give or take karma with `@user++` or `@user--`
- Group karma: `@user1 @user2++ for being awesome`
- Emoji reactions (thumbs up, laughing, etc.) award karma automatically
- Reaction removal reverses the karma
- Self-voting gets roasted with a random funny message
- Milestone celebrations at 5, 10, 25, 50, 100, 250, 500, and 1000 karma
- Karma updates post to a dedicated `#bot_zone` channel
- `!leaderboard` / `!lb` — top karma holders
- `!history` / `!h @user` — karma history for a user

### Music
- `!play` / `!p <query>` — play a song from YouTube
- `!mix <query>` — continuous auto-play radio based on a search query (max 50 songs)
- `!skip` / `!s` — skip current track
- `!queue` / `!q` — show the queue (max 50 tracks)
- `!nowplaying` / `!np` — show current track
- `!pause` / `!resume` — pause and resume playback
- `!loop` — toggle looping the current track
- `!stop` — stop playback and clear queue
- `!leave` / `!dc` — disconnect from voice
- `!ban` — ban the currently playing song forever
- `!unban <title or url>` — unban a song
- `!banned` — list all banned songs
- Smart duplicate avoidance: shuffled search results, 7-day play history tracking, and permanent ban list
- Auto audio resync when someone joins the voice channel

### Vibe Check
- `!vibe` / `!v` — sentiment analysis of recent channel messages using VADER
- Rates the channel energy from "toxic wasteland" to "off the charts wholesome"
- Configurable message count: `!vibe 100`

### Waifu
- `!waifu` / `!w <category>` — random SFW anime image (neko, hug, pat, smile, etc.)
- NSFW command available as a hidden feature in `#bot_test_zone` only

### Remember
- `!remember` / `!rem <key> <value>` — save a note
- `!rem <key>` (as a reply) — save the replied message under a key
- `!rem` (as a reply) — save with an auto-generated key
- Saves text, attachments (images/videos), and embed URLs (YouTube links, etc.)
- `!recall` / `!r <key>` — recall a saved note
- `!memories` / `!mems` — list all saved notes
- `!forget <key>` — delete a note

### Translate
- `!translate` / `!tr` (as a reply) — translate any message to English
- `!tr <text>` — translate inline text
- Replies directly to the original message
- Powered by Google Translate (via deep-translator)

### Health Monitoring
- Hourly health check logs: DB size, row counts, guild count, latency
- Warning at 1 GB, red alert at 5 GB
- `make db-stats` — manual database stats
- `make db-vacuum` — compact the database

### Rate Limiting
- 10 requests per 30 seconds per user
- Applies to both commands and karma actions

## Setup

```bash
# Clone the repo
git clone <repo-url> && cd firooz

# Create venv and install dependencies
make setup

# Configure the bot token (stored in SQLite, not .env)
make configure

# Run the bot
make run
```

### Prerequisites
- Python 3.11+
- FFmpeg (for music playback)
- A Discord bot token with Message Content, Server Members, and Reactions intents enabled

### Discord Bot Setup
1. Go to https://discord.com/developers/applications
2. Create a new application
3. Go to Bot settings, enable Message Content Intent and Server Members Intent
4. Copy the bot token and run `make configure`
5. Invite the bot: `https://discord.com/api/oauth2/authorize?client_id=YOUR_CLIENT_ID&permissions=68672&scope=bot`

## Commands

| Command | Alias | Description |
|---------|-------|-------------|
| `!leaderboard` | `!lb` | Top karma holders |
| `!history @user` | `!h` | Karma history |
| `!play <query>` | `!p` | Play a YouTube song |
| `!mix <query>` | | Continuous auto-play radio |
| `!skip` | `!s` | Skip current track |
| `!queue` | `!q` | Show queue |
| `!nowplaying` | `!np` | Current track |
| `!pause` | | Pause playback |
| `!resume` | | Resume playback |
| `!loop` | | Toggle loop |
| `!stop` | | Stop and clear queue |
| `!leave` | `!dc` | Disconnect from voice |
| `!ban` | | Ban current song |
| `!unban <query>` | | Unban a song |
| `!banned` | | List banned songs |
| `!vibe` | `!v` | Channel vibe check |
| `!waifu` | `!w` | Random anime image |
| `!remember <key> <value>` | `!rem` | Save a note |
| `!recall <key>` | `!r` | Recall a note |
| `!memories` | `!mems` | List all notes |
| `!forget <key>` | | Delete a note |
| `!translate` | `!tr` | Translate to English |
| `!commands` | `!help` | Show all commands |

## Development

```bash
# Run tests
make test

# Database stats
make db-stats

# Compact database
make db-vacuum

# Clean everything
make clean
```

## Tech Stack
- **discord.py** — Discord API wrapper
- **SQLAlchemy** (async) + **aiosqlite** — ORM and database
- **yt-dlp** + **FFmpeg** — YouTube audio streaming
- **VADER Sentiment** — channel vibe analysis
- **deep-translator** — Google Translate integration
- **aiohttp** — external API calls (waifu.pics)
