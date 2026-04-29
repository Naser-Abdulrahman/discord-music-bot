import discord
from discord.ext import commands
import asyncio
from config import TOKEN
from state import song_queue
from audio import YTDLSource, start_playing
from utils import extract_playlist_videos, find_explicit_url, search_with_ytdlp
from ui import SongSelectionView

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

@bot.check
async def globally_block_banned(ctx):
    import time
    from state import banned_users
    
    if ctx.author.id in banned_users:
        if time.time() < banned_users[ctx.author.id]:
            await ctx.send("You are currently banned from using the bot.", delete_after=5.0)
            return False
        else:
            del banned_users[ctx.author.id]
    return True

@bot.command(name='ban', help='Ban a user from using the bot for X minutes (Max 10)')
async def ban(ctx, target: discord.User, duration: int):
    ADMIN_USERS = [262440154118094851, 276195001547882498]
    OWNER_ID = 262440154118094851
    
    if ctx.author.id not in ADMIN_USERS:
        return
        
    if duration > 10:
        await ctx.send("Maximum ban duration is 10 minutes.")
        return
        
    if duration <= 0:
        await ctx.send("Duration must be greater than 0.")
        return
        
    if target.id == OWNER_ID:
        await ctx.send("You cannot ban the bot owner!")
        return
        
    import time
    from state import banned_users
    
    banned_users[target.id] = time.time() + (duration * 60)
    await ctx.send(f"Blocked {target.mention} from using the bot for {duration} minute(s).")

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    print('------')
    bot.loop.create_task(admin_terminal_listener())
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

async def admin_terminal_listener():
    import sys
    import os
    loop = asyncio.get_running_loop()
    def sync_listen():
        return sys.stdin.readline()
        
    print("Admin Terminal listener started. Type 'playlocal <filename>' to silently play a song.")
    while True:
        try:
            line = await loop.run_in_executor(None, sync_listen)
            if not line:
                break
            line = line.strip()
            if line.startswith("playlocal ") or line.startswith("/playlocal "):
                prefix_len = len("/playlocal ") if line.startswith("/") else len("playlocal ")
                filename = line[prefix_len:].strip()
                if not bot.voice_clients:
                    print("[Terminal] Error: Bot is not connected to a voice channel.")
                    continue
                
                filepath = os.path.join(os.getcwd(), 'songs', filename)
                if not os.path.exists(filepath) and os.path.exists(filename):
                    filepath = filename
                    
                if not os.path.exists(filepath):
                    print(f"[Terminal] Error: File not found ({filepath})")
                    continue
                    
                vc = bot.voice_clients[0]
                song_queue.insert(0, {"url": f"local:{filepath}", "user_id": 262440154118094851, "title": f"Local: {filename}"})
                
                print(f"[Terminal] Playing locally: {filepath}")
                if vc.is_playing():
                    vc.stop()
                else:
                    class DummyCtx:
                        def __init__(self, vc, bot):
                            self.voice_client = vc
                            self.bot = bot
                        async def send(self, *args, **kwargs):
                            pass
                            
                    from audio import start_playing
                    await start_playing(DummyCtx(vc, bot))
            else:
                print(f"[Terminal] Unknown command or invalid format. Type 'playlocal <filename>'")
        except Exception as e:
            print(f"[Terminal] Listener Error: {e}")

