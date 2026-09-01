import discord, asyncio, yt_dlp, re, os
from discord.ext import commands
from flask import Flask
from threading import Thread

# --- MINIMAL WEB ENGINE FOR 24/7 CLOUD HOSTING ---
app = Flask('')
@app.route('/')
def home(): return "Bot is Online 24/7!"
def run_web_server(): app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

intents = discord.Intents.all(); bot = commands.Bot(command_prefix="", intents=intents)
music_queues, current_songs, persistent_channels, loop_status, manual_leave = {}, {}, {}, {}, {}

YTDL_OPTIONS = {'format': 'bestaudio/best', 'noplaylist': True, 'nocheckcertificate': True, 'ignoreerrors': False, 'quiet': True, 'default_search': 'auto', 'source_address': '0.0.0.0', 'extract_flat': False, 'skip_download': True}
FFMPEG_OPTIONS = {'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -probesize 1048576 -analyzeduration 5000000', 'options': '-vn -b:a 128k'}
ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, user, volume=1.0):
        super().__init__(source, volume); self.data, self.title, self.user = data, data.get('title', 'Unknown Title'), user
        d_secs = data.get('duration', 0); m, s = divmod(d_secs, 60); self.duration_str = f"{m:02d}:{s:02d}" if d_secs else "03:54"
    @classmethod
    async def from_url(cls, url, *, user):
        data = await bot.loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))
        if 'entries' in data and data['entries']: data = data['entries']
        return cls(discord.FFmpegPCMAudio(data['url'], **FFMPEG_OPTIONS), data=data, user=user)
    @classmethod
    def rebuild_with_timestamp(cls, data, seconds, user):
        opts = FFMPEG_OPTIONS.copy(); opts['before_options'] += f' -ss {seconds}'
        return cls(discord.FFmpegPCMAudio(data['url'], **opts), data=data, user=user)

def play_next(ctx):
    g_id = ctx.guild.id
    if loop_status.get(g_id, False) and g_id in current_songs:
        old = current_songs[g_id]; new = YTDLSource.rebuild_with_timestamp(old.data, 0, old.user); new.volume = old.volume; current_songs[g_id] = new; ctx.voice_client.play(new, after=lambda e: play_next(ctx)); return
    if g_id in music_queues and music_queues[g_id]:
        next_song = music_queues[g_id].pop(0); current_songs[g_id] = next_song; ctx.voice_client.play(next_song, after=lambda e: play_next(ctx))
        asyncio.run_coroutine_threadsafe(ctx.send(embed=create_music_embed(next_song), view=MusicControlView(ctx)), bot.loop)
    else: current_songs.pop(g_id, None)

def create_music_embed(player):
    embed = discord.Embed(color=0x2b2d31); embed.add_field(name="Playing Song", value=f"**[{player.title}](https://youtube.com)**", inline=False); embed.add_field(name="Song Duration", value=f"**{player.duration_str}**", inline=False)
    embed.set_footer(text=player.user.display_name, icon_url=player.user.display_avatar.url); embed.set_thumbnail(url="https://imgur.com"); return embed

