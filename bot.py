import discord
from discord.ext import commands
import os
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv
import random
import asyncio
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)

# Load environment variables
load_dotenv()

# Configuration
TOKEN = os.getenv('DISCORD_TOKEN')
YOUR_USER_ID = int(os.getenv('YOUR_USER_ID')) if os.getenv('YOUR_USER_ID') else None

if not TOKEN:
    print("❌ DISCORD_TOKEN not found")
    sys.exit(1)

if not YOUR_USER_ID:
    print("❌ YOUR_USER_ID not found")
    sys.exit(1)

# Bot configuration
COOLDOWN_MINUTES = 5
ENABLE_LOGGING = True

# DM Reply messages
DM_REPLY_MESSAGES = {
    'online': [
        "Hey! I'm currently online but might be busy. I'll get back to you soon! 👋",
        "Hi! I'm online but AFK at the moment. Will reply when I can! 💻"
    ],
    'idle': [
        "Hey! I'm currently AFK. I'll reply as soon as I'm back! 🕐",
        "Hi! I'm away from my keyboard right now. Will respond when I return! 💤"
    ],
    'dnd': [
        "Hey! I'm currently busy and can't respond. I'll get back to you when I'm free! 📵",
        "Hi! I'm in Do Not Disturb mode. I'll reply as soon as I'm available! 🚫"
    ],
    'offline': [
        "Hey! I'm currently offline. I'll reply when I come back online! 💤",
        "Hi! I'm not online right now. Will respond when I'm back! 🌙"
    ],
    'unknown': "Hey! Thanks for DMing me! I'll get back to you as soon as possible! 📨"
}

cooldowns = {}

# Create bot instance with all required intents
intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True
intents.guilds = True
intents.members = True
intents.presences = True

bot = commands.Bot(command_prefix='!', intents=intents)

def get_random_message(messages):
    if isinstance(messages, list):
        return random.choice(messages)
    return messages

@bot.event
async def on_ready():
    """Called when bot successfully connects to Discord"""
    print("═══════════════════════════════════════════")
    print(f"✅ BOT ONLINE! Logged in as {bot.user.name}")
    print(f"📋 Bot ID: {bot.user.id}")
    print(f"👥 Connected to {len(bot.guilds)} server(s)")
    print(f"📨 Monitoring DMs for user ID: {YOUR_USER_ID}")
    print("═══════════════════════════════════════════")
    
    # Set bot status
    try:
        await bot.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"DMs for {bot.user.name}"
            ),
            status=discord.Status.online
        )
        print("✅ Status updated successfully")
    except Exception as e:
        print(f"⚠️ Could not update status: {e}")

@bot.event
async def on_message(message):
    """Handle incoming messages"""
    # Ignore messages from bots
    if message.author.bot:
        return
    
    # Only handle DMs
    if not isinstance(message.channel, discord.DMChannel):
        return
    
    # Ignore if from yourself
    if message.author.id == YOUR_USER_ID:
        print(f"💬 DM from yourself - ignored")
        return
    
    print(f"📨 DM from: {message.author} | Content: {message.content[:50]}")
    
    # Check cooldown
    if message.author.id in cooldowns:
        if datetime.now() < cooldowns[message.author.id]:
            remaining = int((cooldowns[message.author.id] - datetime.now()).total_seconds())
            print(f"⏳ Cooldown: {remaining}s remaining for {message.author}")
            return
    
    try:
        # Get your current status from any mutual server
        status = 'offline'
        for guild in bot.guilds:
            try:
                member = guild.get_member(YOUR_USER_ID)
                if member and member.status:
                    status = str(member.status)
                    print(f"📍 Found status: {status} from {guild.name}")
                    break
            except:
                continue
        
        # Get reply message based on status
        if status in DM_REPLY_MESSAGES:
            reply = get_random_message(DM_REPLY_MESSAGES[status])
        else:
            reply = DM_REPLY_MESSAGES['unknown']
        
        # Create embed
        embed = discord.Embed(
            title="📩 Auto-Reply",
            description=reply,
            color=(
                discord.Color.green() if status == 'online' else
                discord.Color.gold() if status == 'idle' else
                discord.Color.red() if status == 'dnd' else
                discord.Color.greyple()
            ),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="📌 My Status", value=f"`{status.upper()}`", inline=True)
        embed.add_field(
            name="⏰ Response Time", 
            value=f"<t:{int(datetime.now().timestamp())}:R>", 
            inline=True
        )
        embed.set_footer(
            text=f"Auto-reply by {bot.user.name}",
            icon_url=bot.user.display_avatar.url
        )
        
        # Send reply
        await message.reply(embed=embed)
        
        # Set cooldown (5 minutes)
        cooldowns[message.author.id] = datetime.now() + timedelta(minutes=COOLDOWN_MINUTES)
        print(f"✅ Replied to {message.author}")
        
    except Exception as e:
        print(f"❌ Error processing DM: {e}")
        # Fallback reply
        try:
            await message.reply("Hey! Thanks for your message! I'll get back to you soon! 📨")
        except:
            pass

@bot.event
async def on_error(event, *args, **kwargs):
    """Global error handler"""
    print(f"❌ Error in {event}: {args}")

@bot.event
async def on_disconnect():
    """Called when bot disconnects"""
    print("⚠️ Bot disconnected from Discord")

@bot.event
async def on_resumed():
    """Called when bot reconnects"""
    print("✅ Bot reconnected to Discord")

# Keep bot alive on Railway with a keep-alive task
async def keep_alive():
    """Background task to keep bot responsive"""
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            # Clean expired cooldowns
            now = datetime.now()
            expired = [uid for uid, expiry in cooldowns.items() if now > expiry]
            for uid in expired:
                del cooldowns[uid]
            if expired:
                print(f"🧹 Cleaned {len(expired)} expired cooldowns")
            
            # Simple keep-alive ping
            print(f"💓 Bot is alive | {len(bot.guilds)} servers | {len(bot.users)} users")
            
        except Exception as e:
            print(f"⚠️ Keep-alive error: {e}")
        
        await asyncio.sleep(60)  # Wait 1 minute

# Run bot
if __name__ == "__main__":
    try:
        print("🚀 Starting bot...")
        print(f"📝 Token: {TOKEN[:10]}... (length: {len(TOKEN)})")
        print(f"👤 User ID: {YOUR_USER_ID}")
        
        # Start keep-alive task when bot is ready
        @bot.event
        async def on_ready():
            bot.loop.create_task(keep_alive())
        
        bot.run(TOKEN, log_handler=None)
        
    except discord.LoginFailure:
        print("❌ Login failed! Check your token")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Critical error: {e}")
        sys.exit(1)
