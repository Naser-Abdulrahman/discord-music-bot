# Discord Music Bot

A feature-rich Discord music bot built with `discord.py` and `yt-dlp`. Supports YouTube (video, playlists, search) and Spotify (tracks, albums, playlists).

## Features

- Play music from YouTube and Spotify
- Queue system
- Search with interactive buttons
- explicit song filtering (`!playtop`)
- Playlist support

## Setup

1.  **Install Python 3.8+**
2.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
3.  **Install FFmpeg**:
    - Download FFmpeg and place `ffmpeg.exe` and `ffprobe.exe` in the bot folder (or add to system PATH).
    - Note: This bot expects an executable named `audioprocessor.exe` (renamed `ffmpeg.exe`) in the root directory to avoid some detection issues, or you can update the code to use default `ffmpeg`.
4.  **Configure Environment**:
    - Copy `.env.example` to `.env`
    - Add your Discord Bot Token and Spotify Credentials:
        ```env
        DISCORD_TOKEN=your_actual_token_here
        SPOTIPY_CLIENT_ID=...
        SPOTIPY_CLIENT_SECRET=...
        ```

## Usage

- `!play <url>` - Play a song or playlist
- `!search <query>` - Search for a song
- `!skip` - Skip current song
- `!queue` - Show queue
- `!stop` - Stop and disconnect

To run the bot:
```bash
python main.py
```
