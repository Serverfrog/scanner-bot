"""
This is a unique discord bot that using the closed source event and server management bots using the Discord API, essentially forming a
    closed ecosystem extraction. It scans the activity of other bots in the server by creating a websocket with the hosts, using Discord's Gateway API.
"""
import logging
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict, Callable
from typing import List, Tuple, Dict, Optional

import discord
import yaml
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from pythonjsonlogger.json import JsonFormatter


def setup_logger(name='attbot', log_level=logging.INFO):
    """
    Configure logger with JSON formatting for stdout

    Args:
        name (str): Logger name
        log_level (int): Logging level (default: logging.INFO)

    Returns:
        logging.Logger: Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()

    # Create stdout handler
    stdout_handler = logging.StreamHandler(sys.stdout)

    # Create a custom JSON formatter
    class CustomJsonFormatter(JsonFormatter):
        def add_fields(self, log_record, record, message_dict):
            super(CustomJsonFormatter, self).add_fields(log_record, record, message_dict)
            # Add timestamp in ISO format
            log_record['timestamp'] = datetime.now().isoformat()
            log_record['level'] = record.levelname
            log_record['logger'] = record.name

    # Configure formatter
    formatter = CustomJsonFormatter(
        '%(timestamp)s %(level)s %(name)s %(message)s'
    )

    stdout_handler.setFormatter(formatter)
    logger.addHandler(stdout_handler)

    return logger

LOG = setup_logger('attbot')

class BotConfig:
    def __init__(self):
        self.TOKEN = None
        self.CHANNEL_ID = None
        self.GUILD_ID = None
        # Database configuration
        self.DB_HOST = None
        self.DB_PORT = None
        self.DB_USER = None
        self.DB_PASSWORD = None
        self.DB_DATABASE = None
        # AttBot configuration
        self.TEMPLATE_PATH = None

    @staticmethod
    def load_config(config_path: str) -> Optional[Dict[str, Any]]:
        """
        Load configuration from a YAML file.

        Args:
            config_path: Path to the YAML configuration file

        Returns:
            Dictionary containing the configuration or None if loading fails

        Example YAML file:
            bot:
              token: your_discord_bot_token
              channel_id: 123456789012345678
              guild_id: 987654321098765432
            database:
              host: localhost
              port: 5432
              user: your_username
              password: your_password
              database: your_database_name
            attbot:
              template: ./staff_meeting_note.md
        """
        path = Path(config_path)

        if not path.exists():
            LOG.error("Config file not found", extra={"config_path": config_path})
            sys.exit(1)

        try:
            with path.open('r', encoding='utf-8') as file:
                config = yaml.safe_load(file)

            if not isinstance(config, dict):
                LOG.error("Invalid YAML structure: root element must be a mapping")
                sys.exit(1)

            return config

        except yaml.YAMLError as e:
            LOG.error(f"Error parsing YAML file: {e}", extra={"config_path": config_path})
            sys.exit(1)
        except Exception as e:
            LOG.error(f"Unexpected error loading config: {e}", extra={"config_path": config_path})
            sys.exit(1)

    @staticmethod
    def get_env_or_config(env_key: str, config: dict, config_path: str, transform: Optional[Callable] = None) -> Any:
        """
        Get value from an environment variable or fallback to a nested config a file.

        Args:
            env_key: Environment variable name
            config: Configuration dictionary
            config_path: Dot-separated path in config dictionary (e.g. 'bot.token')
            transform: Optional function to transform the value
        """
        value = os.getenv(env_key)

        if value is None:
            # Navigate nested dictionary using the path
            current = config
            for key in config_path.split('.'):
                if not isinstance(current, dict):
                    return None
                current = current.get(key)
                if current is None:
                    return None
            value = current

        if value is not None and transform is not None:
            try:
                value = transform(value)
            except (ValueError, TypeError) as e:
                LOG.error(f"Error transforming value for {env_key}: {e}", extra={"config_path": config_path})
                return None

        return value

    @staticmethod
    def is_valid_snowflake(s):
        """
        Check if the given string is a valid Discord snowflake.

        A Discord snowflake must consist of 17 to 20 digits.

        Args:
            s (str): The string to be checked.

        Returns:
            bool: True if the string is valid as a Discord snowflake,
            otherwise False.
        """

        return bool(re.fullmatch(r"\d{17,20}", s))

    def initialize(self):
        """Initialize and validate bot configuration."""
        load_dotenv()
        config = self.load_config('config.yaml')

        if config is None:
            config = {}  # Provide fallback empty dict


        # Get bot values with fallback
        self.TOKEN = self.get_env_or_config("TOKEN", config, "bot.token", str)
        self.CHANNEL_ID = self.get_env_or_config("CHANNEL_ID", config, "bot.channel_id", int)
        self.GUILD_ID = self.get_env_or_config("GUILD_ID", config, "bot.guild_id", str)

        # Get database values with fallback
        self.DB_HOST = self.get_env_or_config("DB_HOST", config, "database.host", str)
        self.DB_PORT = self.get_env_or_config("DB_PORT", config, "database.port", int)
        self.DB_USER = self.get_env_or_config("DB_USER", config, "database.user", str)
        self.DB_PASSWORD = self.get_env_or_config("DB_PASSWORD", config, "database.password", str)
        self.DB_DATABASE = self.get_env_or_config("DB_DATABASE", config, "database.database", str)

        # Get attbot values with fallback
        self.TEMPLATE_PATH = self.get_env_or_config("TEMPLATE_PATH", config, "attbot.template", str)

        if not self.TOKEN:
            LOG.error("Missing TOKEN value in config file.", extra={"bot.token": self.TOKEN})
            sys.exit(1)

        if not self.CHANNEL_ID or not self.is_valid_snowflake(str(self.CHANNEL_ID)):
            LOG.error("Missing or invalid CHANNEL_ID value in config file.", extra={"bot.channel_id": self.CHANNEL_ID})
            sys.exit(1)

        if not self.GUILD_ID or not self.is_valid_snowflake(self.GUILD_ID):
            LOG.error("Missing or invalid GUILD_ID value in config file.", extra={"bot.guild_id": self.GUILD_ID})
            sys.exit(1)


@dataclass
class AttendanceEntry:
    """
    Class representing an attendance log entry.

    Attributes:
        user_id (str): The normalized user ID
        username (str): The pretty/display name of the user
        event_id (int): The ID of the event
        response (str): The response type ("accepted" or "declined")
        timestamp (str): ISO format timestamp of when entry was created
    """
    user_id: str
    username: str
    event_id: int
    response: str = "accepted"
    timestamp: str = None

    def __post_init__(self):
        """Set a timestamp if not provided during initialization"""
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()

    @property
    def pseudo_id(self) -> str:
        """Generate the pseudo_id used for tracking unique entries"""
        if self.response == "accepted":
            return f"{self.event_id}-{self.user_id}"
        return f"{self.event_id}-{self.user_id}-declined"

    def to_dict(self) -> dict:
        """Convert entry to dictionary format for storage"""
        return {
            "timestamp": self.timestamp,
            "user_id": self.user_id,
            "username": self.username,
            "event_id": self.event_id,
            "response": self.response
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'AttendanceEntry':
        """Create an AttendanceEntry instance from a dictionary"""
        return cls(
            user_id=data["user_id"],
            username=data["username"],
            event_id=data["event_id"],
            response=data["response"],
            timestamp=data["timestamp"]
        )



class AttendanceLog:
    """
    Class managing a collection of attendance entries.
    Provides methods for adding, querying, and analyzing attendance data.
    """

    def __init__(self):
        self._entries: TypedDict[str, AttendanceEntry] = {}

    def already_logged(self, pseudo_id: str) -> bool:
        """Check if an entry with the given pseudo_id exists"""
        return pseudo_id in self._entries

    def add_entry(self, entry: AttendanceEntry) -> bool:
        """
        Add a new attendance entry if it doesn't exist.
        Returns True if an entry was added, False if it already existed.
        """
        if not self.already_logged(entry.pseudo_id):
            self._entries[entry.pseudo_id] = entry
            return True
        return False

    def log_attendance(self, user_id: str, username: str, event_id: int, response: str = "accepted") -> bool:
        """Create and add a new attendance entry"""
        entry = AttendanceEntry(
            user_id=user_id,
            username=username.strip(),
            event_id=event_id,
            response=response
        )
        return self.add_entry(entry)

    def get_entry(self, pseudo_id: str) -> Optional[AttendanceEntry]:
        """Retrieve an entry by its pseudo_id"""
        return self._entries.get(pseudo_id)

    def get_user_entries(self, user_id: str) -> List[AttendanceEntry]:
        """Get all entries for a specific user"""
        return [entry for entry in self._entries.values() if entry.user_id == user_id]

    def get_event_entries(self, event_id: int) -> List[AttendanceEntry]:
        """Get all entries for a specific event"""
        return [entry for entry in self._entries.values() if entry.event_id == event_id]

    def get_attendance_summary(self) -> Dict[str, Dict[str, int]]:
        """Get a summary of accepted/declined counts per user"""
        summary = defaultdict(lambda: {"accepted": 0, "declined": 0})
        for entry in self._entries.values():
            summary[entry.username][entry.response] += 1
        return dict(summary)

    def clear(self):
        """Clear all entries"""
        self._entries.clear()

    def get_all_entries(self) -> Dict[str, AttendanceEntry]:
        """Get all entries"""
        return self._entries.values()

    @property
    def total_entries(self) -> int:
        """Get a total number of entries"""
        return len(self._entries)

    @property
    def unique_users(self) -> set:
        """Get a set of unique usernames"""
        return {entry.username for entry in self._entries.values()}

    def to_dict(self) -> Dict[str, dict]:
        """Convert all entries to a dictionary format"""
        return {pseudo_id: entry.to_dict() for pseudo_id, entry in self._entries.items()}

    @classmethod
    def from_dict(cls, data: Dict[str, dict]) -> 'AttendanceLog':
        """Create an AttendanceLog instance from a dictionary"""
        log = cls()
        for pseudo_id, entry_data in data.items():
            entry = AttendanceEntry.from_dict(entry_data)
            log._entries[pseudo_id] = entry
        return log


@dataclass
class EventEntry:
    """
    Class representing a single event entry.

    Attributes:
        event_id: Unique identifier for the event
        accepted: List of tuples containing (normalized_name, display_name) for accepted users
        declined: List of tuples containing (normalized_name, display_name) for declined users
        timestamp: When the event was logged
    """
    event_id: int
    accepted: List[Tuple[str, str]]
    declined: List[Tuple[str, str]]
    timestamp: str = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> dict:
        """Convert entry to dictionary format"""
        return {
            "event_id": self.event_id,
            "accepted": self.accepted,
            "declined": self.declined,
            "timestamp": self.timestamp
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'EventEntry':
        """Create an EventEntry from dictionary data"""
        return cls(**data)


class EventLog:
    """
    Class managing a collection of event entries.
    Maintains the most recent events and provides analysis methods.
    """

    def __init__(self, max_events: int = 8):
        self._events: List[EventEntry] = []
        self.max_events = max_events

    def add_event(self, event: EventEntry) -> None:
        """Add a new event, maintaining the maximum size limit"""
        self._events.append(event)
        if len(self._events) > self.max_events:
            self._events.pop(0)

    def clear(self) -> None:
        """Clear all events"""
        self._events.clear()

    @property
    def recent_events(self) -> List[EventEntry]:
        """Get a list of recent events"""
        return self._events.copy()

    @property
    def total_events(self) -> int:
        """Get a total number of events stored"""
        return len(self._events)

    def get_event(self, event_id: int) -> Optional[EventEntry]:
        """Get event by ID"""
        for event in self._events:
            if event.event_id == event_id:
                return event
        return None

    def get_user_participation(self, normalized_name: str) -> Dict[str, int]:
        """Get participation summary for a user"""
        summary = {"accepted": 0, "declined": 0}
        for event in self._events:
            if any(norm == normalized_name for norm, _ in event.accepted):
                summary["accepted"] += 1
            if any(norm == normalized_name for norm, _ in event.declined):
                summary["declined"] += 1
        return summary

    def get_all_participants(self) -> Dict[str, Dict[str, int]]:
        """Get a participation summary for all users"""
        summary = {}
        for event in self._events:
            for norm_name, display_name in event.accepted:
                if norm_name not in summary:
                    summary[norm_name] = {"display_name": display_name, "accepted": 0, "declined": 0}
                summary[norm_name]["accepted"] += 1

            for norm_name, display_name in event.declined:
                if norm_name not in summary:
                    summary[norm_name] = {"display_name": display_name, "accepted": 0, "declined": 0}
                summary[norm_name]["declined"] += 1
        return summary

    def to_dict(self) -> List[dict]:
        """Convert all events to a dictionary format"""
        return [event.to_dict() for event in self._events]

    @classmethod
    def from_dict(cls, data: List[dict]) -> 'EventLog':
        """Create an EventLog instance from dictionary data"""
        log = cls()
        for event_data in data:
            log.add_event(EventEntry.from_dict(event_data))
        return log

# Create a global config instance
bot_config = BotConfig()

# Initialize the discord intent object and set most of the necessary parameters from the docs of "discord" to True
intents = discord.Intents.default()

# Required for commands and reading messages
intents.message_content = True

# required for reactions, member ids/names and the guild/clan itself
intents.reactions = True
intents.members = True
intents.guilds = True

# needed to receive message + reaction payloads
intents.messages = True

# get the bot commands in a variable with the usual / standard prefix
bot = commands.Bot(command_prefix="/", intents=intents)

# In-memory log: pseudo_id -> log entry
attendance_log = AttendanceLog()

# Holds data for the most recent 8 Apollo events
event_log = EventLog()  # Populate this in the /scan_apollo command

def normalize_name(name: str) -> str:
    """ Using regex, we normalize scanned names to pass into other functions. """
    name = name.lower()
    name = re.sub(r"[^\w\s]", "", name)  # remove punctuation
    name = re.sub(r"\s+", " ", name)     # normalize whitespace
    return name.strip()


async def defer_response(interaction: discord.Interaction, *, thinking: bool = True) -> None:
    """
    Utility method to handle response deferral with proper typing.

    Args:
        interaction: The Discord interaction to defer
        thinking: Whether to show the "thinking" state (default: True)
    """
    await interaction.response.defer(thinking=thinking) # type: ignore[attr-defined]


async def send_response(interaction: discord.Interaction, content: str, *, ephemeral: bool = False) -> None:
    """
    Utility method to handle response sending with proper typing.

    Args:
        interaction: The Discord interaction to respond to
        content: The content to send
        ephemeral: Whether the message should be ephemeral (default: False)
    """
    if interaction.response.is_done(): # type: ignore[attr-defined]
        await interaction.followup.send(content, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(content, ephemeral=ephemeral)# type: ignore[attr-defined]

@bot.event
async def on_ready():
    """
    Handles the on_ready event to confirm the bot's connection and synchronization status.

    This event triggers when the bot is connected to Discord and ready to interact with the API. It prints
    the bot's username to indicate a successful connection and attempts to synchronize application commands
    with Discord. Any errors occurring during synchronization are logged.

    Args:


    Raises:
        Exception: If an error related to syncing commands occurs.

    Returns:
        None
    """

    LOG.info("Bot connected successfully", extra={
        "bot_user": str(bot.user),
        "guild-name": bot.guilds,
    })
    LOG.info("Bot is running on version %s" % discord.__version__)
    try:
        synced = await bot.tree.sync()
        LOG.info(f"Synced commands: {synced}")
    except Exception as e:
        LOG.error(f"Error occurred during syncing commands: {e}")

"""
--- NOTE --- 
This chunk of comments was for the async payload function, doesnt work for Apollo embeds but DOES if we want to use similar functionality in the future
for normal emoji reactions to messages and log them
-----------------------------------------------------------------------------------------------------------------------------------------------------

