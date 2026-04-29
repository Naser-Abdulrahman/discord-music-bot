import asyncio
import glob
import logging
import os
import re
import subprocess

import discord
import yt_dlp

from config import ytdl_format_options
from state import song_queue
from utils import search_with_ytdlp

logger = logging.getLogger(__name__)


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()

        if stream:
            logger.debug("Stream mode requested but not supported; falling back to download mode")

        if url.startswith("local:"):
            filepath = url[len("local:"):]
            try:
                if not os.path.exists(filepath):
                    raise FileNotFoundError(filepath)
                return cls(
                    discord.FFmpegPCMAudio(
                        filepath,
                        executable='audioprocessor.exe',
                        options='-vn -nostdin'
                    ),
                    data={'title': os.path.basename(filepath), 'url': filepath},
                )
            except Exception:
                logger.exception("Failed to create local audio source for %r", filepath)
                raise

        if url.startswith("ytsearch:"):
            search_query = url[len("ytsearch:"):]
            logger.info("Resolving ytsearch query: %s", search_query)
            try:
                results = await loop.run_in_executor(None, lambda: search_with_ytdlp(search_query, n=1))
                if results and results[0].get('webpage_url'):
                    url = results[0]['webpage_url']
                    logger.info("Resolved ytsearch query to %s", url)
                else:
                    raise ValueError(f"No results found for search: {search_query}")
            except Exception:
                logger.exception("Error resolving ytsearch query %r", search_query)
                raise

        songs_dir = os.path.join(os.getcwd(), 'songs')
        os.makedirs(songs_dir, exist_ok=True)
        cache_file = os.path.join(os.getcwd(), 'downloaded_songs.txt')

        def check_cache(cache_url):
            if not os.path.exists(cache_file):
                return None
            with open(cache_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if '|' not in line:
                        continue
                    cached_url, filename = line.strip().split('|', 1)
                    if cached_url == cache_url and os.path.exists(filename):
                        return filename
            return None

        def add_to_cache(cache_url, filename):
            try:
                with open(cache_file, 'a', encoding='utf-8') as f:
                    f.write(f"{cache_url}|{filename}\n")
            except Exception:
                logger.exception("Failed to update cache file for %r", cache_url)

        cached_file = check_cache(url)
        if cached_file:
            logger.info("Using cached file for %s", url)
            return cls(
                discord.FFmpegPCMAudio(
                    cached_file,
                    executable='audioprocessor.exe',
                    options='-vn -nostdin'
                ),
                data={'title': os.path.basename(cached_file), 'url': cached_file},
            )

        def download_with_ytdlp():
            try:
                cmd = f'python -m yt_dlp -f "18" --no-playlist "{url}"'
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    cwd=songs_dir,
                    timeout=120,
                    shell=True
                )

                if result.returncode != 0:
                    error_msg = f"yt-dlp failed (Code {result.returncode}):\nSTDERR: {result.stderr}\nSTDOUT: {result.stdout}"
                    logger.error(error_msg)
                    raise RuntimeError(error_msg)

                video_id_match = re.search(r'(?:v=|/)([a-zA-Z0-9_-]{11})', url)
                if not video_id_match:
                    raise ValueError("Could not extract video ID from URL")

                video_id = video_id_match.group(1)
                pattern = os.path.join(songs_dir, f"*{video_id}*")

                for _ in range(10):
                    files = glob.glob(pattern)
                    files = [f for f in files if not f.endswith('.part')]

                    if files:
                        files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
                        selected_file = files[0]
                        if os.path.getsize(selected_file) > 0:
                            add_to_cache(url, selected_file)
                            return selected_file

                    import time
                    time.sleep(1)

                raise FileNotFoundError("Could not find downloaded file or file is empty")
            except subprocess.TimeoutExpired:
                raise TimeoutError("Download timed out after 120 seconds")

        try:
            filename = await loop.run_in_executor(None, download_with_ytdlp)
        except Exception:
            logger.exception("Failed to download audio for %s", url)
            raise

        return cls(
            discord.FFmpegPCMAudio(
                filename,
                executable='audioprocessor.exe',
                options='-vn -nostdin'
            ),
            data={'title': os.path.basename(filename), 'url': filename},
        )


async def start_playing(ctx):
    """Start playback from the queue for the current context."""
    if len(song_queue) > 0:
        next_item = song_queue.pop(0)
        next_url = next_item['url'] if isinstance(next_item, dict) else next_item
        try:
            player = await YTDLSource.from_url(next_url, loop=ctx.bot.loop, stream=False)

            def after_playing(error):
                if error:
                    logger.error("Player error: %s", error)
                play_next(ctx)

            ctx.voice_client.play(player, after=after_playing)
            await ctx.send(f'Now playing: **{player.title}**')
        except Exception as e:
            logger.exception("Error playing next song: %s", next_url)
            await ctx.send(f"Error playing song, skipping to next... ({e})")
            await start_playing(ctx)
    else:
        await ctx.send("The queue is empty.")


def play_next(ctx):
    if len(song_queue) > 0:
        next_item = song_queue.pop(0)
        next_url = next_item['url'] if isinstance(next_item, dict) else next_item

        loop = ctx.bot.loop

        coro = YTDLSource.from_url(next_url, loop=loop, stream=False)
        future = asyncio.run_coroutine_threadsafe(coro, loop)

        try:
            player = future.result()

            def after_playing(error):
                if error:
                    logger.error("Player error: %s", error)
                play_next(ctx)

            ctx.voice_client.play(player, after=after_playing)
            asyncio.run_coroutine_threadsafe(ctx.send(f'Now playing: **{player.title}**'), loop)
        except Exception:
            logger.exception("Error playing next song: %s", next_url)
            play_next(ctx)
            asyncio.run_coroutine_threadsafe(ctx.send("Error playing song, skipping to next..."), loop)
    else:
        loop = ctx.bot.loop
        asyncio.run_coroutine_threadsafe(ctx.send("The queue is empty."), loop)
