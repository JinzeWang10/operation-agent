import pytest
from unittest.mock import AsyncMock, MagicMock
from big_data_model.llm.client import LLMClient
from big_data_model.config import Settings


@pytest.fixture
def llm_settings():
    return Settings(
        llm_api_key="test-key",
        llm_base_url="http://test:8000/v1",
        llm_model="test-model",
    )


@pytest.mark.asyncio
async def test_chat_returns_content(llm_settings):
    client = LLMClient(llm_settings)

    mock_message = MagicMock()
    mock_message.content = "Hello from LLM"
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    client._client.chat.completions.create = AsyncMock(return_value=mock_response)

    result = await client.chat([{"role": "user", "content": "hi"}])
    assert result == "Hello from LLM"


@pytest.mark.asyncio
async def test_chat_with_tools_returns_message(llm_settings):
    client = LLMClient(llm_settings)

    mock_message = MagicMock()
    mock_message.content = None
    mock_message.tool_calls = [MagicMock()]
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    client._client.chat.completions.create = AsyncMock(return_value=mock_response)

    result = await client.chat_with_tools(
        [{"role": "user", "content": "investigate"}],
        [{"type": "function", "function": {"name": "test"}}],
    )
    assert result.tool_calls is not None
