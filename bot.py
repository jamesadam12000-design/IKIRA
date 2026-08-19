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
print("🤖 DISCORD DM AUTO-REPLY BOT")
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
COOLDOWN_MINUTES = 5
cooldowns = {}

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


# === SINGLE on_ready HANDLER ===
# NOTE: discord.py only keeps the LAST @bot.event handler registered for a
# given event name. The original file defined on_ready() twice, so the
# first definition (server list / membership check / presence) was silently
# overwritten and never ran. Everything is now merged into one handler.
@bot.event
async def on_ready():
    """Called when bot connects to Discord"""
    print("=" * 60)
    print(f"✅ BOT ONLINE SUCCESSFULLY!")
    print(f"📋 Bot Name: {bot.user.name}")
    print(f"📋 Bot ID: {bot.user.id}")
    print(f"👥 Connected to {len(bot.guilds)} server(s)")
    print("-" * 60)

    # List all servers and check if you're in them
    for guild in bot.guilds:
        print(f"📁 Server: {guild.name} (ID: {guild.id})")
        try:
            member = guild.get_member(YOUR_USER_ID)
            if member:
                print(f"   ✅ YOU are in this server! Status: {member.status}")
            else:
                print(f"   ⚠️ You are NOT in this server (bot can't DM you here)")
        except Exception as e:
            print(f"   ⚠️ Could not check membership: {e}")

    print("=" * 60)
    print("📨 Bot is now MONITORING for DMs...")
    print("💡 Test: Have a friend DM your Discord account!")
    print("⚠️  Note: Bot will NOT reply to your own DMs")
    print("=" * 60)

    # Set bot status
    try:
        await bot.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="for DMs"
            )
        )
    except Exception as e:
        print(f"⚠️ Could not set presence: {e}")

    # Start keep-alive loop (only once, guard against on_ready firing
    # multiple times on reconnects)
    if not getattr(bot, "_keep_alive_started", False):
        bot._keep_alive_started = True
        bot.loop.create_task(keep_alive())


@bot.event
async def on_message(message):
    """Handle all incoming messages"""

    # Ignore messages from bots
    if message.author.bot:
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

    # === HANDLE DMs ONLY ===
    if not isinstance(message.channel, discord.DMChannel):
        return

    # Log the DM
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

    # Check cooldown
    if message.author.id in cooldowns:
        if datetime.now() < cooldowns[message.author.id]:
            remaining = int((cooldowns[message.author.id] - datetime.now()).total_seconds())
            print(f"   ⏳ Cooldown: {remaining}s remaining")
            print("-" * 60)
            return

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
                  "(status defaulting to 'offline'). Check that the bot "
                  "shares a server with you and that the 'members' "
                  "privileged intent is enabled in the Developer Portal.")

        # Get reply message
        reply = get_reply(status)

        # Send the reply
        await message.reply(reply)

        # Set cooldown
        cooldowns[message.author.id] = datetime.now() + timedelta(minutes=COOLDOWN_MINUTES)

        print(f"   ✅ Auto-reply sent to {message.author}")
        print(f"   📝 Reply: {reply[:50]}...")

    except discord.Forbidden:
        print(f"   ❌ Cannot send DM to {message.author} (blocked or DMs disabled)")
    except Exception as e:
        print(f"   ❌ Error sending reply: {e}")
        # Try fallback
        try:
            await message.reply("Hey! Thanks for your message! I'll get back to you soon! 📨")
            print(f"   ✅ Fallback reply sent")
        except Exception as fallback_error:
            print(f"   ❌ Fallback reply also failed: {fallback_error}")

    print("-" * 60)


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
            # Clean expired cooldowns
            now = datetime.now()
            expired = [uid for uid, expiry in cooldowns.items() if now > expiry]
            for uid in expired:
                del cooldowns[uid]

            # Log heartbeat every minute
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
