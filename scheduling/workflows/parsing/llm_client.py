from abc import abstractmethod
from typing import Optional

from core.utils.llm_utils import LLMProvider
from scheduling.workflows.parsing.schedules import SchedulesList


class LLMClientInterface:
    @abstractmethod
    async def get_completions(self,
                              messages: list[dict],
                              temperature: float) -> tuple[Optional[SchedulesList], Optional[str]]:
        pass

    async def aclose(self) -> None:
        """Release any underlying network resources. Default: no-op."""
        pass

    @abstractmethod
    def get_provider(self) -> LLMProvider:
        pass

    @abstractmethod
    def get_model(self) -> str:
        pass
