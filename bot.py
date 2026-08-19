import discord
import os
import sys
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
import random

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

print(f"📝 Token loaded: {TOKEN[:10]}...")
print(f"👤 User ID: {YOUR_USER_ID}")

# Bot configuration
COOLDOWN_MINUTES = 5

# Reply messages
DM_REPLY_MESSAGES = {
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
    ],
    'unknown': "Hey! Thanks for DMing me! I'll get back to you as soon as possible! 📨"
}

cooldowns = {}

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True
intents.guilds = True
intents.members = True
intents.presences = True

bot = discord.Client(intents=intents)

def get_random_message(messages):
    if isinstance(messages, list):
        return random.choice(messages)
    return messages

@bot.event
async def on_ready():
    """Called when bot successfully connects"""
    print("═══════════════════════════════════════════")
    print(f"✅ BOT ONLINE! Logged in as {bot.user.name}")
    print(f"📋 Bot ID: {bot.user.id}")
    print(f"👥 Connected to {len(bot.guilds)} server(s)")
    print(f"📨 Monitoring DMs for user ID: {YOUR_USER_ID}")
    print("═══════════════════════════════════════════")
    
    # Set status
    try:
        await bot.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"DMs for {bot.user.name}"
            )
        )
        print("✅ Status updated")
    except Exception as e:
        print(f"⚠️ Status update error: {e}")

@bot.event
async def on_message(message):
    """Handle incoming messages"""
    # Ignore bots
    if message.author.bot:
        return
    
    # Only handle DMs
    if not isinstance(message.channel, discord.DMChannel):
        return
    
    # Ignore if from yourself
    if message.author.id == YOUR_USER_ID:
        return
    
    print(f"📨 DM from: {message.author} | Content: {message.content[:50]}")
    
    # Check cooldown
    if message.author.id in cooldowns:
        if datetime.now() < cooldowns[message.author.id]:
            remaining = int((cooldowns[message.author.id] - datetime.now()).total_seconds())
            print(f"⏳ Cooldown: {remaining}s remaining")
            return
    
    try:
        # Get your status
        status = 'offline'
        for guild in bot.guilds:
            member = guild.get_member(YOUR_USER_ID)
            if member and member.status:
                status = str(member.status)
                break
        
        # Get reply
        if status in DM_REPLY_MESSAGES:
            reply = get_random_message(DM_REPLY_MESSAGES[status])
        else:
            reply = DM_REPLY_MESSAGES['unknown']
        
        # Send reply
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
        embed.set_footer(text=f"Auto-reply by {bot.user.name}")
        
        await message.reply(embed=embed)
        cooldowns[message.author.id] = datetime.now() + timedelta(minutes=COOLDOWN_MINUTES)
        print(f"✅ Replied to {message.author}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        try:
            await message.reply("Hey! Thanks for your message! I'll get back to you soon! 📨")
        except:
            pass

@bot.event
async def on_error(event, *args, **kwargs):
    print(f"❌ Error in {event}")

@bot.event
async def on_disconnect():
    print("⚠️ Disconnected from Discord")

@bot.event
async def on_resumed():
    print("✅ Reconnected to Discord")

# Keep bot alive on Railway
async def keep_alive():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            # Clean expired cooldowns
            now = datetime.now()
            expired = [uid for uid, expiry in cooldowns.items() if now > expiry]
            for uid in expired:
                del cooldowns[uid]
            
            # Log heartbeat
            print(f"💓 Bot is alive | {len(bot.guilds)} servers | {len(bot.users)} users")
            
        except Exception as e:
            print(f"⚠️ Keep-alive error: {e}")
        
        await asyncio.sleep(60)

@bot.event
async def on_ready():
    bot.loop.create_task(keep_alive())

# Run the bot
if __name__ == "__main__":
    try:
        print("🚀 Starting bot...")
        bot.run(TOKEN, log_level=20)  # log_level=20 = INFO
    except discord.LoginFailure:
        print("❌ Login failed! Check your token")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
