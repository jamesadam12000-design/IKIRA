import discord
import os
import sys
import asyncio
import random
from datetime import datetime, timedelta
from dotenv import load_dotenv
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)

# Load environment variables
load_dotenv()

# Configuration
TOKEN = os.getenv('DISCORD_TOKEN')
YOUR_USER_ID = os.getenv('YOUR_USER_ID')

# Debug startup
print("=" * 60)
print("🤖 DISCORD DM AUTO-REPLY + RELAY BOT")
print("=" * 60)

# Check token
if not TOKEN:
    print("❌ ERROR: DISCORD_TOKEN not found in environment variables")
    print("💡 Please add DISCORD_TOKEN to Railway variables")
    sys.exit(1)

# Check user ID
if not YOUR_USER_ID:
    print("❌ ERROR: YOUR_USER_ID not found in environment variables")
    print("💡 Please add YOUR_USER_ID to Railway variables")
    sys.exit(1)

# Convert user ID to int
try:
    YOUR_USER_ID = int(YOUR_USER_ID)
    print(f"✅ User ID loaded: {YOUR_USER_ID}")
except ValueError:
    print(f"❌ ERROR: YOUR_USER_ID must be a number, got: {YOUR_USER_ID}")
    sys.exit(1)

print(f"✅ Token loaded: {TOKEN[:15]}... (length: {len(TOKEN)})")
print("=" * 60)

# Bot configuration
COOLDOWN_MINUTES = 10
cooldowns = {}

# Maps a relayed message ID (sent to the owner) -> info needed to reply back.
# For DMs:      {"type": "dm", "user_id": <sender id>}
# For mentions:  {"type": "mention", "channel_id": <channel id>, "user_id": <sender id>}
relay_map = {}

# Remembers the most recent DM sender, so "!r <message>" works without
# needing to reply to a specific relayed message.
last_dm_sender_id = None
# Timestamp of when last_dm_sender_id was set, and who else has DMed recently,
# so !r can warn if it might be replying to the wrong person.
last_dm_sender_time = None
recent_dm_senders = {}  # user_id -> datetime of their most recent DM
AMBIGUITY_WINDOW_MINUTES = 10

# --- Per-person conversation history (in-memory "inbox") ---
# user_id -> list of {"from": "them" | "you", "text": str, "time": datetime}
conversation_history = {}
HISTORY_LIMIT = 20  # how many messages to keep per person

# Assigns each person a consistent color for their embeds, so scrolling your
# DM with the bot, you can visually tell conversations apart at a glance.
PERSON_COLORS = [
    0xE74C3C, 0x3498DB, 0x2ECC71, 0xF1C40F, 0x9B59B6,
    0x1ABC9C, 0xE67E22, 0xE91E63, 0x00BCD4, 0x8BC34A,
]
person_color_map = {}  # user_id -> color int


def get_person_color(user_id: int) -> int:
    if user_id not in person_color_map:
        person_color_map[user_id] = PERSON_COLORS[len(person_color_map) % len(PERSON_COLORS)]
    return person_color_map[user_id]


def log_conversation(user_id: int, sender: str, text: str):
    history = conversation_history.setdefault(user_id, [])
    history.append({"from": sender, "text": text, "time": datetime.now()})
    if len(history) > HISTORY_LIMIT:
        del history[0]


# Tracks the ONE live embed message per person in the owner's DM with the
# bot. New messages from/to that person EDIT this same message instead of
# sending a new one, so each person stays in a single scrolling container.
active_thread_message = {}  # user_id -> discord.Message


def build_thread_embed(user_id: int, author_name: str, kind: str) -> discord.Embed:
    history = conversation_history.get(user_id, [])
    lines = []
    for entry in history:
        who = "**You**" if entry["from"] == "you" else f"**{author_name}**"
        when = entry["time"].strftime("%b %d, %I:%M %p")
        lines.append(f"{who} ({when}): {entry['text']}")
    description = "\n\n".join(lines) if lines else "No messages yet."
    if len(description) > 4000:
        description = "...(earlier messages trimmed)\n\n" + description[-3900:]

    embed = discord.Embed(description=description, color=get_person_color(user_id),
                           timestamp=datetime.now())
    icon = "📨" if kind == "dm" else "🔔"
    embed.set_author(name=f"{icon} {author_name}")
    embed.set_footer(text=f"ID: {user_id} • Reply here, or use !r <text> / !r {user_id} <text>")
    return embed


