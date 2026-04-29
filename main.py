import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import time

import discord
from discord.ext import commands

from audio import YTDLSource, start_playing, play_next
from config import TOKEN
from state import banned_users, song_queue
from ui import SongSelectionView
from utils import extract_playlist_videos, find_explicit_url, get_spotify_tracks, search_with_ytdlp

LOG_DIR = os.path.join(os.getcwd(), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "bot.log")

root_logger = logging.getLogger()
if not root_logger.handlers:
    root_logger.setLevel(logging.INFO)

    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    stream_handler = logging.StreamHandler()

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    file_handler.setFormatter(formatter)
    stream_handler.setFormatter(formatter)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)

logger = logging.getLogger(__name__)

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)


@bot.check
async def globally_block_banned(ctx):
    if ctx.author.id in banned_users:
        if time.time() < banned_users[ctx.author.id]:
            await ctx.send("You are currently banned from using the bot.", delete_after=5.0)
            return False
        del banned_users[ctx.author.id]
    return True


@bot.command(name='ban', help='Ban a user from using the bot for X minutes (Max 10)')
async def ban(ctx, target: discord.User, duration: int):
    admin_users = [262440154118094851, 276195001547882498]
    owner_id = 262440154118094851

    if ctx.author.id not in admin_users:
        await ctx.send("You don't have permission to use this command.")
        return

    if duration > 10:
        await ctx.send("Maximum ban duration is 10 minutes.")
        return

    if duration <= 0:
        await ctx.send("Duration must be greater than 0.")
        return

    if target.id == owner_id:
        await ctx.send("You cannot ban the bot owner!")
        return

    banned_users[target.id] = time.time() + (duration * 60)
    logger.info("User %s banned %s for %s minute(s)", ctx.author.id, target.id, duration)
    await ctx.send(f"Blocked {target.mention} from using the bot for {duration} minute(s).")


@bot.event
async def on_ready():
    logger.info("Logged in as %s (ID: %s)", bot.user, bot.user.id)
    bot.loop.create_task(admin_terminal_listener())
    try:
        synced = await bot.tree.sync()
        logger.info("Synced %s slash command(s)", len(synced))
    except Exception:
        logger.exception("Failed to sync commands")


async def admin_terminal_listener():
    loop = asyncio.get_running_loop()

    def sync_listen():
        return sys.stdin.readline()

    logger.info("Admin Terminal listener started. Type 'playlocal <filename>' to silently play a song.")
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
                    logger.warning("Terminal playlocal requested while bot is not in a voice channel")
                    continue

                filepath = os.path.join(os.getcwd(), 'songs', filename)
                if not os.path.exists(filepath) and os.path.exists(filename):
                    filepath = filename

                if not os.path.exists(filepath):
                    logger.warning("Terminal playlocal file not found: %s", filepath)
                    continue

                vc = bot.voice_clients[0]
                song_queue.insert(0, {"url": f"local:{filepath}", "user_id": 262440154118094851, "title": f"Local: {filename}"})
                logger.info("Terminal playlocal queued file: %s", filepath)

                if vc.is_playing():
                    vc.stop()
                else:
                    class DummyCtx:
                        def __init__(self, vc, bot):
                            self.voice_client = vc
                            self.bot = bot

                        async def send(self, *args, **kwargs):
                            pass

                    await start_playing(DummyCtx(vc, bot))
            else:
                logger.warning("Unknown terminal command: %s", line)
        except Exception:
            logger.exception("Terminal listener error")


