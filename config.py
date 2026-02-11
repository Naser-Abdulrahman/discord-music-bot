import os
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
TOKEN = os.getenv('DISCORD_TOKEN')

# --- Spotify Configuration ---
SPOTIPY_CLIENT_ID = os.getenv('SPOTIPY_CLIENT_ID')
SPOTIPY_CLIENT_SECRET = os.getenv('SPOTIPY_CLIENT_SECRET')

ytdl_format_options = {
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'extract_flat': False,
    'youtube_include_dash_manifest': True,
    'youtube_include_hls_manifest': True,
    'cookiesfrombrowser': ('chrome',),
}

ffmpeg_options = {
    'options': '-vn -nostdin -report',
}
