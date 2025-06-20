""" 
This is a unique discord bot that reverse-engineers the closed source event and server management bots using the Discord API, essentially forming a
    closed ecosystem extraction. It scans the activity of other bots in the server by creating a websocket with the hosts, using Discord's Gateway API.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any

import discord
import os

import yaml
from dotenv import load_dotenv
from datetime import datetime
from discord.ext import commands
from discord import app_commands
from collections import defaultdict
import re


class BotConfig:
    def __init__(self):
        self.TOKEN = None
        self.CHANNEL_ID = None
        self.GUILD_ID = None

    @staticmethod
    def load_config(config_path: str) -> Optional[Dict[str, Any]]:
        """
        Load configuration from a YAML file.

        Args:
            config_path: Path to the YAML configuration file

        Returns:
            Dictionary containing the configuration or None if loading fails

        Example YAML file:
            database:
              host: localhost
              port: 5432
            api:
              key: abc123
              timeout: 30
        """
        path = Path(config_path)

        if not path.exists():
            print(f"Config file not found: {config_path}")
            return None

        try:
            with path.open('r', encoding='utf-8') as file:
                config = yaml.safe_load(file)

            if not isinstance(config, dict):
                print("Invalid YAML structure: root element must be a mapping")
                return None

            return config

        except yaml.YAMLError as e:
            print(f"Error parsing YAML file: {e}")
            return None
        except Exception as e:
            print(f"Unexpected error loading config: {e}")
            return None

    @staticmethod
    def get_env_or_config(env_key: str, config: dict, config_path: str, transform: Optional[callable] = None) -> Any:
        """
        Get value from environment variable or fallback to nested config file.

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
                print(f"Error transforming value for {env_key}: {e}")
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

        # Get values with fallback
        self.TOKEN = self.get_env_or_config("TOKEN", config, "bot.token", str)
        self.CHANNEL_ID = self.get_env_or_config("CHANNEL_ID", config, "bot.channel_id", int)
        self.GUILD_ID = self.get_env_or_config("GUILD_ID", config, "bot.guild_id", str)

        if not self.TOKEN:
            print("Invalid Discord Bot Token.")
            exit(-1)

        if not self.CHANNEL_ID or not self.is_valid_snowflake(str(self.CHANNEL_ID)):
            print(f"Invalid Channel ID format: {self.CHANNEL_ID}")
            exit(-1)

        if not self.GUILD_ID or not self.is_valid_snowflake(self.GUILD_ID):
            print(f"Invalid Guild ID format: {self.GUILD_ID}")
            exit(-1)


@dataclass
class AttendanceEntry:
    """
    Class representing an attendance log entry.

    Attributes:
        user_id (str): The normalized user ID
        username (str): The pretty/display name of the user
        event_id (str): The ID of the event
        response (str): The response type ("accepted" or "declined")
        timestamp (str): ISO format timestamp of when entry was created
    """
    user_id: str
    username: str
    event_id: str
    response: str = "accepted"
    timestamp: str = None

    def __post_init__(self):
        """Set timestamp if not provided during initialization"""
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


# Create a global config instance
bot_config = BotConfig()

# Initialize the discord intent object and set most needed paramters from the docs of "discord" to True
intents = discord.Intents.default()

# Required for commands and reading messages
intents.message_content = True

# obviously, required for reactions, members ids/names and the guild/clan itself
intents.reactions = True
intents.members = True
intents.guilds = True

# needed to receive message + reaction payloads
intents.messages = True

# get the bot commands in a variable with usual/standard prefix
bot = commands.Bot(command_prefix="/", intents=intents)

# In-memory log: pseudo_id -> log entry
attendance_log = {}

# Holds data for the most recent 8 Apollo events
event_log = []  # Populate this in /scan_apollo command


# already logged function that removes duplicates
def already_logged(pseudo_id):
    return pseudo_id in attendance_log


def normalize_name(name: str) -> str:
    """ Using regex, we normalise scanned names to pass into other functions. """
    name = name.lower()
    name = re.sub(r"[^\w\s]", "", name)  # remove punctuation
    name = re.sub(r"\s+", " ", name)     # normalize whitespace
    return name.strip()


