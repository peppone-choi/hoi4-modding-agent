"""Test Sonnet parallel execution."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from hoi4_agent.core.orchestration import execute_sonnet_parallel


@pytest.mark.asyncio
async def test_sonnet_parallel_first_success():
    client = MagicMock()
    
    success_response = MagicMock()
    success_response.content = [MagicMock(type="text", text="Success")]
    
    client.messages.create = MagicMock(return_value=success_response)
    
    result = await execute_sonnet_parallel(
        client=client,
        model="claude-sonnet-4",
        system_prompt="Test prompt",
        tools=[],
        messages=[{"role": "user", "content": "test"}],
        max_tokens=1024,
        count=3,
    )
    
    assert result == success_response
    assert client.messages.create.call_count >= 1


@pytest.mark.asyncio
async def test_sonnet_parallel_all_fail():
    client = MagicMock()
    
    client.messages.create = MagicMock(side_effect=Exception("API Error"))
    
    with pytest.raises(Exception, match="API Error"):
        await execute_sonnet_parallel(
            client=client,
            model="claude-sonnet-4",
            system_prompt="Test prompt",
            tools=[],
            messages=[{"role": "user", "content": "test"}],
            max_tokens=1024,
            count=2,
        )
    
    assert client.messages.create.call_count >= 1


@pytest.mark.asyncio
async def test_sonnet_parallel_partial_failure():
    client = MagicMock()
    
    success_response = MagicMock()
    success_response.content = [MagicMock(type="text", text="Success on retry")]
    
    call_count = 0
    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("First call failed")
        return success_response
    
    client.messages.create = MagicMock(side_effect=side_effect)
    
    result = await execute_sonnet_parallel(
        client=client,
        model="claude-sonnet-4",
        system_prompt="Test prompt",
        tools=[],
        messages=[{"role": "user", "content": "test"}],
        max_tokens=1024,
        count=3,
    )
    
    assert result == success_response
