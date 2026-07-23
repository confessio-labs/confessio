from __future__ import annotations

import os
from typing import Optional, TYPE_CHECKING

from pydantic import ValidationError

from core.utils.llm_utils import LLMProvider
from scheduling.workflows.parsing.llm_client import LLMClientInterface
from scheduling.workflows.parsing.schedules import SchedulesList

if TYPE_CHECKING:
    # openai costs ~0.24 s to import and is only needed by the worker, but this module is
    # reachable from the server startup path, so it is imported lazily. `from __future__ import
    # annotations` above keeps the AsyncOpenAI annotations from being evaluated at runtime.
    from openai import AsyncOpenAI


class OpenAILLMClient(LLMClientInterface):
    client: AsyncOpenAI

    def __init__(self, client: AsyncOpenAI, model: str):
        self.client = client
        self.model = model

    async def get_completions(self,
                              messages: list[dict],
                              temperature: float) -> tuple[Optional[SchedulesList], Optional[str]]:
        from openai import BadRequestError

        try:
            temperature_args = {'temperature': temperature} if self.model != 'o3' else {}
            response = await self.client.chat.completions.parse(
                model=self.model,
                messages=messages,
                response_format=SchedulesList,
                **temperature_args
            )
        except BadRequestError as e:
            print(e)
            return None, str(e)
        except ValidationError as e:
            print(e)
            return None, str(e)

        message = response.choices[0].message
        schedules_list = message.parsed
        if not schedules_list:
            return None, message.refusal

        return schedules_list, None

    async def aclose(self) -> None:
        await self.client.close()

    def get_provider(self) -> LLMProvider:
        return LLMProvider.OPENAI

    def get_model(self) -> str:
        return self.model


def get_openai_client(openai_api_key: Optional[str] = None) -> AsyncOpenAI:
    from openai import AsyncOpenAI

    if not openai_api_key:
        openai_api_key = os.getenv("OPENAI_API_KEY")

    return AsyncOpenAI(api_key=openai_api_key)


def get_openai_llm_client() -> OpenAILLMClient:
    # TODO get latest fine-tuned model
    # openai_model = 'ft:gpt-4o-2024-08-06:confessio::AHfh95wJ'
    openai_model = 'o3'  # or "gpt-4o-mini"

    return OpenAILLMClient(get_openai_client(), openai_model)
