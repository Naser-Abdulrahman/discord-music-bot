import pytest
from unittest.mock import patch, MagicMock
from utils import search_with_ytdlp, find_explicit_url
import json

def test_search_with_ytdlp():
    # Mock subprocess.run to return a fake JSON result
    with patch('subprocess.run') as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = json.dumps({
            "title": "Test Video",
            "webpage_url": "https://youtube.com/watch?v=123",
            "id": "123"
        })
        mock_run.return_value = mock_result
        
        # Basic search test
        results = search_with_ytdlp("test video", n=1)
        
        assert len(results) > 0
        assert results[0]['title'] == "Test Video"
        assert results[0]['webpage_url'] == "https://youtube.com/watch?v=123"

@pytest.mark.asyncio
async def test_find_explicit_url():
    # Mock search_with_ytdlp to return explicit result
    with patch('utils.search_with_ytdlp') as mock_search:
        mock_search.return_value = [{
            "title": "WAP (Explicit)",
            "webpage_url": "https://youtube.com/watch?v=wap",
            "id": "wap"
        }]
        
        # We need to pass a loop to find_explicit_url?
        # definition: async def find_explicit_url(query, loop):
        # We can pass asyncio.get_running_loop() or mock it.
        import asyncio
        loop = asyncio.get_running_loop()
        
        url, is_explicit = await find_explicit_url("WAP", loop)
        
        assert url == "https://youtube.com/watch?v=wap"
        assert is_explicit is True