def log_attendance(user_id, username, event_id, response="accepted"):

    normalized_id = normalize_name(user_id)
    pseudo_id = f"{event_id}-{normalized_id}" if response == "accepted" else f"{event_id}-{normalized_id}-declined"

    if pseudo_id not in attendance_log:
        attendance_log[pseudo_id] = {

            "timestamp": datetime.now().isoformat(),
            "user_id": normalized_id,

            # preserve pretty version (username_x becomes server specific 'nickname' eg for milsim clans: pyle -> Pvt G. Pyle)
            "username": username.strip(),
            "event_id": event_id,
            "response": response
        }

@bot.event
async def on_ready():

    print(f"Bot is connected as {bot.user}")
    print(f"Logged in as {bot.user}")

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s).")

    except Exception as e:
        print(f"Error syncing commands: {e}")

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
    await ctx.send(f"Current entries: {len(attendance_log)}")


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
        await interaction.response.send_message(f"No Apollo messages found in last {limit} messages.")
    else:
        await interaction.response.send_message(f"Found {found} Apollo messages.", ephemeral=True)


# lets list recent messages and their authors
@bot.tree.command(name="recent_authors", description="Show recent authors from the channel.")
@app_commands.describe(limit="Number of messages to scan (default 20)")
async def recent_authors(interaction: discord.Interaction, limit: int = 20):

    authors = set()
    limit = min(limit, 200)

    async for msg in interaction.channel.history(limit=limit):
        authors.add(msg.author.name)

    result = ", ".join(authors)
    await interaction.response.send_message(
        f"Recent authors from last {limit} messages:\n{result}"
    )


# TODO: Make a /help_awards_bot command
@bot.tree.command(name="hilf", description="Show all available commands and their usage.")
async def hilf(interaction: discord.Interaction):

    await interaction.response.defer()  # defer in case it takes a moment

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

    await interaction.response.defer()  # defer in case it takes a moment

    notes_text = """
            Staff meeting notetaking template

            `**Promotions and awards**


            **Astro award:-**


            **good conduct**


            **Red Cross**


            **Promotions**


            - Fox Red:

            - Centurion:

            

            **Out of Probation**


            __Discussion Part__
            **Staff Notes**:-


            __NCO TRAINED__ (if any)



            __NCOs__

            **Shughart**


            **Hastings**


            **Banjo**


            **Rydah** 


            **Mooses**


            **Aranel**


            **Miller**


            **Astro**


            **Landa**


            **Adams**

            **__Public Notes__** (if any)`
"""
    await interaction.followup.send(notes_text)


