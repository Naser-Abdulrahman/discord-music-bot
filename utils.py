import asyncio
import json
import logging
import subprocess
import sys

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

from config import SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET

logger = logging.getLogger(__name__)


def search_with_ytdlp(query, n=5):
    """Search YouTube with yt-dlp and return a list of metadata dicts."""
    cmd = [
        'yt-dlp.exe',
        f'ytsearch{n}:{query}',
        '--dump-json',
        '--no-playlist',
        '--quiet',
        '--ignore-errors'
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=45,
        )

        if result.returncode != 0:
            stderr = (result.stderr or '').strip()
            logger.error("yt-dlp search failed for %r (code %s): %s", query, result.returncode, stderr)
            return []

        results = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                logger.debug("Skipping malformed yt-dlp JSON line for query %r: %r", query, line[:200])
        return results
    except subprocess.TimeoutExpired:
        logger.exception("yt-dlp search timed out for %r", query)
        return []
    except Exception:
        logger.exception("Search error for %r", query)
        return []


async def find_explicit_url(query, loop):
    """Find an explicit version of a song by searching for query + explicit."""
    search_query = f"{query} explicit"
    logger.info("Searching for explicit version: %s", search_query)

    try:
        results = await loop.run_in_executor(None, lambda: search_with_ytdlp(search_query, n=5))
    except Exception:
        logger.exception("Explicit search failed for %r", query)
        return None, False

    explicit_keywords = ['explicit', 'dirty', 'uncensored', 'parental advisory']

    for res in results:
        title = res.get('title', '').lower()
        if any(keyword in title for keyword in explicit_keywords):
            logger.info("Found explicit match: %s", res.get('title'))
            return res.get('webpage_url'), True

    return None, False


def extract_playlist_videos(url):
    """Extract all video entries from a playlist using yt-dlp."""
    cmd = [
        'yt-dlp.exe',
        '--dump-json',
        '--flat-playlist',
        '--ignore-errors',
        '--quiet',
        '--no-warnings',
        url,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=60,
        )

        if result.returncode != 0:
            stderr = (result.stderr or '').strip()
            logger.error("Playlist extraction failed for %r (code %s): %s", url, result.returncode, stderr)
            return []

        entries = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("Skipping malformed playlist JSON line for %r: %r", url, line[:200])
                continue

            if data.get('url'):
                entries.append(data)
        return entries
    except subprocess.TimeoutExpired:
        logger.exception("Playlist extraction timed out for %r", url)
        return []
    except Exception:
        logger.exception("Playlist extraction error for %r", url)
        return []


def get_spotify_tracks(url):
    """Expand a Spotify track/playlist/album into a list of 'Artist - Title' strings."""
    if not SPOTIPY_CLIENT_ID or not SPOTIPY_CLIENT_SECRET:
        logger.error("Spotify credentials are missing; cannot resolve %r", url)
        return []

    try:
        auth_manager = SpotifyClientCredentials(
            client_id=SPOTIPY_CLIENT_ID,
            client_secret=SPOTIPY_CLIENT_SECRET,
        )
        sp = spotipy.Spotify(auth_manager=auth_manager)

        tracks = []
        url_lower = (url or '').lower()
        if 'track' in url_lower:
            track = sp.track(url)
            tracks.append(f"{track['artists'][0]['name']} - {track['name']}")
        elif 'playlist' in url_lower:
            results = sp.playlist_tracks(url)
            for item in results['items']:
                track = item['track']
                if track:
                    tracks.append(f"{track['artists'][0]['name']} - {track['name']}")
            while results.get('next'):
                results = sp.next(results)
                for item in results['items']:
                    track = item['track']
                    if track:
                        tracks.append(f"{track['artists'][0]['name']} - {track['name']}")
        elif 'album' in url_lower:
            results = sp.album_tracks(url)
            for item in results['items']:
                tracks.append(f"{item['artists'][0]['name']} - {item['name']}")
        else:
            logger.error("Unrecognized Spotify URL format: %r", url)
            return []

        return tracks
    except Exception:
        logger.exception("Spotify error while resolving %r", url)
        return []
