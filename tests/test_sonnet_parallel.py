"""Test Sonnet parallel execution."""
import asyncio
from unittest.mock import MagicMock

import pytest

from hoi4_agent.core.orchestration import execute_sonnet_parallel


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def success_response():
    resp = MagicMock()
    resp.content = [MagicMock(type="text", text="Success")]
    return resp


def test_sonnet_parallel_first_success(mock_client, success_response):
    mock_client.messages.create = MagicMock(return_value=success_response)
    
    result = asyncio.run(
        execute_sonnet_parallel(
            client=mock_client,
            model="claude-sonnet-4",
            system_prompt="Test prompt",
            tools=[],
            messages=[{"role": "user", "content": "test"}],
            max_tokens=1024,
            count=3,
        )
    )
    
    assert result == success_response
    assert mock_client.messages.create.call_count >= 1


def test_sonnet_parallel_all_fail(mock_client):
    mock_client.messages.create = MagicMock(side_effect=Exception("API Error"))
    
    with pytest.raises(Exception, match="API Error"):
        asyncio.run(
            execute_sonnet_parallel(
                client=mock_client,
                model="claude-sonnet-4",
                system_prompt="Test prompt",
                tools=[],
                messages=[{"role": "user", "content": "test"}],
                max_tokens=1024,
                count=2,
            )
        )
    
    assert mock_client.messages.create.call_count >= 1


def test_sonnet_parallel_partial_failure(mock_client, success_response):
    call_count = 0
    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("First call failed")
        return success_response
    
    mock_client.messages.create = MagicMock(side_effect=side_effect)
    
    result = asyncio.run(
        execute_sonnet_parallel(
            client=mock_client,
            model="claude-sonnet-4",
            system_prompt="Test prompt",
            tools=[],
            messages=[{"role": "user", "content": "test"}],
            max_tokens=1024,
            count=3,
        )
    )
    
    assert result == success_response
