from config import SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import subprocess
import json
import asyncio

def search_with_ytdlp(query, n=5):
    """
    Searches YouTube for the query using yt-dlp.exe and returns list of metadata dicts.
    """
    cmd = [
        'yt-dlp.exe',
        f'ytsearch{n}:{query}',
        '--dump-json',
        '--no-playlist',
        '--quiet',
        '--ignore-errors'
    ]
    
    try:
        # Run in subprocess
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8' # Force utf-8
        )
        
        results = []
        for line in result.stdout.splitlines():
            if line.strip():
                try:
                    data = json.loads(line)
                    results.append(data)
                except json.JSONDecodeError:
                    pass
        return results
    except Exception as e:
        print(f"Search error for '{query}': {e}")
        return []

async def find_explicit_url(query, loop):
    """
    Finds an explicit version of the song.
    """
    # 1. Search for query + " explicit"
    search_query = f"{query} explicit"
    print(f"Searching for explicit version: {search_query}")
    
    results = await loop.run_in_executor(None, lambda: search_with_ytdlp(search_query, n=5))
    
    explicit_keywords = ['explicit', 'dirty', 'uncensored', 'parental advisory']
    
    # Check for explicit keywords in title
    for res in results:
        title = res.get('title', '').lower()
        if any(keyword in title for keyword in explicit_keywords):
            print(f"Found explicit match: {res.get('title')}")
            return res.get('webpage_url'), True
            
    # If no explicit match found, return None
    return None, False

def extract_playlist_videos(url):
    """
    Extracts all video URLs from a playlist using yt-dlp --flat-playlist.
    """
    cmd = [
        'yt-dlp.exe', 
        '--dump-json', 
        '--flat-playlist', 
        '--ignore-errors',
        '--quiet',
        '--no-warnings',
        url
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8'
        )
        
        entries = []
        for line in result.stdout.splitlines():
            if line.strip():
                try:
                    data = json.loads(line)
                    if data.get('url'):
                        entries.append(data)
                except json.JSONDecodeError:
                    pass
        return entries
    except Exception as e:
        print(f"Playlist extraction error: {e}")
        return []

def get_spotify_tracks(url):
    try:
        auth_manager = SpotifyClientCredentials(client_id=SPOTIPY_CLIENT_ID, client_secret=SPOTIPY_CLIENT_SECRET)
        sp = spotipy.Spotify(auth_manager=auth_manager)
        
        tracks = []
        if 'track' in url:
            track = sp.track(url)
            tracks.append(f"{track['artists'][0]['name']} - {track['name']}")
        elif 'playlist' in url:
            results = sp.playlist_tracks(url)
            for item in results['items']:
                track = item['track']
                tracks.append(f"{track['artists'][0]['name']} - {track['name']}")
            while results['next']:
                results = sp.next(results)
                for item in results['items']:
                    track = item['track']
                    tracks.append(f"{track['artists'][0]['name']} - {track['name']}")
        elif 'album' in url:
            results = sp.album_tracks(url)
            for item in results['items']:
                tracks.append(f"{item['artists'][0]['name']} - {item['name']}")
        
        return tracks
    except Exception as e:
        print(f"Spotify Error: {e}")
        return None