# Make an async function for the raw reaction transfer with its payload
    # we need to consider that we have to add the payload for every reaction, and the data we need for that is:
        # 1- the reaction emoji
        # 2- the channel id
        # 3- bot id and member/user id must match

@bot.event
async def on_raw_reaction_add(payload):
    print(f"Detected reaction: '{payload.emoji.name}'")

    if payload.emoji.name != REACTION_EMOJI:
        return
    if payload.channel_id != CHANNEL_ID:
        return
    if payload.user_id == bot.user.id:
        return

    # store the member and "guild" with their corresponding data in simpler vars then:
    guild = bot.get_guild(payload.guild_id)
    member = guild.get_member(payload.user_id)

    # if the member is valid, log their attendance with needed params and print what they attended
    if member:
        log_attendance(member.id, member.name, payload.message_id)
        print(f"{member.name} attended event {payload.message_id}")
-----------------------------------------------------------------------------------------------------------------------------------------------------
"""

# TODO: Set up a command like /post_summary to auto-post attendance summaries at the end of the month in a formatted embed.
# TODO: Host the bot on a server so its always up
# TODO: Improve /leaderboard by including the event name (if found in embed.title or embed.description) not applicable for our clan (events not named)

# debug attendance log
@bot.command()
async def dump_attendance(ctx):
    await ctx.send(f"Current entries: {attendance_log.total_entries}")


# This will print embed descriptions so we can see exactly what text is there (for reverse engineering websocket requests of other bots)
@bot.tree.command(name="show_apollo_embeds", description="Show Apollo embed descriptions.")
@app_commands.describe(limit="Number of messages to scan (default 50)")
async def show_apollo_embeds(interaction: discord.Interaction, limit: int = 50):

    found = 0
    limit = min(limit, 200)

    async for msg in interaction.channel.history(limit=limit):
        if "Apollo" in msg.author.name:
            found += 1
            for embed in msg.embeds:
                await interaction.channel.send(f"Embed description:\n```{embed.description}```")

    if found == 0:
        await send_response(interaction,f"No Apollo messages found in last {limit} messages.")
    else:
        await send_response(interaction,f"Found {found} Apollo messages.", ephemeral=True)


# let's list recent messages and their authors
@bot.tree.command(name="recent_authors", description="Show recent authors from the channel.")
@app_commands.describe(limit="Number of messages to scan (default 20)")
async def recent_authors(interaction: discord.Interaction, limit: int = 20):

    authors = set()
    limit = min(limit, 200)

    async for msg in interaction.channel.history(limit=limit):
        authors.add(msg.author.name)

    result = ", ".join(authors)
    await send_response(interaction,
        f"Recent authors from last {limit} messages:\n{result}"
    )


# TODO: Make a /help_awards_bot command
@bot.tree.command(name="hilf", description="Show all available commands and their usage.")
async def hilf(interaction: discord.Interaction):

    await defer_response(interaction)  # defer in case it takes a moment

    help_text = """
        **Attendance Bot Commands:**

        `/scan_apollo` -> Scans recent Apollo messages and logs users who reacted with ✅ or :accepted: and who reacted with ❌ or :declined:.

        `/leaderboard` -> Shows this month's attendance leaderboard, based on unique events attended.

        `/show_apollo_embeds` -> Prints the descriptions of recent Apollo embeds for "debugging". This is the actual command that exposes the embeds and
                                other formats of the Apollo bot to "reverse engineer" whatever the bot embeds in order to make your own version thereof.

        `/recent_authors` -> Lists authors of the last 'n' messages in the channel. Mainly used for debugging or simply finding out who has made messages.
                            This command is used to figure out if it was apollo bot, or another bot/author that made the message/post.

        `/scan_all_reactions` -> Mainly used for analysing the reactions to messages, includes all reaction types and which member reacted with what.

        `/debug_duplicates` -> If you get duplicate reactions, you check how many and which of those were duplicate and why, since this will be a common
                                issue, especially for escape sequences and non standard usernames.

        `/dump_attendance` -> Debugs all current entries. If the `/scan_apollo` command isn't used before had it will always return 0 as the procedure is
                                sequential to save memory and improve performance.

        `/staff_meeting_notes` -> Paste staff meeting notes markdown text template.

        > This bot tracks Apollo event reactions to summarize user participation. More commands to be added.
        """
    await interaction.followup.send(help_text)


@bot.tree.command(name="staff_meeting_notes", description="Paste staff meeting note template.")
async def staff_meeting_notes(interaction: discord.Interaction):

    await defer_response(interaction)  # defer in case it takes a moment

    try:
        with open(bot_config.TEMPLATE_PATH, 'r', encoding='utf-8') as file:
            notes_text = file.read()

        if not notes_text.strip():
            await interaction.followup.send("Error: Template file is empty!")
            return

        await interaction.followup.send(notes_text)

    except FileNotFoundError:
        await interaction.followup.send(f"Error: Template file '{bot_config.TEMPLATE_PATH}' not found!")
    except PermissionError:
        await interaction.followup.send("Error: No permission to read the template file!")
    except UnicodeDecodeError:
        await interaction.followup.send("Error: Unable to read template file - encoding issue!")
    except Exception as e:
        await interaction.followup.send(f"Error: An unexpected error occurred: {str(e)}")

@bot.tree.command(name="debug_apollo", description="Scan recent messages for Apollo embeds and show raw fields for debugging.")
@app_commands.describe(limit="How many recent messages to scan (default 50)")
async def debug_apollo(interaction: discord.Interaction, limit: int = 50):


    await defer_response(interaction)
    found = False
    messages = []

    async for msg in interaction.channel.history(limit=limit):

        if "apollo" in msg.author.name.lower():
            found = True

            if not msg.embeds:
                messages.append("Apollo message found, but has no embeds.")
                continue

            for embed in msg.embeds:
                title = embed.title or "No Title"
                description = embed.description or "No Description"
                messages.append(f"**Embed Title:** {title}\n```{description}```")

                for field in embed.fields:
                    name = field.name or "Unnamed Field"
                    value = field.value or "No Value"
                    chunk = f"**{name}**:\n```{value}```"
                    messages.append(chunk)

    if not found:
        await interaction.followup.send("No Apollo messages found in recent history.")
        return

    if not messages:
        await interaction.followup.send("Apollo messages found, but no embeds to show.")
        return

    # Send messages in chunks under 1900 characters
    chunk = ""
    for msg in messages:
        if len(chunk) + len(msg) > 1900:
            await interaction.followup.send(chunk)
            chunk = ""
        chunk += msg + "\n\n"

    if chunk:
        await interaction.followup.send(chunk)


@bot.tree.command(name="debug_duplicates", description="Check for inconsistent (duplicate-looking) usernames in attendance log.")
async def debug_duplicates(interaction: discord.Interaction):
    from collections import defaultdict

    seen = defaultdict(set)

    # Normalize usernames and group them
    for entry in attendance_log.get_all_entries():
        normalized = normalize_name(entry.username)
        seen[normalized].add(entry.username)

    duplicates = {k: v for k, v in seen.items() if len(v) > 1}

    # Defer in case it takes time
    await defer_response(interaction)

    if not duplicates:
        await interaction.followup.send("No username inconsistencies found.")
    else:
        lines = ["Inconsistent usernames found:"]
        for k, versions in duplicates.items():
            lines.append(f"{k}: {', '.join(versions)}")
        
        message = "\n".join(lines)
        if len(message) > 1900:
            for chunk in [message[i:i+1900] for i in range(0, len(message), 1900)]:
                await interaction.followup.send(chunk)
        else:
            await interaction.followup.send(message)


# command to gather Apollo data, cause its fucking CLOSED SOURCE!!
@bot.tree.command(name="scan_apollo", description="Scan Apollo event embeds and log attendance.")
@app_commands.describe(limit="Number of messages to scan (default 18, max 100)")
async def scan_apollo(interaction: discord.Interaction, limit: int = 18):

    # initialize scanned and logged as 0
    scanned = 0
    logged = 0

    # limit the apollo scans to a max of 100
    limit = min(limit, 100)

    # Ensure CHANNEL_ID is int or convert
    # also, if you don't want to hard-code the channel id and instead want to type the channel id as an argument to the command, you can do so
    target_channel = bot.get_channel(int(bot_config.CHANNEL_ID))
    if not target_channel:
        await send_response(interaction,"Failed to fetch the announcements channel.")
        return

    # the thinking is "the bot is thinking", which is set to true
    await defer_response(interaction, thinking=True)

    # NOTE -> here on, we will be focusing on scanning the actual apollo messages

    # for every message in the target channel, with the current limit of how many prior messages to scan, we will check if it's a message by apollo first
    async for msg in target_channel.history(limit=limit):
        if "Apollo" not in msg.author.name:
            continue
        
        # if it is an apollo, increment scanned messages count by 1
        scanned += 1

        # ---- NOTE ----
        # the way Apollo does its ✅, ❌ for example, is not the actual emoji, that would be :white_check_mark: and :x: . Rather, apollo has its own
        # server side embeds which it displays as those emojis in its default functionality, for attendance of the event as:
        # :accepted: :declined:

        # NOTE: The "embed" object here refers to an instance of discord.Embed, which is a class provided by the discord.py library representing
        # a rich content "embed" attached to a Discord message. 
        # Discord allows bots and users to send rich messages containing fields, colors, thumbnails, and descriptions

        """ 
        A typical Apollo embed could be like:
                embed.title: "Training Operation - June 17"

                embed.description: "- Cpl C. Hart\n- Pvt M. Doe"

                embed.fields:

                Field 1: Name = "Accepted ✅", Value = "- PFC Jane\n- LCpl Bob"

                Field 2: Name = "Declined ❌", Value = "- Pvt Ray" 
        """

        # then for each embed in the message embeds, set a list of what embed we want to keep track of i.e.: here we keep track of attendees and declined,
        # but that goes for literally anything else, using any other of apollo's function, that's why the "/show_apollo_embeds" function exists,
        # So we are looping through all embed objects attached to a single message 'msg'
        for embed in msg.embeds:
            attendees = []
            declined = []

            # then for each field in the embeds' fields, check for both accepted and declined
            # embed.fields is a list of named fields in that embed (e.g., "Accepted", "Declined").
            for field in embed.fields:

                # strip them of their standard apollo format and append the plain names to the attendees dict, do the same for declined
                # parse the .value of each field to extract usernames by "normalizing" them
                if "accepted" in field.name.lower():
                    for line in field.value.split("\n"):
                        name = line.strip("- ").strip()
                        if name:
                            attendees.append(name)

                if "declined" in field.name.lower() or "x" in field.name.lower():
                    for line in field.value.split("\n"):
                        name = line.strip("- ").strip()
                        if name:
                            declined.append(name)

            # the embed object description is how the bot parses each description for each line in the description of event but remember:
            # this condition is outside the field loop, but inside the main msg embed loop, so the description embed here is for this specific use case,
            # showing the attendees
            if embed.description:
                for line in embed.description.split("\n"):
                    if line.strip().startswith("-"):
                        name = line.strip("- ").strip()
                        if name:
                            attendees.append(name)

            # debug loop for seeing the exact inner workings of the bot embeds in JSON like format
            for debugEmbed in msg.embeds:
                logging.info(f"Embed: {debugEmbed}")

            # we then want to get tuples of the names in each of the 2 lists we have so far, and call the normalized_name function on it,
            # to well... normalize them using list iteration
            normalized_declined = [(normalize_name(name), name) for name in declined]
            normalized_attendees = [(normalize_name(name), name) for name in attendees]

            # append the MAIN list, at global level which is keeping track of mapping the attributes to the id's like we see below
            event = EventEntry(
                event_id=msg.id,
                accepted=normalized_attendees,
                declined=normalized_declined
            )
            event_log.add_event(event)

            # now im "pretty printing" it, so I don't want to see ".username_x" but their actual server name like in a milsim server (Pvt M. Cooper)
            # for every user_id and pretty name in each of the lists i.e., "attendees" and "declined", we first want to check if they are already logged
            # by calling the "already_logged" function with the "pseudo_id" to prevent duplicates, and if that's not the case, we append logged by 1
            for user_id, pretty in normalized_attendees:
                pseudo_id = f"{msg.id}-{user_id}"
                if not attendance_log.already_logged(pseudo_id):
                    attendance_log.log_attendance(user_id, pretty, msg.id)
                    logged += 1

            # fore declined we do the same, but we pass the response parameter and check for all declined users
            for user_id, pretty in normalized_declined:
                pseudo_id = f"{msg.id}-{user_id}-declined"
                if not attendance_log.already_logged(pseudo_id):
                    attendance_log.log_attendance(user_id, pretty, msg.id, response="declined")
                    logged += 1

    await interaction.followup.send(
        f"Scanned {scanned} Apollo events, logged {logged} attendees (limit: {limit})."
    )


@bot.tree.command(name="scan_all_reactions", description="Scan recent messages for reactions and summarize them.")
@app_commands.describe(limit="How many recent messages to scan (default is 50)")
async def scan_all_reactions(interaction: discord.Interaction, limit: app_commands.Range[int, 1, 100] = 50):


    await defer_response(interaction,thinking=True)  # defer in case it takes a moment

    # initialize scanned to 0, and a dict of emoji lists
    scanned = 0
    emoji_summary = defaultdict(list)

    # we want to check every message in the channel this command is made in, and for every message amount mentioned when making the "/command",
    # increment the scanned counter
    async for msg in interaction.channel.history(limit=limit):
        scanned += 1

        # then for every reaction in the messages we scanned, set the users to a list of all users who have reacted to store reactions
        for reaction in msg.reactions:

            users = [user async for user in reaction.users()]

            # Only consider users, not bots
            for user in users:
                if user.bot:
                    continue

                # set a var member, using Discord's guild object and use the get_member method for that user.id, also set display_name to that member
                # display name, if the user is a member, else just get the discord username (because nickname for non-members might not be set)
                member = interaction.guild.get_member(user.id)
                display_name = member.display_name if member else user.name

                # append the emoji summary dict with a string representation of the reaction emojis like ":x:, :white_check_mark: ..." on the display_name
                emoji_summary[str(reaction.emoji)].append(display_name)

    if not emoji_summary:
        await interaction.followup.send(f"No reactions found in the last {limit} messages.")
        return

    # set a list of lines as an f string to show number of scanned messages
    lines = [f"**Reactions Summary (from last {scanned} messages)**\n"]

    # then for each emoji, user in the emoji_summary dict (we are unpacking the dict, using .items() to index into the dict)
    for emoji, users in emoji_summary.items():

        # get a set of unique users
        unique_users = set(users)

        # append the 'lines' list with the f string of each emoji, mapped to each set of users
        lines.append(f"{emoji} - {len(users)} reaction(s) from: {', '.join(unique_users)}")

    await interaction.followup.send("\n".join(lines))


# The command to show the leaderboard
# for slash commands using @bot.tree.command, the callback function must accept a discord.Interaction as the first argument, not ctx
# wherever using ctx.send(), it should become send_response(interaction,) or interaction.followup.send() depending on
# whether we're deferring the response.
@bot.tree.command(name="leaderboard",
                  description="Show a ranked summary leaderboard of accepted and declined for the last 8 events")
async def leaderboard(interaction: discord.Interaction):
    if event_log.total_events == 0:
        await send_response(interaction, "No events have been scanned yet.")
        return
    await defer_response(interaction)

    # Get participation summary
    participation_data = event_log.get_all_participants()

    # Sort users by accepted count (descending)
    sorted_participants = sorted(
        participation_data.items(),
        key=lambda x: (-x[1]["accepted"], x[1]["display_name"])
    )

    # Format leaderboard
    lines = [f"**Attendance Leaderboard {datetime.now().strftime('%B')}**"]
    total_events = event_log.total_events

    # Add each participant's stats
    for i, (user_id, stats) in enumerate(sorted_participants, start=1):
        display_name = stats["display_name"]
        accepted = stats["accepted"]
        lines.append(f"{i}. **{display_name}** - {accepted}/{total_events} events ✅")

    # Add declined-only users
    declined_only = [
        (user_id, stats) for user_id, stats in sorted_participants
        if stats["accepted"] == 0 and stats["declined"] > 0
    ]

    if declined_only:
        lines.append(f"\n**Declined (❌)**")
        for i, (user_id, stats) in enumerate(declined_only, start=1):
            display_name = stats["display_name"]
            declined = stats["declined"]
            lines.append(f"{i}. **{display_name}** - {declined} declines ❌")

    # Add total unique responders
    lines.append(f"\nTotal unique responders: {len(participation_data)}")

    # Send the message
    message = "\n".join(lines)
    await defer_response(interaction, thinking=True)

    if len(message) > 1900:
        for chunk in [message[i:i + 1900] for i in range(0, len(message), 1900)]:
            await interaction.followup.send(chunk)
    else:
        await interaction.followup.send(message)



if __name__ == "__main__":
    bot_config.initialize()
    # Run the bot with a token of server
    bot.run(bot_config.TOKEN)