@bot.tree.command(name="playlocal", description="[Admin] Play a downloaded song silently")
@discord.app_commands.describe(filename="The filename of the downloaded song")
async def playlocal_cmd(interaction: discord.Interaction, filename: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return
        
    if not interaction.guild.voice_client:
        await interaction.response.send_message("Bot is not in a voice channel.", ephemeral=True)
        return
        
    import os
    filepath = os.path.join(os.getcwd(), 'songs', filename)
    if not os.path.exists(filepath):
        if os.path.exists(filename):
            filepath = filename
        else:
            await interaction.response.send_message(f"File not found: {filename}", ephemeral=True)
            return

    vc = interaction.guild.voice_client
    song_queue.insert(0, {"url": f"local:{filepath}", "user_id": interaction.user.id, "title": f"Local: {filename}"})
    
    await interaction.response.send_message(f"Silently playing locally: {filename}", ephemeral=True)
    
    if vc.is_playing():
        vc.stop()
    else:
        class DummyCtx:
            def __init__(self, interaction):
                self.voice_client = interaction.guild.voice_client
                self.bot = interaction.client
            async def send(self, *args, **kwargs):
                pass
                
        from audio import start_playing
        await start_playing(DummyCtx(interaction))

@bot.command(name='play', help='Plays a song from YouTube url or search query')
async def play(ctx, *, query=None):
    if not query:
        await ctx.send("Please provide a URL or search query.")
        return

    # Check if query is a URL
    if query.startswith('http://') or query.startswith('https://'):
        is_playlist = 'list=' in query or 'playlist' in query
        if is_playlist:
            await ctx.send(f"Processing playlist... this may take a moment.")
            playlist_entries = await bot.loop.run_in_executor(None, lambda: extract_playlist_videos(query))
            
            if playlist_entries:
                if len(playlist_entries) > 35:
                     await ctx.send(f"Playlist is too long! Max 35 songs allowed. Found {len(playlist_entries)}.")
                     return
                added_count = 0
                for entry in playlist_entries:
                    video_url = entry.get('url')
                    if video_url and not video_url.startswith('http'):
                        video_url = f"https://www.youtube.com/watch?v={video_url}"
                        
                    if video_url:
                        song_queue.append({"url": video_url, "user_id": ctx.author.id, "title": entry.get('title', 'Unknown')})
                        added_count += 1
                
                await ctx.send(f"Added {added_count} songs from playlist to queue.")
                url = None
            else:
                 await ctx.send("Could not extract songs from playlist. Trying as single video...")
                 url = query
        else:
            url = query
    else:
        # It's a search query
        await ctx.send(f"Searching for explicit version of: **{query}**...")
        
        url, is_explicit = await find_explicit_url(query, bot.loop)
        
        if not url:
            # Fallback to standard search
            await ctx.send("Could not find a confirmed explicit version using keywords. Searching for top result...")
            results = await bot.loop.run_in_executor(None, lambda: search_with_ytdlp(query, n=1))
            if results:
                url = results[0].get('webpage_url')
                await ctx.send(f"Playing top result: **{results[0].get('title')}**")
            else:
                await ctx.send("Could not find any results.")
                return
        else:
            await ctx.send(f"Found explicit version!")

    # 1. Check if user is in a voice channel
    if not ctx.message.author.voice:
        await ctx.send("You are not connected to a voice channel.")
        return

    # 2. Connect to the channel if not already connected
    if not ctx.voice_client:
        await ctx.message.author.voice.channel.connect()

    # 3. Add to queue logic
    voice_client = ctx.voice_client

    if url:
        if voice_client.is_playing():
             song_queue.append({"url": url, "user_id": ctx.author.id, "title": query})
             await ctx.send(f"Added to queue! Position: {len(song_queue)}")
        else:
             song_queue.append({"url": url, "user_id": ctx.author.id, "title": query})
             
    # Start playback if not playing
    if not voice_client.is_playing():
        try:
             # Trigger playback via shared logic
             await start_playing(ctx)
        except Exception as e:
            await ctx.send(f"Error starting playback: {e}")

@bot.command(name='search', help='Search for songs and add them interactively')
async def search(ctx, *, query):
    if not ctx.author.voice:
        await ctx.send("You are not connected to a voice channel.")
        return
        
    await ctx.send(f"Searching for **{query}**...")
    
    results = await bot.loop.run_in_executor(None, lambda: search_with_ytdlp(query, n=20))
    
    if not results:
        await ctx.send("No results found.")
        return
        
    view = SongSelectionView(ctx, results)
    
    batch = results[:5]
    desc = ""
    for i, song in enumerate(batch):
        desc += f"**{i+1}.** {song.get('title')}\n"
        
    view.message = await ctx.send(f"**Search Results (Page 1):**\n{desc}", view=view)

@bot.command(name='playtop', help='Plays the top <count> explicit songs for a query (fills with non-explicit if needed)')
async def playtop(ctx, count: int, *, query):
    if count < 1:
        await ctx.send("Count must be at least 1.")
        return
    if count > 20:
        await ctx.send("Max count is 20.")
        return
        
    if not ctx.author.voice:
        await ctx.send("You are not connected to a voice channel.")
        return

    await ctx.send(f"Searching for top {count} songs for **{query}** (prioritizing explicit)...")
    
    explicit_search_query = f"{query} explicit"
    candidates = await bot.loop.run_in_executor(None, lambda: search_with_ytdlp(explicit_search_query, n=count*2))
    
    selected_songs = []
    explicit_keywords = ['explicit', 'dirty', 'uncensored', 'parental advisory']
    seen_ids = set()
    
    def get_id(song):
        return song.get('id') or song.get('webpage_url')

    for song in candidates:
        sid = get_id(song)
        if sid in seen_ids: continue
        
        title = song.get('title', '').lower()
        if any(kw in title for kw in explicit_keywords):
            selected_songs.append(song)
            seen_ids.add(sid)
            
        if len(selected_songs) >= count:
            break
            
    if len(selected_songs) < count:
        remaining = count - len(selected_songs)
        fill_candidates = await bot.loop.run_in_executor(None, lambda: search_with_ytdlp(query, n=count + len(selected_songs)))
        
        for song in fill_candidates:
            sid = get_id(song)
            if sid in seen_ids: continue
            
            selected_songs.append(song)
            seen_ids.add(sid)
            
            if len(selected_songs) >= count:
                break
                
    if not selected_songs:
        await ctx.send("No songs found.")
        return
        
    added_titles = []
    for song in selected_songs:
        url = song.get('webpage_url') or song.get('url')
        title = song.get('title')
        song_queue.append({"url": url, "user_id": ctx.author.id, "title": title})
        added_titles.append(title)
        
    await ctx.send(f"Added {len(selected_songs)} songs to queue:\n" + "\n".join([f"- {t}" for t in added_titles[:10]]) + (f"\n...and {len(added_titles)-10} more" if len(added_titles) > 10 else ""))
    
    if not ctx.voice_client:
         await ctx.author.voice.channel.connect()
         
    if not ctx.voice_client.is_playing():
        try:
             play_next(ctx)
             # Note: play_next sends "Now playing" message
        except Exception as e:
             await ctx.send(f"Error starting playback: {e}")

@bot.command(name='skip', help='Skips the current song or resumes playback')
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("Skipping...")
    elif len(song_queue) > 0:
        await ctx.send("Resuming playback...")
        play_next(ctx)
    else:
        await ctx.send("Queue empty.")

@bot.command(name='help', help='Shows this message')
async def help(ctx):
    embed = discord.Embed(
        title="Music Bot Commands",
        description="Here are the available commands:",
        color=discord.Color.blue()
    )
    
    sorted_commands = sorted(bot.commands, key=lambda c: c.name)
    
    for command in sorted_commands:
        if command.hidden:
            continue
        signature = command.signature
        name = command.name
        help_text = command.help or "No description provided."
        
        embed.add_field(
            name=f"!{name} {signature}",
            value=help_text,
            inline=False
        )
        
    await ctx.send(embed=embed)

@bot.command(name='stop', help='Stops music and clears queue')
async def stop(ctx):
    if ctx.voice_client:
        song_queue.clear()
        ctx.voice_client.stop()
        await ctx.send("Stopped playing and cleared the queue.")
    else:
        await ctx.send("I'm not in a voice channel.")

@bot.command(name='queue', help='Shows the current queue')
async def queue(ctx):
    if len(song_queue) == 0:
        await ctx.send("The queue is empty.")
    else:
        q_list = [f"{i+1}. {item.get('title', item['url'])}" if isinstance(item, dict) else f"{i+1}. {item}" for i, item in enumerate(song_queue)]
        await ctx.send(f"Current Queue:\n" + "\n".join(q_list[:20]) + (f"\n...and {len(q_list)-20} more" if len(q_list) > 20 else ""))

@bot.command(name='playspotify', help='Plays a Spotify playlist, album, or track')
async def playspotify(ctx, url):
    # This was previously incomplete/stubbed in main.py, leaving it out or unimplemented for now?
    # The original main.py had get_spotify_tracks helper but play_spotify command seemed cut off in view.
    # I'll include the command stub but note it needs implementation if it wasn't fully there.
    # Actually I moved get_spotify_tracks to utils. Let's use it.
    from utils import get_spotify_tracks
    
    tracks = get_spotify_tracks(url)
    if not tracks:
        await ctx.send("Could not retrieve Spotify tracks (check credentials or URL).")
        return
        
    for track in tracks:
        # YTDLSource.from_url expects a URL or search term?
        # yt-dlp supports "ytsearch:..."
        song_queue.append({"url": f"ytsearch:{track}", "user_id": ctx.author.id, "title": track})
        
    await ctx.send(f"Added {len(tracks)} tracks from Spotify to queue.")
    
    if not ctx.voice_client:
         if ctx.author.voice:
             await ctx.author.voice.channel.connect()
    
    if ctx.voice_client and not ctx.voice_client.is_playing():
        await start_playing(ctx)

@bot.command(name='clearqueue', help='Clears the song queue (Admin only)')
async def clearqueue(ctx):
    OWNER_ID = 262440154118094851
    ADMIN_2 = 276195001547882498
    CLEAR_ADMIN = 206281653784412160
    
    if ctx.author.id not in [OWNER_ID, ADMIN_2, CLEAR_ADMIN]:
        await ctx.send("You don't have permission to use this command.")
        return
        
    if len(song_queue) == 0:
        await ctx.send("The queue is already empty.")
        return
        
    if ctx.author.id == OWNER_ID or ctx.author.id == CLEAR_ADMIN:
        cleared_count = len(song_queue)
        song_queue.clear()
        await ctx.send(f"Cleared {cleared_count} songs from the entire queue.")
    elif ctx.author.id == ADMIN_2:
        original_length = len(song_queue)
        new_queue = [
            item for item in song_queue 
            if (isinstance(item, dict) and item.get("user_id") == ADMIN_2) or not isinstance(item, dict)
        ]
        cleared_count = original_length - len(new_queue)
        song_queue.clear()
        song_queue.extend(new_queue)
        await ctx.send(f"Cleared {cleared_count} songs from the queue (kept your own songs).")

if __name__ == "__main__":
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("Error: DISCORD_TOKEN not found in environment variables.")