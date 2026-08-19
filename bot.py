import discord
from discord.ext import commands
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
import random
import asyncio

# Load environment variables
load_dotenv()

# Configuration
TOKEN = os.getenv('DISCORD_TOKEN')
YOUR_USER_ID = int(os.getenv('YOUR_USER_ID'))  # Your Discord User ID

if not TOKEN:
    print("❌ DISCORD_TOKEN not found in .env file")
    exit(1)

# Bot configuration
COOLDOWN_MINUTES = 5
ENABLE_LOGGING = True

# DM Reply messages based on your status
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

# Cooldown dictionary
cooldowns = {}

# Create bot instance
intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True
intents.guilds = True
intents.members = True
intents.presences = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Helper function
def get_random_message(messages):
    if isinstance(messages, list):
        return random.choice(messages)
    return messages

@bot.event
async def on_ready():
    print("═══════════════════════════════════════════")
    print(f"✅ BOT ONLINE: {bot.user.name}")
    print(f"📨 Monitoring DMs for: {bot.user.name}")
    print(f"👥 In {len(bot.guilds)} server(s)")
    print("═══════════════════════════════════════════")
    
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name=f"DMs for {bot.user.name}"
        )
    )

@bot.event
async def on_message(message):
    # Ignore bots
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
            print(f"⏳ Cooldown active for {message.author}")
            return
    
    try:
        # Get your status from any mutual server
        status = 'unknown'
        for guild in bot.guilds:
            member = guild.get_member(YOUR_USER_ID)
            if member and member.status:
                status = str(member.status)
                break
        
        # Get reply message based on status
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
        
        # Set cooldown (5 minutes)
        cooldowns[message.author.id] = datetime.now() + timedelta(minutes=COOLDOWN_MINUTES)
        print(f"✅ Replied to {message.author}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        await message.reply("Hey! Thanks for your message! I'll get back to you soon! 📨")

# Clean expired cooldowns
async def clean_cooldowns():
    await bot.wait_until_ready()
    while not bot.is_closed():
        now = datetime.now()
        expired = [uid for uid, expiry in cooldowns.items() if now > expiry]
        for uid in expired:
            del cooldowns[uid]
        await asyncio.sleep(60)

@bot.event
async def on_ready():
    bot.loop.create_task(clean_cooldowns())

# Run the bot
if __name__ == "__main__":
    bot.run(TOKEN)