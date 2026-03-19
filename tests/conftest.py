import pytest
from app.config import Settings


@pytest.fixture
def settings():
    return Settings(
        llm_api_key="test-key",
        llm_base_url="http://test:8000/v1",
        llm_model="test-model",
        debug=True,
    )
