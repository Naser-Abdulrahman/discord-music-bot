import discord
import asyncio
import yt_dlp
import os
import subprocess
import glob
from config import ytdl_format_options
from state import song_queue

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
            stream = False
        
        # Download logic embedded here for now
        output_template = "%(extractor)s-%(id)s-%(title)s.%(ext)s"
        songs_dir = os.path.join(os.getcwd(), 'songs')
        os.makedirs(songs_dir, exist_ok=True)
        cache_file = os.path.join(os.getcwd(), 'downloaded_songs.txt')
        
        def check_cache(url):
            if os.path.exists(cache_file):
                with open(cache_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if '|' in line:
                            cached_url, filename = line.strip().split('|', 1)
                            if cached_url == url and os.path.exists(filename):
                                return filename
            return None
        
        def add_to_cache(url, filename):
            with open(cache_file, 'a', encoding='utf-8') as f:
                f.write(f"{url}|{filename}\n")
        
        cached_file = check_cache(url)
        if cached_file:
            return cls(discord.FFmpegPCMAudio(
                cached_file,
                executable='audioprocessor.exe',
                options='-vn -nostdin'
            ), data={'title': os.path.basename(cached_file), 'url': cached_file})
        
        def download_with_ytdlp():
            try:
                cmd = f'yt-dlp.exe -f "18" --no-playlist "{url}"'
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    cwd=songs_dir,
                    timeout=120,
                    shell=True
                )
                
                if result.returncode != 0:
                    raise Exception(f"yt-dlp.exe failed: {result.stderr}")
                
                import re
                import time
                
                video_id_match = re.search(r'(?:v=|/)([a-zA-Z0-9_-]{11})', url)
                if not video_id_match:
                    raise Exception("Could not extract video ID from URL")
                
                video_id = video_id_match.group(1)
                pattern = os.path.join(songs_dir, f"*{video_id}*")
                
                for attempt in range(10):
                    files = glob.glob(pattern)
                    files = [f for f in files if not f.endswith('.part')]
                    
                    if files:
                        files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
                        selected_file = files[0]
                        file_size = os.path.getsize(selected_file)
                        
                        if file_size > 0:
                            add_to_cache(url, selected_file)
                            return selected_file
                    
                    time.sleep(1)
                else:
                    raise Exception("Could not find downloaded file or file is empty")
                
            except subprocess.TimeoutExpired:
                raise Exception("Download timed out after 120 seconds")
        
        filename = await loop.run_in_executor(None, download_with_ytdlp)
        
        return cls(discord.FFmpegPCMAudio(
            filename, 
            executable='audioprocessor.exe', 
            options='-vn -nostdin'
        ), data={'title': os.path.basename(filename), 'url': filename})

def play_next(ctx):
    if len(song_queue) > 0:
        next_url = song_queue.pop(0)
        
        # We access the bot loop via ctx.bot.loop since play_next isn't async
        loop = ctx.bot.loop
        
        coro = YTDLSource.from_url(next_url, loop=loop, stream=False)
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        
        try:
            player = future.result()
            
            def after_playing(error):
                if error:
                    print(f"Player error: {error}")
                play_next(ctx)
                
            ctx.voice_client.play(player, after=after_playing)
            asyncio.run_coroutine_threadsafe(ctx.send(f'Now playing: **{player.title}**'), loop)
        except Exception as e:
            print(f"Error playing next song: {e}")
            play_next(ctx)
            asyncio.run_coroutine_threadsafe(ctx.send(f"Error playing song, skipping to next... ({e})"), loop)
    else:
        loop = ctx.bot.loop
        asyncio.run_coroutine_threadsafe(ctx.send("The queue is empty."), loop)
