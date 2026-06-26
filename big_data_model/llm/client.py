from openai import AsyncOpenAI
from big_data_model.config import Settings


class LLMClient:
    def __init__(self, settings: Settings):
        self._client = AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
        )
        self._model = settings.llm_model
        self._temperature = settings.llm_temperature

    async def chat(self, messages: list[dict]) -> str:
        """Simple chat completion, returns content string."""
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=self._temperature,
        )
        return response.choices[0].message.content or ""

    async def chat_with_tools(self, messages: list[dict], tools: list[dict]):
        """Chat with tool calling. Returns the raw message object."""
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=tools,
            temperature=self._temperature,
        )
        return response.choices[0].message
