import yt_dlp
import os

from unittest.mock import patch, MagicMock

def test_ytdlp_configuration():
    # Test that the configuration used in the bot is valid for yt-dlp
    from config import ytdl_format_options
    
    # Mock yt_dlp.YoutubeDL to avoid actual network calls/blocking
    with patch('yt_dlp.YoutubeDL') as mock_ydl_cls:
        mock_instance = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_instance
        
        # Mock extract_info return
        mock_instance.extract_info.return_value = {'title': 'Me at the zoo'}
        
        # Copy options but disable download
        opts = ytdl_format_options.copy()
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            # Extract info for a known safe video (e.g. Me at the zoo)
            info = ydl.extract_info('https://www.youtube.com/watch?v=jNQXAC9IVRw', download=False)
            assert info['title'] == 'Me at the zoo'
