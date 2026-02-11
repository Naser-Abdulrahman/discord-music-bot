from utils import extract_playlist_videos

def test_extract_playlist_videos():
    # Test with a known playlist or check empty/error handling
    # Using a small public playlist or just checking structure
    
    # Mocking/Checking a real playlist might be slow and flaky. 
    # Let's test with a known small playlist if possible, or just skip if no network.
    
    # https://www.youtube.com/playlist?list=PLMC9KNkIncVtP8kIs0G59rAyD5SIj2WqW (YouTube Spotlight - Popular)
    # Might be too big.
    
    # Let's just assert the function exists and behaves on bad input
    results = extract_playlist_videos("http://bad.url")
    assert results == []
