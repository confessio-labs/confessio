from abc import ABC, abstractmethod
from uuid import UUID

from pydantic import BaseModel

from scheduling.workflows.parsing.liturgical import PeriodEnum  # noqa
from scheduling.workflows.parsing.schedules import ScheduleItem
from scheduling.workflows.parsing.schedules import SchedulesList


###########
# SOURCES #
###########

class BaseSource(BaseModel, ABC, frozen=True):
    schedules_list: SchedulesList | None

    @property
    @abstractmethod
    def source_type(self) -> str:
        pass

    @abstractmethod
    def hash_key(self):
        pass

    def __hash__(self):
        return hash(self.hash_key())


class ParsingSource(BaseSource):
    parsing_uuid: UUID

    @property
    def source_type(self) -> str:
        return 'parsing'

    def hash_key(self):
        return self.source_type, self.parsing_uuid


class OClocherSource(BaseSource):

    @property
    def source_type(self) -> str:
        return 'oclocher'

    def hash_key(self):
        return (self.source_type,)


UnionSource = ParsingSource | OClocherSource


#############
# SCHEDULES #
#############

class SourcedScheduleItem(BaseModel):
    item: ScheduleItem
    explanation: str
    sources: list[UnionSource]

    def hash_key(self):
        return (
            self.item.model_dump_json(),
            self.explanation,
            tuple(sorted(map(lambda s: s.hash_key(), self.sources)))
        )


class SourcedSchedulesOfChurch(BaseModel):
    church_id: int | None
    sourced_schedules: list[SourcedScheduleItem]

    def is_church_explicitly_other(self) -> bool:
        return self.church_id == -1

    def is_real_church(self) -> bool:
        return self.church_id is not None and not self.is_church_explicitly_other()

    def hash_key(self):
        return (
            self.church_id if self.church_id is not None else -2,
            tuple(sorted(map(lambda s: s.hash_key(), self.sourced_schedules)))
        )


class SourcedSchedulesList(BaseModel):
    sourced_schedules_of_churches: list[SourcedSchedulesOfChurch]
    possible_by_appointment_sources: list[UnionSource]
    is_related_to_mass_sources: list[UnionSource]
    is_related_to_adoration_sources: list[UnionSource]
    is_related_to_permanence_sources: list[UnionSource]
    will_be_seasonal_events_sources: list[UnionSource]

    def hash_key(self):
        return (
            tuple(sorted(map(lambda s: s.hash_key(), self.sourced_schedules_of_churches))),
            tuple(sorted(map(lambda s: s.hash_key(), self.possible_by_appointment_sources))),
            tuple(sorted(map(lambda s: s.hash_key(), self.is_related_to_mass_sources))),
            tuple(sorted(map(lambda s: s.hash_key(), self.is_related_to_adoration_sources))),
            tuple(sorted(map(lambda s: s.hash_key(), self.is_related_to_permanence_sources))),
            tuple(sorted(map(lambda s: s.hash_key(), self.will_be_seasonal_events_sources))),
        )