async def relay_thread_update(user_id: int, author_name: str, kind: str):
    """Edit the existing container for this person if one exists, otherwise
    create it. Returns the message (new or edited) so callers can (re)map it
    in relay_map, or None on failure."""
    embed = build_thread_embed(user_id, author_name, kind)
    try:
        owner = await bot.fetch_user(YOUR_USER_ID)
        existing = active_thread_message.get(user_id)
        if existing:
            try:
                edited = await existing.edit(embed=embed)
                print("   📤 Updated existing container for this person")
                return edited
            except (discord.NotFound, discord.HTTPException) as e:
                print(f"   ⚠️ Couldn't edit existing container ({e}), sending a new one")

        sent = await owner.send(embed=embed)
        active_thread_message[user_id] = sent
        print("   📤 Created new container for this person")
        return sent
    except discord.Forbidden:
        print("   ❌ Could not relay to owner (owner has DMs from the bot disabled/blocked)")
    except Exception as e:
        print(f"   ❌ Error relaying to owner: {e}")
    return None


# Create bot with all required intents
intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True
intents.guilds = True
intents.members = True
intents.presences = True

bot = discord.Client(intents=intents)

# Reply messages based on status
REPLY_MESSAGES = {
    'online': [
        "Hey! I'm currently online but might be busy. I'll get back to you soon! 👋",
        "Hi! I'm online but AFK at the moment. Will reply when I can! 💻"
    ],
    'idle': [
        "Hey! I'm currently AFK. I'll reply as soon as I'm back! 🕐",
        "Hi! I'm away from my keyboard. Will respond when I return! 💤"
    ],
    'dnd': [
        "Hey! I'm currently busy. I'll get back to you when I'm free! 📵",
        "Hi! I'm in Do Not Disturb mode. I'll reply as soon as I'm available! 🚫"
    ],
    'offline': [
        "Hey! I'm currently offline. I'll reply when I come back online! 💤",
        "Hi! I'm not online right now. Will respond when I'm back! 🌙"
    ]
}


def get_reply(status):
    """Get a random reply based on status"""
    if status in REPLY_MESSAGES:
        return random.choice(REPLY_MESSAGES[status])
    return "Hey! Thanks for DMing me! I'll get back to you soon! 📨"


async def relay_to_owner(content: str, user_id: int = None, author_name: str = None,
                          kind: str = "dm", footer: str = None):
    """Send a message to the bot owner's DMs (from the bot, not as the user),
    as a color-coded embed so each person's thread is visually distinct in
    your DM history with the bot.
    Returns the sent Message object (or None on failure) so the caller can
    map it in relay_map for two-way replies."""
    try:
        owner = await bot.fetch_user(YOUR_USER_ID)
        if len(content) > 3900:
            content = content[:3900] + "\n...(truncated)"

        if user_id is not None:
            color = get_person_color(user_id)
            embed = discord.Embed(description=content, color=color,
                                   timestamp=datetime.now())
            icon = "📨" if kind == "dm" else "🔔"
            embed.set_author(name=f"{icon} {author_name}" if author_name else icon)
            if footer:
                embed.set_footer(text=footer)
            sent = await owner.send(embed=embed)
        else:
            sent = await owner.send(content)

        print("   📤 Relayed to owner")
        return sent
    except discord.Forbidden:
        print("   ❌ Could not relay to owner (owner has DMs from the bot disabled/blocked)")
    except Exception as e:
        print(f"   ❌ Error relaying to owner: {e}")
    return None


@bot.event
async def on_ready():
    """Called when bot connects to Discord"""
    print("=" * 60)
    print(f"✅ BOT ONLINE SUCCESSFULLY!")
    print(f"📋 Bot Name: {bot.user.name}")
    print(f"📋 Bot ID: {bot.user.id}")
    print(f"👥 Connected to {len(bot.guilds)} server(s)")
    print("-" * 60)

    for guild in bot.guilds:
        print(f"📁 Server: {guild.name} (ID: {guild.id})")
        try:
            member = guild.get_member(YOUR_USER_ID)
            if member:
                print(f"   ✅ YOU are in this server! Status: {member.status}")
            else:
                print(f"   ⚠️ You are NOT in this server (can't check status or catch mentions here)")
        except Exception as e:
            print(f"   ⚠️ Could not check membership: {e}")

    print("=" * 60)
    print("📨 Bot is now MONITORING for DMs and @mentions...")
    print("=" * 60)

    try:
        await bot.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="for DMs & mentions"
            )
        )
    except Exception as e:
        print(f"⚠️ Could not set presence: {e}")

    if not getattr(bot, "_keep_alive_started", False):
        bot._keep_alive_started = True
        bot.loop.create_task(keep_alive())