@bot.tree.command(name="debug_apollo", description="Scan recent messages for Apollo embeds and show raw fields for debugging.")
@app_commands.describe(limit="How many recent messages to scan (default 50)")
async def debug_apollo(interaction: discord.Interaction, limit: int = 50):


    await interaction.response.defer()
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
    for entry in attendance_log.values():
        normalized = normalize_name(entry["username"])
        seen[normalized].add(entry["username"])

    duplicates = {k: v for k, v in seen.items() if len(v) > 1}

    # Defer in case it takes time
    await interaction.response.defer()

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

    # initialise scanned and logged as 0
    scanned = 0
    logged = 0

    # limit the apollo scans to a max of 100
    limit = min(limit, 100)

    # Ensure CHANNEL_ID is int or convert
    # also, if you dont want to hard-code the channel id and instead want to type the channel id as an argument to the command, you can do so
    target_channel = bot.get_channel(int(bot_config.CHANNEL_ID))
    if not target_channel:
        await interaction.response.send_message("Failed to fetch the announcements channel.")
        return

    # the thining is "the bot is thinking", which is set to true
    await interaction.response.defer(thinking=True)

    # NOTE -> here on, we will be focusing on scanning the actual apollo messages

    # for every message in the target channel, with the current limit of how many prior messages to scan, we will check if its a message by apollo first
    async for msg in target_channel.history(limit=limit):
        if "Apollo" not in msg.author.name:
            continue
        
        # if it is apollo, increment scanned messages count by 1
        scanned += 1

        # ---- NOTE ----
        # the way Apollo does its ✅, ❌ for example is not the actual emoji, that would be :white_check_mark: and :x: . Rather apollo has its own
        # server side embeds which it displays as those emojis in its default functionality, for attendance of the event as:
        # :accepted: :declined:

        # NOTE: The "embed" object here, refers to an instance of discord.Embed, which is a class provided by the discord.py library representing 
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

        # then for each embed in the the message embeds, set a list of what embed we want to keep track of ie: here we keep track of attendees and declined
        # but that goes for literally anything else, using any other of apollo's function, thats why the "/show_apollo_embeds" function exists
        # So we are looping through all embed objects attached to a single message 'msg'
        for embed in msg.embeds:
            attendees = []
            declined = []

            # then fo each field in the embeds' fields, check for both accepted and declined
            # embed.fields is a list of named fields in that embed (e.g., "Accepted", "Declined").
            for field in embed.fields:

                # strip them of their standard apollo format, and appent the plain names to the attendees dict, do the same for declined
                # parse the .value of each field to extract user names by "normalising" them
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

            # the embed object description, is how the bot parses each description for each line in the description of event but remember:
            # this condition is outside the field loop, but inside the main msg embed loop so the description embed is here, for this specific use case,
            # showing the 
            if embed.description:
                for line in embed.description.split("\n"):
                    if line.strip().startswith("-"):
                        name = line.strip("- ").strip()
                        if name:
                            attendees.append(name)

            # debug loop for seeing the exact inner workings of the bot embeds in json like format
            for embed in msg.embeds:
                print(embed.to_dict())

            # we then want to get tuples of the names in each of the 2 lists we have so far, and call the normalized_name function on it, 
            # to well... normalize them using list iteration
            normalized_declined = [(normalize_name(name), name) for name in declined]
            normalized_attendees = [(normalize_name(name), name) for name in attendees]

            # append the MAIN list, at global level which is keeping track of mapping the attributes to the id's like we see below
            event_log.append({
                "event_id": msg.id,
                "accepted": normalized_attendees,
                "declined": normalized_declined
            })

            # now im "pretty printing" it so i dont want to see ".username_x" but their actual server name like in a milsim server (Pvt M. Cooper)
            # for every user_id and pretty name in each of the lists ie, "attendees" and "declined", we first want to check if they are already logged
            # by calling the "already_logged" function with the "pseudo_id" to prevent duplicates, and if thats not the casem we append logged by 1
            for user_id, pretty in normalized_attendees:
                pseudo_id = f"{msg.id}-{user_id}"
                if not already_logged(pseudo_id):
                    log_attendance(user_id, pretty, msg.id)
                    logged += 1

            # fore declined we do the same, but we pass the response parameter and check for all declined users
            for user_id, pretty in normalized_declined:
                pseudo_id = f"{msg.id}-{user_id}-declined"
                if not already_logged(pseudo_id):
                    log_attendance(user_id, pretty, msg.id, response="declined")
                    logged += 1

    await interaction.followup.send(
        f"Scanned {scanned} Apollo events, logged {logged} attendees (limit: {limit})."
    )