@bot.tree.command(name="playlocal", description="[Admin] Play a downloaded song silently")
@discord.app_commands.describe(filename="The filename of the downloaded song")
async def playlocal_cmd(interaction: discord.Interaction, filename: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Admin only.", ephemeral=True)
        return

    if not interaction.guild.voice_client:
        await interaction.response.send_message("Bot is not in a voice channel.", ephemeral=True)
        return

    filepath = os.path.join(os.getcwd(), 'songs', filename)
    if not os.path.exists(filepath):
        if os.path.exists(filename):
            filepath = filename
        else:
            await interaction.response.send_message(f"File not found: {filename}", ephemeral=True)
            return

    vc = interaction.guild.voice_client
    song_queue.insert(0, {"url": f"local:{filepath}", "user_id": interaction.user.id, "title": f"Local: {filename}"})
    logger.info("Slash playlocal queued file %s by user %s", filepath, interaction.user.id)

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

        await start_playing(DummyCtx(interaction))


@bot.command(name='play', help='Plays a song from YouTube url or search query')
async def play(ctx, *, query=None):
    if not query:
        await ctx.send("Please provide a URL or search query.")
        return

    url = None

    try:
        if query.startswith('http://') or query.startswith('https://'):
            is_playlist = 'list=' in query or 'playlist' in query
            if is_playlist:
                await ctx.send("Processing playlist... this may take a moment.")
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
            await ctx.send(f"Searching for explicit version of: **{query}**...")
            url, is_explicit = await find_explicit_url(query, bot.loop)

            if not url:
                await ctx.send("Could not find a confirmed explicit version using keywords. Searching for top result...")
                results = await bot.loop.run_in_executor(None, lambda: search_with_ytdlp(query, n=1))
                if results:
                    url = results[0].get('webpage_url')
                    await ctx.send(f"Playing top result: **{results[0].get('title')}**")
                else:
                    await ctx.send("Could not find any results.")
                    return
            else:
                await ctx.send("Found explicit version!")

        if not ctx.message.author.voice:
            await ctx.send("You are not connected to a voice channel.")
            return

        if not ctx.voice_client:
            await ctx.message.author.voice.channel.connect()

        voice_client = ctx.voice_client

        if url:
            song_queue.append({"url": url, "user_id": ctx.author.id, "title": query})
            if voice_client.is_playing():
                await ctx.send(f"Added to queue! Position: {len(song_queue)}")

        if not voice_client.is_playing():
            await start_playing(ctx)
    except Exception:
        logger.exception("Error in !play command for query %r", query)
        await ctx.send("Something went wrong while trying to play that track.")


@bot.command(name='search', help='Search for songs and add them interactively')
async def search(ctx, *, query):
    if not ctx.author.voice:
        await ctx.send("You are not connected to a voice channel.")
        return

    await ctx.send(f"Searching for **{query}**...")

    try:
        results = await bot.loop.run_in_executor(None, lambda: search_with_ytdlp(query, n=20))
    except Exception:
        logger.exception("Search command failed for %r", query)
        await ctx.send("Search failed unexpectedly.")
        return

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

    try:
        explicit_search_query = f"{query} explicit"
        candidates = await bot.loop.run_in_executor(None, lambda: search_with_ytdlp(explicit_search_query, n=count * 2))

        selected_songs = []
        explicit_keywords = ['explicit', 'dirty', 'uncensored', 'parental advisory']
        seen_ids = set()

        def get_id(song):
            return song.get('id') or song.get('webpage_url')

        for song in candidates:
            sid = get_id(song)
            if sid in seen_ids:
                continue

            title = song.get('title', '').lower()
            if any(kw in title for kw in explicit_keywords):
                selected_songs.append(song)
                seen_ids.add(sid)

            if len(selected_songs) >= count:
                break

        if len(selected_songs) < count:
            fill_candidates = await bot.loop.run_in_executor(None, lambda: search_with_ytdlp(query, n=count + len(selected_songs)))
            for song in fill_candidates:
                sid = get_id(song)
                if sid in seen_ids:
                    continue

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

        await ctx.send(
            f"Added {len(selected_songs)} songs to queue:\n"
            + "\n".join([f"- {t}" for t in added_titles[:10]])
            + (f"\n...and {len(added_titles) - 10} more" if len(added_titles) > 10 else "")
        )

        if not ctx.voice_client:
            await ctx.author.voice.channel.connect()

        if not ctx.voice_client.is_playing():
            play_next(ctx)
    except Exception:
        logger.exception("Error in !playtop for query %r", query)
        await ctx.send("Something went wrong while building the explicit queue.")


@bot.command(name='skip', help='Skips the current song or resumes playback')
async def skip(ctx):
    try:
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send("Skipping...")
        elif len(song_queue) > 0:
            await ctx.send("Resuming playback...")
            play_next(ctx)
        else:
            await ctx.send("Queue empty.")
    except Exception:
        logger.exception("Error in skip command")
        await ctx.send("Could not skip the current track.")


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
        embed.add_field(
            name=f"!{command.name} {command.signature}",
            value=command.help or "No description provided.",
            inline=False
        )

    await ctx.send(embed=embed)


@bot.command(name='stop', help='Stops music and clears queue')
async def stop(ctx):
    try:
        if ctx.voice_client:
            song_queue.clear()
            ctx.voice_client.stop()
            await ctx.send("Stopped playing and cleared the queue.")
        else:
            await ctx.send("I'm not in a voice channel.")
    except Exception:
        logger.exception("Error in stop command")
        await ctx.send("Could not stop playback cleanly.")


@bot.command(name='queue', help='Shows the current queue')
async def queue(ctx):
    try:
        if len(song_queue) == 0:
            await ctx.send("The queue is empty.")
        else:
            q_list = [f"{i+1}. {item.get('title', item['url'])}" if isinstance(item, dict) else f"{i+1}. {item}" for i, item in enumerate(song_queue)]
            await ctx.send(f"Current Queue:\n" + "\n".join(q_list[:20]) + (f"\n...and {len(q_list)-20} more" if len(q_list) > 20 else ""))
    except Exception:
        logger.exception("Error in queue command")
        await ctx.send("Could not display the queue right now.")


@bot.command(name='playspotify', help='Plays a Spotify playlist, album, or track')
async def playspotify(ctx, url):
    try:
        tracks = get_spotify_tracks(url)
        if not tracks:
            await ctx.send("Could not retrieve Spotify tracks (check credentials or URL).")
            return

        for track in tracks:
            song_queue.append({"url": f"ytsearch:{track}", "user_id": ctx.author.id, "title": track})

        await ctx.send(f"Added {len(tracks)} tracks from Spotify to queue.")

        if not ctx.voice_client:
            if ctx.author.voice:
                await ctx.author.voice.channel.connect()

        if ctx.voice_client and not ctx.voice_client.is_playing():
            await start_playing(ctx)
    except Exception:
        logger.exception("Error in playspotify command for %r", url)
        await ctx.send("Could not process the Spotify link.")


@bot.command(name='clearqueue', help='Clears the song queue (Admin only)')
async def clearqueue(ctx):
    owner_id = 262440154118094851
    admin_2 = 276195001547882498
    clear_admin = 206281653784412160

    try:
        if ctx.author.id not in [owner_id, admin_2, clear_admin]:
            await ctx.send("You don't have permission to use this command.")
            return

        if len(song_queue) == 0:
            await ctx.send("The queue is already empty.")
            return

        if ctx.author.id == owner_id or ctx.author.id == clear_admin:
            cleared_count = len(song_queue)
            song_queue.clear()
            await ctx.send(f"Cleared {cleared_count} songs from the entire queue.")
        elif ctx.author.id == admin_2:
            original_length = len(song_queue)
            new_queue = [
                item for item in song_queue
                if (isinstance(item, dict) and item.get("user_id") == admin_2) or not isinstance(item, dict)
            ]
            cleared_count = original_length - len(new_queue)
            song_queue.clear()
            song_queue.extend(new_queue)
            await ctx.send(f"Cleared {cleared_count} songs from the queue (kept your own songs).")
    except Exception:
        logger.exception("Error in clearqueue command")
        await ctx.send("Could not clear the queue right now.")


if __name__ == "__main__":
    if TOKEN:
        bot.run(TOKEN)
    else:
        logger.error("DISCORD_TOKEN not found in environment variables.")
