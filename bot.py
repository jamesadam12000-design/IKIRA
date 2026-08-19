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


async def relay_to_owner(content: str):
    """Send a message to the bot owner's DMs (from the bot, not as the user).
    Returns the sent Message object (or None on failure) so the caller can
    map it in relay_map for two-way replies."""
    try:
        owner = await bot.fetch_user(YOUR_USER_ID)
        # Discord DMs cap at 2000 chars; trim defensively
        if len(content) > 1900:
            content = content[:1900] + "\n...(truncated)"
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
                    await message.add_reaction("✅")
                    print(f"   ↩️  Owner reply forwarded to {target_user} via DM")
                elif info["type"] == "mention":
                    channel = bot.get_channel(info["channel_id"])
                    if channel:
                        await channel.send(f"<@{info['user_id']}> {message.content}")
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
                await message.add_reaction("✅")
                print(f"   ↩️  Owner quick-reply forwarded to {target_user} via DM")
            except discord.Forbidden:
                await message.reply("❌ Couldn't deliver that — they may have DMs closed or blocked the bot.")
            except Exception as e:
                await message.reply(f"❌ Error forwarding reply: {e}")
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
        relayed = await relay_to_owner(
            f"📨 **New DM from {message.author} ({message.author.id}):**\n{message.content}\n"
            f"-# Reply to this message, or use `!r <text>`, to respond."
        )
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
        relayed = await relay_to_owner(
            f"🔔 **{message.author}** mentioned you in **#{message.channel}** "
            f"({message.guild.name}):\n{message.content}\n"
            f"-# Reply to this message to respond in that channel."
        )
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
