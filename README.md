# Apollo Scanner Bot

**Reverse-engineering Apollo event embeds and other event bot embeds to restore lost functionality for Discord communities.**

## Docs
- [Discord API](https://discord.com/developers/docs/reference)
- [Gateway API](https://discord.com/developers/docs/events/gateway)
- [Rich Presence, bot-embed extraction and usage](https://discord.com/developers/docs/rich-presence/overview)
- [Rate Limiting](https://discord.com/developers/docs/topics/permissions)

## Overview

- Apollo Scanner Bot is a modular and lightweight Discord bot designed to **scan Apollo event embeds** and return structured data such as attendance, declined responses, and reaction summaries.

This bot **IS NOT** a replacement for Apollo, rather an adaptable secondary "drone-bot" designed to be modular in order to support most event bots' paid tier like features, with some programming knowledge. The examples provided in source code are referencing the needs of a milsim gaming community, but it can be adapted for literally anything else. 

- This tool was created in response to Apollo’s shift to paid features that limit accessibility for small communities. Rather than replicating Apollo, this bot **reads and summarizes Apollo’s embeds**, acting as a diagnostic tool to **reverse engineer Apollo’s behavior** for further automation or analytics.

## Features

* `/scan_apollo` - Parse the latest Apollo embeds and summarize all attendee/decline reactions.
* `/leaderboard` - Display attendance over the last N number of events.
* `/show_apollo_embeds` - Print raw embed data from Apollo events (for debugging).
* `/recent_authors` - List bots/authors that posted embeds recently (to ensure Apollo is the source).
* `/hilf` - Help command.
* Works with **any** Apollo or event-bot-like embed, no internal API needed.
* Modular: Add new post-processing commands without changing the scanning core.

---

### NOTE:- [Rate Limiting](https://discord.com/developers/docs/topics/permissions) is **not implemented for the Discord API**, because for most uses it should be sufficient to summarize data say, once a month or every week even. But just know that if you need it, **you will have to implement rate limiting** if your needs are at the larger end.

## Project Structure

```
📁 discord-bot/
├──bots
|    ├── attbot.py              # Deployment-ready bot (no CSV logging, memory only)
|    ├── botscanner.py          # Local version with persistent CSV logging
├── requirements.txt       # Python dependencies
├── .env                   # (ignored)
├── README.md              # This thing!
```

There are **two versions** of the bot:

* `attbot.py`: Temporary memory storage, no filesystem writing, ready for deployment (includes `.exe` and Docker support).
* `botscanner.py`: Local version that uses `CSV` to persist data across runs for richer logging and analysis.

---

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/yourusername/bot-scanner.git
cd bot-scanner
```

### 2. Install dependencies

Ensure you have Python 3.10+ and a virtual environment:

```bash
pip install -r requirements.txt
```

### 3. Set up `.env` (or provide input manually)

Create a `.env` file with:

```env
TOKEN = your_discord_bot_token
CHANNEL_ID = 123456789012345678
GUILD_ID = 987654321098765432
```

If you omit any of these, the bot will prompt you to enter them manually at runtime.

---

## Deployment Options

### Prebuilt Executables

You’ll find `.exe` files for both `attbot.py` and `botscanner.py` (under Releases, currently in Alpha, might not be super stable). No setup needed, just double-click and run.

### Docker

A containerized version of `attbot.py` is available for local or server deployment:

```bash
docker build -t apollo-bot .
docker run -e TOKEN=... -e CHANNEL_ID=... -e GUILD_ID=... apollo-bot
```

---

## Modularity & Extension

The bot was designed to be **modular and composable**:

1. Run `/scan_apollo` once to store recent Apollo data in memory.
2. Run any command (`/leaderboard`, `/show_declines`, etc.) afterward to process that data.
3. You can add new commands to work on the scanned data with no changes to the scanning logic.

---

## Why This Bot?

Apollo no longer provides detailed response exports on its free tier. This bot restores that power to users by **targeting Apollo's public embed messages** and extracting structured data from them.

This bot does not violate Discord ToS or Apollo’s terms, since it only reads publicly available content already visible to users.

---

## Contributing

Pull requests and feature suggestions are welcome! This project is open source under the MIT License. You can:

* Add new analytics commands
* Improve normalization or deduplication logic
* Help support new event types or embed formats

---

## License

MIT © 2025

---


