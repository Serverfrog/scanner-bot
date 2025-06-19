import discord
import csv
import os
from datetime import datetime
from discord.ext import commands
from collections import defaultdict


""" 
This is a unique discord bot that reverse-engineers the closed source event and server management bots using the Discord API, essentially forming a
    closed ecosystem extraction. It scans the activty of other bots in the server by creating a websocket with the hosts, using Discord's Gateway API.
"""

# First configure globs for discord library, since this is designed to run locally, dont worry about a .env folder or anything.
# Remember, the bot will only be up, as long as you are running your python script.
TOKEN = "your token here"
GUILD_ID = "your discord server/guild id"
CHANNEL_ID = "the channel id where you want the bot to scan"  # optional, you could just make the bot commands in the target channel but that can get messy
REACTION_EMOJI = "✅"

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


# Get the csv file number and use the datetime lib to get time of all during command and return the f string thereof
def get_csv_filename():
    now = datetime.now()
    return f"attendance_{now.year}_{now.month:02}.csv"


# already logged function that removes duplicates
def already_logged(pseudo_id, message_id):
    filename = get_csv_filename()
    if not os.path.isfile(filename):
        return False
    with open(filename, newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        # Use "EventID" instead of "MessageID"
        return any(
            row["UserID"] == pseudo_id and row["EventID"] == str(message_id)
            for row in reader
        )


# now log user's attendance to the filename
def log_attendance(user_id, username, event_id, response="accepted"):
    filename = get_csv_filename()
    file_exists = os.path.isfile(filename)

    with open(filename, "a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)

        # Write header only if file does not exist yet
        if not file_exists:
            writer.writerow(["Timestamp", "UserID", "Username", "EventID", "Response"])

        # Write attendance data row
        writer.writerow(
            [datetime.now().isoformat(), user_id, username, event_id, response]
        )


@bot.event
async def on_ready():
    print(f"Bot is connected as {bot.user}")


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


# This will print embed descriptions so we can see exactly what text is there (for reverse engineering websocket requests of other bots)
@bot.command()
async def show_apollo_embeds(ctx):
    found = 0
    async for msg in ctx.channel.history(limit=50):
        if "Apollo" in msg.author.name:
            found += 1
            for embed in msg.embeds:
                await ctx.send(f"Embed description:\n```{embed.description}```")
    if found == 0:
        await ctx.send("No Apollo messages found in last 50 messages.")


# lets list recent messages and their authors
@bot.command()
async def recent_authors(ctx):
    authors = set()
    async for msg in ctx.channel.history(limit=20):
        authors.add(msg.author.name)
    await ctx.send(f"Recent authors: {', '.join(authors)}")


@bot.command()
async def halp(ctx):
    help_text = """
        **Attendance Bot Commands:**

        `/scan_apollo` — Scans recent Apollo messages and logs users who reacted with ✅ or :accepted:.

        `/leaderboard` — Shows this month's attendance leaderboard, based on unique events attended.

        `/show_apollo_embeds` — Prints the descriptions of recent Apollo embeds for debugging.

        `/recent_authors` — Lists authors of the last 20 messages in the channel.

        > This bot tracks Apollo event reactions to summarize user participation.
        """
    await ctx.send(help_text)


@bot.command()
async def debug_apollo(ctx):
    async for msg in ctx.channel.history(limit=10):
        if "Apollo" in msg.author.name:
            for embed in msg.embeds:
                await ctx.send(
                    f"Embed title: {embed.title}\nDesc:\n```{embed.description}```"
                )
                for field in embed.fields:
                    await ctx.send(
                        f"Field name: {field.name}\nValue:\n```{field.value}```"
                    )


# command to gather Apollo data, cause its fucking CLOSED SOURCE!!
@bot.command()
async def scan_apollo(ctx):
    scanned = 0
    logged = 0

    # find channel by name
    target_channel = bot.get_channel(CHANNEL_ID)
    if not target_channel:
        await ctx.send(f"Failed to fetch the announcements channel.")
        return

    async for msg in target_channel.history(limit=18):
        if "Apollo" not in msg.author.name:
            continue

        scanned += 1
        for embed in msg.embeds:
            attendees = []
            declined = []

            # Case 1: Look inside embed.fields for a field named like ":accepted:"
            for field in embed.fields:
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

            # Case 2: Look inside embed.description (fallback)
            if embed.description:
                lines = embed.description.split("\n")
                for line in lines:
                    if line.strip().startswith("-"):
                        name = line.strip("- ").strip()
                        if name:
                            attendees.append(name)

            # Log each attendee with pseudo ID
            for name in attendees:
                pseudo_id = f"{msg.id}-{name}"
                if not already_logged(pseudo_id, msg.id):
                    log_attendance(
                        name, name, msg.id
                    )  # using 'name' as user_id and username, or Discord user ID if available
                logged += 1
            else:
                print(f"Already logged: {name} with ID {pseudo_id}")

            for name in declined:
                pseudo_id = f"{msg.id}-{name}-declined"
                if not already_logged(pseudo_id, msg.id):
                    log_attendance(name, name, msg.id, response="declined")
                    logged += 1
                else:
                    print(f"Already logged: {name} with ID {pseudo_id}")

    await ctx.send(f"Scanned {scanned} Apollo events, logged {logged} attendees.")


@bot.command(name="scan_all_reactions")
async def scan_all_reactions(ctx):
    """
    Scan recent messages in the channel and log users who reacted with ✅, ❌ or other similar emojis. (like for quick attendance chcks)
    Shows which user used what emoji as well.
    """

    scanned = 0

    # Use a dict to map emojis to usernames {emoji: [usernames]}
    emoji_summary = defaultdict(list)

    # Change `limit`` if you want
    async for msg in ctx.channel.history(limit=50):
        scanned += 1

        # iterate over every reaction in message and find users who reacted
        for reaction in msg.reactions:

            # use list comprehension to get the user and iterate for every user in "users" list, and check for bot reactions cause we wanna skip those
            users = [user async for user in reaction.users()]
            for user in users:
                if user.bot:
                    continue

                # Get display name from guild, we dont want username we want SERVER name so, fetch the Member object from the guild and use .display_name
                member = ctx.guild.get_member(user.id)

                # set display name to member object's display name, if there is a member otherwise use user.name (fallback)
                display_name = member.display_name if member else user.name
                emoji_summary[str(reaction.emoji)].append(display_name)

    # check for reactions
    if not emoji_summary:
        await ctx.send("No reactions found in the last 50 messages.")
        return

    lines = [f"**Reactions Summary (from last {scanned} messages)**\n"]
    for emoji, users in emoji_summary.items():
        unique_users = set(users)
        lines.append(
            f"{emoji} — {len(users)} reaction(s) from: {', '.join(unique_users)}"
        )

    await ctx.send("\n".join(lines))


# The command to show the leaderboard
@bot.command()
async def leaderboard(ctx):
    filename = get_csv_filename()

    if not os.path.isfile(filename):
        await ctx.send("No attendance data for this month yet.")
        return

    attendance = defaultdict(set)  # user_id -> set of accepted event IDs
    declined = defaultdict(set)  # user_id -> set of declined event IDs
    usernames = {}  # user_id -> pretty username

    with open(filename, newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            raw_username = row["Username"].strip()
            user_id = raw_username.lower()
            event_id = row["EventID"].strip()
            response = row.get("Response", "accepted").lower()

            usernames[user_id] = raw_username
            if response == "accepted":
                attendance[user_id].add(event_id)
            elif response == "declined":
                declined[user_id].add(event_id)

    total_events = 8  # fix as per your monthly events

    # Sort accepted users by descending attendance count, then username
    accepted_sorted = sorted(
        attendance.items(), key=lambda x: (-len(x[1]), usernames.get(x[0], ""))
    )

    lines = [f"**Attendance Leaderboard {datetime.now().strftime('%B')}**"]
    max_to_print = 40
    count_printed = 0

    # Print accepted attendees (up to max_to_print)
    for i, (user_id, events) in enumerate(accepted_sorted, start=1):
        count = len(events)
        if count == 0:
            continue
        username = usernames.get(user_id, "Unknown")
        lines.append(f"{i}. **{username}** - {count}/{total_events} events ✅")
        count_printed += 1
        if count_printed >= max_to_print:
            break

    if count_printed == 0:
        lines.append("No attendees logged this month.")
    else:
        lines.append(f"\nTotal unique attendees (accepted): {len(attendance)}")

    # Filter declined users to only those who never accepted anything
    declined_only = {
        uid: evts for uid, evts in declined.items() if uid not in attendance
    }

    if declined_only:
        lines.append(f"\n**Declined (❌)**")
        declined_sorted = sorted(
            declined_only.items(), key=lambda x: (-len(x[1]), usernames.get(x[0], ""))
        )
        for i, (user_id, events) in enumerate(declined_sorted, start=1):
            if i + count_printed > max_to_print:
                break
            username = usernames.get(user_id, "Unknown")
            lines.append(
                f"{count_printed + i}. **{username}** - {len(events)} declines ❌"
            )

    # Total unique responders (accepted + declined)
    unique_responders = set(attendance.keys()) | set(declined.keys())
    lines.append(f"\nTotal unique responders: {len(unique_responders)}")

    # Send message (consider splitting if too long)
    message = "\n".join(lines)
    if len(message) > 1900:

        # Optional: split message if too long
        chunks = [message[i : i + 1900] for i in range(0, len(message), 1900)]
        for chunk in chunks:
            await ctx.send(chunk)
    else:
        await ctx.send(message)


# Run the bot with token of server
bot.run(TOKEN)
