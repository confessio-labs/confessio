from abc import abstractmethod
from typing import TypeVar, Generic

from scheduling.utils.enum_utils import StringEnum

E = TypeVar('E', bound=StringEnum)


class MachineLearningInterface(Generic[E]):
    different_labels: list[E]

    @abstractmethod
    def fit(self, embeddings, labels: list[E]):
        """Learning method"""
        pass

    @abstractmethod
    def predict(self, embeddings) -> list[E]:
        """Prediction method"""
        pass

    @abstractmethod
    def from_pickle(self, pickle_as_str: str):
        pass

    @abstractmethod
    def to_pickle(self) -> str:
        pass