@bot.tree.command(name="scan_all_reactions", description="Scan recent messages for reactions and summarize them.")
@app_commands.describe(limit="How many recent messages to scan (default is 50)")
async def scan_all_reactions(interaction: discord.Interaction, limit: app_commands.Range[int, 1, 100] = 50):

    await interaction.response.defer(thinking=True)  # defer in case it takes a moment

    # initialise scanned to 0, and a dict of emoji lists
    scanned = 0
    emoji_summary = defaultdict(list)

    # we want to checn every message in the channel this command is made in, and for every message amount mentioned when making the "/command",
    # increment the scanned counter
    async for msg in interaction.channel.history(limit=limit):
        scanned += 1

        # then for every reaction in the messages we scanned, set the users to a list of all users who have reacted to store reactions
        for reaction in msg.reactions:

            users = [user async for user in reaction.users()]

            # Only consider users not bots
            for user in users:
                if user.bot:
                    continue
                
                # set a var member, using Discord's guild object and use the get_member method for that user.id, also set display_name to that members
                # display name, if the the user is a member, else just get the discord username (because nickname for non members might not be set)
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
# wherever using ctx.send(), it should become interaction.response.send_message() or interaction.followup.send() depending on 
# whether we're deferring the response.
@bot.tree.command(name="leaderboard", description="Show a ranked summary leaderboard of accepted and declined for the last 8 events")
async def leaderboard(interaction: discord.Interaction):

    # if the global dict "event_log" is empty, then no messages have been scanned
    if len(event_log) == 0:
        await interaction.response.send_message("No events have been scanned yet.")
        return

    # ser recent events to the event_log dict but only 8 bot messages from Apollo
    recent_events = event_log[-8:]

    # now we want to set a dict for each type of reaction 
    # NOTE--- in this case its only accepted and declined because thats my use case, you can have multiple, just follow this template/general idea

    # the general idea being, we want EACH parsed representation of a type of reaction-user mapping to be its own datastructure for cleanliness and 
    # separation of concerns. I want the number of declined and accepted, a set of unique users and a dict of pretty names (nickname scanned by "scan_apollo")
    accepted_count = defaultdict(int)
    declined_count = defaultdict(int)
    unique_users = set()
    pretty_names = {}

    # for every event in the scanned recent events, we will be going over the accepted reactions and declined reactions
    for event in recent_events:

        # then for each normal user_id and the pretty version thereof in the accepted category list of that event,
        for user_id, pretty in event["accepted"]:

            # increment the accepted count dict by 1, then for every user_id in the pretty_names dict, we set that to the pretty ie, the nickname, and 
            # add that user_id to the set of unique users
            accepted_count[user_id] += 1
            pretty_names[user_id] = pretty
            unique_users.add(user_id)

        # similar for declined users, just that we use event.get, a temp list of declined while iterating, to keep track of how many user_id and pretty
        for user_id, pretty in event.get("declined", []):

            # increment the declined users by 1, add that user_id to the unique users set, and strip any trailing/leading whitespace before setting
            # those user_id equal to the user_id in the pretty_names dict
            declined_count[user_id] += 1
            unique_users.add(user_id)
            pretty_names[user_id] = pretty.strip()

    # now we want to sort the accepted users, bu counting that dict and using a lambda function that sorts them by descending
    accepted_sorted = sorted(
        accepted_count.items(),
        key=lambda x: (-x[1], x[0])
    )

    # we want a similar 'lines' list as previous function to show the leaderboard
    lines = [f"**Attendance Leaderboard {datetime.now().strftime('%B')}**"]
    total_events = len(recent_events)

    # and for each user 'user_id' and the 'count' (tuple) we want to number it firstly, then, append to the lines list by using the fstring of how we want
    # the data to be shown
    for i, (user_id, count) in enumerate(accepted_sorted, start=1):
        lines.append(f"{i}. **{pretty_names[user_id]}** - {count}/{total_events} events ✅")

    # check how many unique attendees if at all
    if accepted_count:
        lines.append(f"\nTotal unique attendees (accepted): {len(accepted_count)}")
    else:
        lines.append("\nNo attendees found in last 8 events.")

    # then we make a declined exclusive dict, where we are using dict iteration to check key-name, for value-count, in the declined_count dict, is only there
    # if its not there in the accepted_count dict. SO, if they declined, they should not be in accepted dict
    declined_only = {
        name: count for name, count in declined_count.items()
        if name not in accepted_count
    }

    # if that above dict is true, append to the lines list with an fstring to show the data, same as accepted_sorted
    if declined_only:

        lines.append(f"\n**Declined (❌)**")
        declined_sorted = sorted(
            declined_only.items(),
            key=lambda x: (-x[1], x[0])
        )

        for i, (norm_name, count) in enumerate(declined_sorted, start=1):

            display_name = pretty_names.get(norm_name, norm_name).strip()
            lines.append(f"{i}. **{display_name}** - {count} declines ❌")

    lines.append(f"\nTotal unique responders: {len(unique_users)}")

    # if message exceeds character limit then send the next chunk in a new line/message
    message = "\n".join(lines)

    # defer response to allow time if needed
    await interaction.response.defer(thinking=True)

    # send large messages in chunks
    if len(message) > 1900:
        for chunk in [message[i:i+1900] for i in range(0, len(message), 1900)]:
            await interaction.followup.send(chunk)
    else:
        await interaction.followup.send(message)



if __name__ == "__main__":
    bot_config.initialize()
    # Run the bot with token of server 
    bot.run(bot_config.TOKEN)