@bot.event
async def on_message(message):
    """Handle all incoming messages"""
    global last_dm_sender_id, last_dm_sender_time

    # Ignore messages from bots (including itself)
    if message.author.bot:
        return

    # === OWNER REPLYING THROUGH THE BOT ===
    # Only applies to messages the owner sends to the bot in DM.
    if isinstance(message.channel, discord.DMChannel) and message.author.id == YOUR_USER_ID:

        # Option A: owner used Discord's native "Reply" on a relayed message
        if message.reference and message.reference.message_id in relay_map:
            info = relay_map[message.reference.message_id]
            try:
                if info["type"] == "dm":
                    target_user = await bot.fetch_user(info["user_id"])
                    await target_user.send(message.content)
                    log_conversation(info["user_id"], "you", message.content)
                    relayed = await relay_thread_update(info["user_id"], str(target_user), "dm")
                    if relayed:
                        relay_map[relayed.id] = {"type": "dm", "user_id": info["user_id"]}
                    await message.add_reaction("✅")
                    print(f"   ↩️  Owner reply forwarded to {target_user} via DM")
                elif info["type"] == "mention":
                    channel = bot.get_channel(info["channel_id"])
                    if channel:
                        await channel.send(f"<@{info['user_id']}> {message.content}")
                        log_conversation(info["user_id"], "you", message.content)
                        try:
                            target_user = await bot.fetch_user(info["user_id"])
                            name = str(target_user)
                        except Exception:
                            name = f"User {info['user_id']}"
                        relayed = await relay_thread_update(info["user_id"], name, "mention")
                        if relayed:
                            relay_map[relayed.id] = {
                                "type": "mention",
                                "channel_id": info["channel_id"],
                                "user_id": info["user_id"],
                            }
                        await message.add_reaction("✅")
                        print(f"   ↩️  Owner reply forwarded to #{channel}")
                    else:
                        await message.reply("❌ Couldn't find that channel anymore.")
            except discord.Forbidden:
                await message.reply("❌ Couldn't deliver that — they may have DMs closed or blocked the bot.")
            except Exception as e:
                await message.reply(f"❌ Error forwarding reply: {e}")
            return

        # Option B: reply via the bot, e.g. "!r on my way" (most recent sender)
        # or "!r <user_id> on my way" (explicit target, works for anyone who's
        # ever DMed the bot this session)
        if message.content.startswith('!r '):
            raw = message.content[len('!r '):].strip()
            if not raw:
                await message.reply(
                    "⚠️ Usage:\n"
                    "`!r <message>` — replies to your most recent DM\n"
                    "`!r <user_id> <message>` — replies to a specific person (ID shown in their relay message)"
                )
                return

            # Check for explicit "!r <user_id> <message>" targeting
            parts = raw.split(maxsplit=1)
            explicit_target_id = None
            if parts[0].isdigit() and len(parts) > 1:
                explicit_target_id = int(parts[0])
                reply_text = parts[1]
            else:
                reply_text = raw

            if explicit_target_id is not None:
                try:
                    target_user = await bot.fetch_user(explicit_target_id)
                    await target_user.send(reply_text)
                    log_conversation(explicit_target_id, "you", reply_text)
                    relayed = await relay_thread_update(explicit_target_id, str(target_user), "dm")
                    if relayed:
                        relay_map[relayed.id] = {"type": "dm", "user_id": explicit_target_id}
                    await message.add_reaction("✅")
                    print(f"   ↩️  Owner reply forwarded to {target_user} via DM (explicit ID)")
                except discord.NotFound:
                    await message.reply(f"❌ No Discord user found with ID `{explicit_target_id}`.")
                except discord.Forbidden:
                    await message.reply("❌ Couldn't deliver that — they may have DMs closed or blocked the bot.")
                except Exception as e:
                    await message.reply(f"❌ Error forwarding reply: {e}")
                return

            # No explicit ID given — fall back to "most recent sender" with
            # an ambiguity check if multiple people have DMed recently.
            if last_dm_sender_id is None:
                await message.reply("⚠️ No recent DM to reply to yet.")
                return

            now = datetime.now()
            window = timedelta(minutes=AMBIGUITY_WINDOW_MINUTES)
            recent_others = [
                uid for uid, ts in recent_dm_senders.items()
                if uid != last_dm_sender_id and now - ts <= window
            ]

            if recent_others:
                try:
                    target_preview = await bot.fetch_user(last_dm_sender_id)
                except Exception:
                    target_preview = last_dm_sender_id
                others_preview = []
                for uid in recent_others:
                    try:
                        u = await bot.fetch_user(uid)
                        others_preview.append(f"{u} (ID: {uid})")
                    except Exception:
                        others_preview.append(f"ID: {uid}")
                await message.reply(
                    f"⚠️ More than one person has DMed you recently, so `!r` alone is ambiguous.\n"
                    f"Most recent: **{target_preview}** (ID: `{last_dm_sender_id}`)\n"
                    f"Also recent: {', '.join(others_preview)}\n\n"
                    f"Use `!r <user_id> <message>` to target one directly, or reply "
                    f"natively to their relay message."
                )
                return

            try:
                target_user = await bot.fetch_user(last_dm_sender_id)
                await target_user.send(reply_text)
                log_conversation(last_dm_sender_id, "you", reply_text)
                relayed = await relay_thread_update(last_dm_sender_id, str(target_user), "dm")
                if relayed:
                    relay_map[relayed.id] = {"type": "dm", "user_id": last_dm_sender_id}
                await message.add_reaction("✅")
                print(f"   ↩️  Owner quick-reply forwarded to {target_user} via DM")
            except discord.Forbidden:
                await message.reply("❌ Couldn't deliver that — they may have DMs closed or blocked the bot.")
            except Exception as e:
                await message.reply(f"❌ Error forwarding reply: {e}")
            return

    # === OWNER: !inbox — list all conversations, most recently active first ===
    if isinstance(message.channel, discord.DMChannel) and message.author.id == YOUR_USER_ID \
            and message.content.strip() == '!inbox':
        if not conversation_history:
            await message.reply("📭 Your inbox is empty — no conversations yet.")
            return

        # Sort by most recent message time, descending
        sorted_users = sorted(
            conversation_history.items(),
            key=lambda item: item[1][-1]["time"] if item[1] else datetime.min,
            reverse=True,
        )

        embed = discord.Embed(
            title="📥 Inbox",
            description="Most recent conversations first. Use `!history <id>` to open a full thread.",
            color=0x2C2F33,
            timestamp=datetime.now(),
        )
        for user_id, history in sorted_users[:20]:
            if not history:
                continue
            try:
                user = await bot.fetch_user(user_id)
                name = str(user)
            except Exception:
                name = f"User {user_id}"

            last = history[-1]
            prefix = "You: " if last["from"] == "you" else ""
            preview = last["text"]
            if len(preview) > 100:
                preview = preview[:100] + "..."
            when = last["time"].strftime("%b %d, %H:%M")

            embed.add_field(
                name=f"{name}  •  {when}",
                value=f"{prefix}{preview}\n-# ID: `{user_id}`",
                inline=False,
            )

        await message.reply(embed=embed)
        return

    # === OWNER: !history <id> — full thread with one person ===
    if isinstance(message.channel, discord.DMChannel) and message.author.id == YOUR_USER_ID \
            and message.content.startswith('!history'):
        parts = message.content.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip().isdigit():
            await message.reply("⚠️ Usage: `!history <user_id>` (ID shown in their inbox entry or relay message)")
            return

        target_id = int(parts[1].strip())
        history = conversation_history.get(target_id)
        if not history:
            await message.reply("📭 No conversation history found for that ID yet.")
            return

        try:
            user = await bot.fetch_user(target_id)
            name = str(user)
        except Exception:
            name = f"User {target_id}"

        lines = []
        for entry in history:
            who = "**You**" if entry["from"] == "you" else f"**{name}**"
            when = entry["time"].strftime("%b %d, %H:%M")
            lines.append(f"{who} ({when}): {entry['text']}")

        embed = discord.Embed(
            title=f"💬 Conversation with {name}",
            description="\n\n".join(lines),
            color=get_person_color(target_id),
        )
        embed.set_footer(text=f"ID: {target_id}")
        await message.reply(embed=embed)
        return

    # === TEST COMMAND ===
    if message.content.startswith('!testdm'):
        try:
            await message.author.send("✅ Test successful! The bot can send you DMs!")
            await message.reply("📨 Check your DMs!")
            print(f"📨 Test DM sent to {message.author}")
        except discord.Forbidden:
            await message.reply("❌ I can't DM you! Please enable DMs from server members.")
        except Exception as e:
            await message.reply(f"❌ Error: {e}")
        return

    # === CASE 1: DM sent directly to the bot ===
    if isinstance(message.channel, discord.DMChannel):
        print("-" * 60)
        print(f"📨 DM RECEIVED")
        print(f"   From: {message.author} (ID: {message.author.id})")
        print(f"   Content: {message.content[:100]}")
        print(f"   Time: {datetime.now().strftime('%H:%M:%S')}")

        # Ignore if DM is from yourself (prevents infinite loops)
        if message.author.id == YOUR_USER_ID:
            print("   ⏭️  Ignoring - DM from yourself")
            print("-" * 60)
            return

        # Always relay the DM content to the owner, regardless of cooldown
        last_dm_sender_id = message.author.id
        last_dm_sender_time = datetime.now()
        recent_dm_senders[message.author.id] = last_dm_sender_time
        log_conversation(message.author.id, "them", message.content)
        relayed = await relay_thread_update(message.author.id, str(message.author), "dm")
        if relayed:
            relay_map[relayed.id] = {"type": "dm", "user_id": message.author.id}

        # Check cooldown for the auto-reply (relay above is not subject to this)
        on_cooldown = False
        if message.author.id in cooldowns:
            if datetime.now() < cooldowns[message.author.id]:
                remaining = int((cooldowns[message.author.id] - datetime.now()).total_seconds())
                print(f"   ⏳ Auto-reply cooldown: {remaining}s remaining (relay still sent)")
                on_cooldown = True

        if not on_cooldown:
            try:
                # Get your current status
                status = 'offline'
                for guild in bot.guilds:
                    member = guild.get_member(YOUR_USER_ID)
                    if member and member.status:
                        status = str(member.status)
                        print(f"   📌 Your status: {status} (from {guild.name})")
                        break
                else:
                    print("   ⚠️ Could not find your member object in any guild "
                          "(status defaulting to 'offline').")

                reply = get_reply(status)
                await message.reply(reply)

                cooldowns[message.author.id] = datetime.now() + timedelta(minutes=COOLDOWN_MINUTES)

                print(f"   ✅ Auto-reply sent to {message.author}")
                print(f"   📝 Reply: {reply[:50]}...")

            except discord.Forbidden:
                print(f"   ❌ Cannot send DM to {message.author} (blocked or DMs disabled)")
            except Exception as e:
                print(f"   ❌ Error sending reply: {e}")
                try:
                    await message.reply("Hey! Thanks for your message! I'll get back to you soon! 📨")
                    print(f"   ✅ Fallback reply sent")
                except Exception as fallback_error:
                    print(f"   ❌ Fallback reply also failed: {fallback_error}")

        print("-" * 60)
        return

    # === CASE 2: You were @mentioned in a server ===
    if message.guild is not None and any(u.id == YOUR_USER_ID for u in message.mentions):
        print("-" * 60)
        print(f"🔔 MENTION DETECTED")
        print(f"   From: {message.author} (ID: {message.author.id})")
        print(f"   Server: {message.guild.name} | Channel: #{message.channel}")
        print(f"   Content: {message.content[:100]}")

        # Ignore if the mention is from yourself
        if message.author.id == YOUR_USER_ID:
            print("   ⏭️  Ignoring - mention from yourself")
            print("-" * 60)
            return

        # Relay to owner only — bot does NOT reply in the channel
        log_conversation(message.author.id, "them",
                          f"[in #{message.channel}] {message.content}")
        relayed = await relay_thread_update(message.author.id, str(message.author), "mention")
        if relayed:
            relay_map[relayed.id] = {
                "type": "mention",
                "channel_id": message.channel.id,
                "user_id": message.author.id,
            }

        print("-" * 60)
        return


@bot.event
async def on_error(event, *args, **kwargs):
    """Global error handler"""
    print(f"❌ Error in {event}: {args[0] if args else 'Unknown'}")


@bot.event
async def on_disconnect():
    """Called when bot disconnects"""
    print("⚠️ Disconnected from Discord")


@bot.event
async def on_resumed():
    """Called when bot reconnects"""
    print("✅ Reconnected to Discord")


# Keep alive task for Railway
async def keep_alive():
    """Prevent Railway from killing the bot"""
    await bot.wait_until_ready()
    counter = 0
    while not bot.is_closed():
        try:
            now = datetime.now()
            expired = [uid for uid, expiry in cooldowns.items() if now > expiry]
            for uid in expired:
                del cooldowns[uid]

            counter += 1
            if counter % 2 == 0:
                print(f"💓 Bot is alive | {len(bot.guilds)} servers | {len(bot.users)} users")

        except Exception as e:
            print(f"⚠️ Keep-alive error: {e}")

        await asyncio.sleep(30)


# Run the bot
if __name__ == "__main__":
    print("🚀 Starting bot...")
    try:
        bot.run(TOKEN)
    except discord.LoginFailure:
        print("❌ Login failed! Invalid token")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        sys.exit(1)
