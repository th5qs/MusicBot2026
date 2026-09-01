import discord
import asyncio
import yt_dlp
import re
import os
from discord.ext import commands
from aiohttp import web

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="", intents=intents)

music_queues = {}
current_songs = {}

YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'quiet': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'skip_download': True
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -probesize 1048576 -analyzeduration 5000000',
    'options': '-vn -b:a 128k'
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, user, volume=1.0):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title', 'Unknown Title')
        self.user = user
        d_secs = data.get('duration', 0)
        m, s = divmod(d_secs, 60)
        self.duration_str = f"{m:02d}:{s:02d}" if d_secs else "03:54"

    @classmethod
    async def from_url(cls, url, *, user):
        data = await bot.loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))
        if isinstance(data, dict) and 'entries' in data and data['entries']:
            data = data['entries'][0]
        elif isinstance(data, list) and data:
            data = data[0]
        return cls(discord.FFmpegPCMAudio(data['url'], **FFMPEG_OPTIONS), data=data, user=user)

def play_next(ctx):
    g_id = ctx.guild.id
    if g_id in music_queues and music_queues[g_id]:
        next_song = music_queues[g_id].pop(0)
        current_songs[g_id] = next_song
        ctx.voice_client.play(next_song, after=lambda e: play_next(ctx))
        asyncio.run_coroutine_threadsafe(ctx.send(embed=create_music_embed(next_song), view=MusicControlView(ctx)), bot.loop)
    else:
        current_songs.pop(g_id, None)

def create_music_embed(player):
    embed = discord.Embed(color=0x2b2d31)
    embed.add_field(name="Playing Song", value=f"**[{player.title}](https://youtube.com)**", inline=False)
    embed.add_field(name="Song Duration", value=f"**{player.duration_str}**", inline=False)
    embed.set_footer(text=player.user.display_name, icon_url=player.user.display_avatar.url)
    return embed

class MusicControlView(discord.ui.View):
    def __init__(self, ctx):
        super().__init__(timeout=None)
        self.ctx = ctx

    @discord.ui.button(label="🔊-", style=discord.ButtonStyle.secondary)
    async def vol_down(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer()
        if self.ctx.guild.id in current_songs:
            current_songs[self.ctx.guild.id].volume = max(0.0, current_songs[self.ctx.guild.id].volume - 0.2)

    @discord.ui.button(label="⏸️", style=discord.ButtonStyle.secondary)
    async def pr_btn(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer()
        vc = self.ctx.voice_client
        if vc and vc.is_playing(): vc.pause()
        elif vc and vc.is_paused(): vc.resume()

    @discord.ui.button(label="🔊+", style=discord.ButtonStyle.secondary)
    async def vol_up(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer()
        if self.ctx.guild.id in current_songs:
            current_songs[self.ctx.guild.id].volume = min(2.0, current_songs[self.ctx.guild.id].volume + 0.2)

    @discord.ui.button(label="⏭️", style=discord.ButtonStyle.secondary)
    async def skip_btn(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer()
        if self.ctx.voice_client: self.ctx.voice_client.stop()

@bot.event
async def on_ready():
    print(f"========================================")
    print(f"SUCCESS: {bot.user.name} IS NOW ONLINE!")
    print(f"========================================")

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    parts = message.content.strip().split(maxsplit=1)
    if not parts:
        return
        
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""
    ctx = await bot.get_context(message)
    g_id = message.guild.id
    msg_clean = message.content.strip().lower()
    
    # --- COME COMMAND ---
    if (bot.user.mentioned_in(message) or "bot" in msg_clean) and "come" in msg_clean:
        if message.author.voice:
            try:
                if message.guild.voice_client: 
                    await message.guild.voice_client.move_to(message.author.voice.channel)
                else: 
                    await message.author.voice.channel.connect(reconnect=True, timeout=15.0)
                await message.add_reaction("✅")
            except Exception as e:
                await ctx.send(f"Connection failed: {e}")
        return

    # --- PLAY COMMAND (p / ش) ---
    if cmd in ["p", "ش"]:
        if not args: return await ctx.send("Type a song name after the command!")
        if not ctx.author.voice: return await ctx.send("Join a voice room first!")
        if not ctx.voice_client or not ctx.voice_client.is_connected():
            try:
                await ctx.author.voice.channel.connect(reconnect=True, timeout=15.0)
            except Exception as e:
                return await ctx.send(f"Failed to join voice channel: {e}")
        music_queues.setdefault(g_id, [])
        try:
            player = await YTDLSource.from_url(args, user=ctx.author)
            if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
                music_queues[g_id].append(player)
                await ctx.send(f"📋 Added to queue: **{player.title}**")
            else:
                current_songs[g_id] = player
                ctx.voice_client.play(player, after=lambda e: play_next(ctx))
                await ctx.send(embed=create_music_embed(player), view=MusicControlView(ctx))
        except Exception as e: await ctx.send(f"Error: {e}")
        return

    # --- SKIP COMMAND (s / س) ---
    if cmd in ["s", "س"]:
        if ctx.voice_client and ctx.voice_client.is_playing(): 
            ctx.voice_client.stop()
            await message.add_reaction("⏭️")
        return

    # --- PAUSE COMMAND (stop / pause / وقف) ---
    if cmd in ["stop", "pause", "وقف"]:
        if ctx.voice_client and ctx.voice_client.is_playing(): 
            ctx.voice_client.pause()
            await message.add_reaction("⏸️")
        return

    # --- RESUME COMMAND (con / resume / كمل) ---
    if cmd in ["con", "continue", "resume", "كمل"]:
        if ctx.voice_client and ctx.voice_client.is_paused(): 
            ctx.voice_client.resume()
            await message.add_reaction("▶️")
        return

    # --- LEAVE COMMAND (leave / خروج) ---
    if cmd in ["leave", "خروج"]:
        if ctx.voice_client:
            music_queues.pop(g_id, None)
            current_songs.pop(g_id, None)
            await ctx.voice_client.disconnect()
            await message.add_reaction("✅")
        return

    await bot.process_commands(message)

async def handle_ping(request):
    return web.Response(text="Bot is running!")

async def main():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

    token = os.environ.get("DISCORD_TOKEN")
    if token:
        await bot.start(token)

if __name__ == '__main__':
    asyncio.run(main())