class MusicControlView(discord.ui.View):
    def __init__(self, ctx): super().__init__(timeout=None); self.ctx = ctx
    @discord.ui.button(label="🔁", style=discord.ButtonStyle.secondary)
    async def loop_btn(self, i: discord.Interaction, b: discord.ui.Button): g_id = self.ctx.guild.id; loop_status[g_id] = not loop_status.get(g_id, False); await i.response.send_message(f"🔁 Loop: **{'ENABLED' if loop_status[g_id] else 'DISABLED'}**.", delete_after=2)
    @discord.ui.button(label="🔊-", style=discord.ButtonStyle.secondary)
    async def vol_down(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer()
        if self.ctx.guild.id in current_songs: current_songs[self.ctx.guild.id].volume = max(0.0, current_songs[self.ctx.guild.id].volume - 0.2)
    @discord.ui.button(label="⏸️", style=discord.ButtonStyle.secondary)
    async def pr_btn(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer(); vc = self.ctx.voice_client
        if vc and vc.is_playing(): vc.pause()
        elif vc and vc.is_paused(): vc.resume()
    @discord.ui.button(label="🔊+", style=discord.ButtonStyle.secondary)
    async def vol_up(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer()
        if self.ctx.guild.id in current_songs: current_songs[self.ctx.guild.id].volume = min(2.0, current_songs[self.ctx.guild.id].volume + 0.2)
    @discord.ui.button(label="⏭️", style=discord.ButtonStyle.secondary)
    async def skip_btn(self, i: discord.Interaction, b: discord.ui.Button): await i.response.defer(); (self.ctx.voice_client.stop() if self.ctx.voice_client else None)

@bot.event
async def on_ready(): print(f"Logged in successfully as {bot.user.name}")

@bot.event
async def on_voice_state_update(member, before, after):
    guild = member.guild
    vc = guild.voice_client
    if not vc:
        return
    if member.id == bot.user.id and after.channel is None and before.channel is not None:
        if manual_leave.get(guild.id, False): 
            manual_leave[guild.id] = False
            return
        if guild.id in persistent_channels or guild.id in current_songs or guild.id in music_queues:
            target = persistent_channels.get(guild.id, before.channel)
            await asyncio.sleep(0.5)
            try: await target.connect()
            except: pass
        return
    if vc and vc.channel and len([m for m in vc.channel.members if not m.bot]) == 0 and guild.id not in persistent_channels:
        await asyncio.sleep(2)
        if len([m for m in vc.channel.members if not m.bot]) == 0:
            music_queues.pop(guild.id, None); current_songs.pop(guild.id, None); manual_leave[guild.id] = True; await vc.disconnect()


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


    if bot.user.mentioned_in(message) and "come" in message.content.lower():
        if message.author.voice:
            manual_leave[message.guild.id] = False
            if message.guild.voice_client: await message.guild.voice_client.move_to(message.author.voice.channel)
            else: await message.author.voice.channel.connect()
            await message.add_reaction("✅")
        return
    if "setup" in cmd and bot.user.mentioned_in(message):
        if message.author.voice:
            manual_leave[message.guild.id] = False; persistent_channels[message.guild.id] = message.author.voice.channel
            if message.guild.voice_client: await message.guild.voice_client.move_to(message.author.voice.channel)
            else: await message.author.voice.channel.connect()
            await ctx.send(f"🔒 **24/7 Setup Activated** in **{message.author.voice.channel.name}**.")
        return
    if cmd in ["p", "ش"]:
        if not args: return await ctx.send("Type a song name after the command!")
        if not ctx.author.voice: return await ctx.send("Join a voice room first!")
        if not ctx.voice_client: await ctx.author.voice.channel.connect()
        g_id = ctx.guild.id; manual_leave[g_id] = False; music_queues.setdefault(g_id, [])
        try:
            player = await YTDLSource.from_url(args, user=ctx.author)
            if ctx.voice_client.is_playing() or ctx.voice_client.is_paused(): music_queues[g_id].append(player); await ctx.send(f"📋 Added to queue: **{player.title}**")
            else: current_songs[g_id] = player; ctx.voice_client.play(player, after=lambda e: play_next(ctx)); await ctx.send(embed=create_music_embed(player), view=MusicControlView(ctx))
        except Exception as e: await ctx.send(f"Error: {e}")
        return
    if cmd in ["s", "س"]:
        if ctx.voice_client and ctx.voice_client.is_playing(): ctx.voice_client.stop(); await message.add_reaction("⏭️")
        return
    if cmd in ["stop", "pause", "وقف"]:
        if ctx.voice_client and ctx.voice_client.is_playing(): ctx.voice_client.pause(); await message.add_reaction("⏸️")
        return
    if cmd in ["con", "continue", "resume", "كمل"]:
        if ctx.voice_client and ctx.voice_client.is_paused(): ctx.voice_client.resume(); await message.add_reaction("▶️")
        return
    if cmd == "v":
        if ctx.voice_client and ctx.guild.id in current_songs:
            match = re.search(r'\d+', args); vol = int(match.group()) if match else 100
            if 0 <= vol <= 200: current_songs[ctx.guild.id].volume = vol / 100; await message.add_reaction("🔊")
            else: await ctx.send("Volume range must be between 0 and 200.")
        return
    if cmd in ["leave", "خروج"]:
        if ctx.voice_client and ctx.author.voice and ctx.author.voice.channel == ctx.voice_client.channel:
            g_id = ctx.guild.id; music_queues.pop(g_id, None); current_songs.pop(g_id, None); persistent_channels.pop(g_id, None); manual_leave[g_id] = True; await ctx.voice_client.disconnect(); await message.add_reaction("✅")
        return
    await bot.process_commands(message)

@bot.command(name='play_cmd')
async def play(ctx, *, search: str): pass
@bot.command(name='skip_cmd')
async def skip(ctx): pass
@bot.command(name='leave_cmd')
async def leave_cmd(ctx): pass

if __name__ == '__main__':
    Thread(target=run_web_server).start()
    bot.run(os.environ.get("DISCORD_TOKEN"))
