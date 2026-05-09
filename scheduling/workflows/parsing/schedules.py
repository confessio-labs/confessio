from datetime import datetime, time, date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, model_validator, Field

from scheduling.utils.date_utils import Weekday, guess_year_from_weekday, get_python_weekday
from scheduling.utils.sort_utils import compare_int_or_none_tuples
from scheduling.workflows.parsing.liturgical import LiturgicalDayEnum, get_liturgical_date, \
    PeriodEnum


SCHEDULES_LIST_VERSION = 'v1.2'


################
# ONE OFF RULE #
################

class OneOffRule(BaseModel, frozen=True):
    year: int | None = Field(None, ge=1900)
    month: int | None = Field(None, ge=1, le=12)  # nullable when liturgical_day is given
    day: int | None = Field(None, ge=1, le=31)  # nullable when liturgical_day is given
    weekday: Weekday | None = None
    liturgical_day: LiturgicalDayEnum | None = None

    def is_valid(self) -> bool:
        return (self.month is not None and self.day is not None) or self.liturgical_day is not None

    def check_is_valid(self):
        if not self.is_valid():
            raise ValueError(f'Invalid one-off rule: {self}')

    def is_valid_date(self) -> bool:
        if not self.is_valid():
            return False

        try:
            if self.month and self.day:
                # check day and month
                datetime(2000, self.month, self.day)  # 2000 is a leap year

                # Check day and month with year
                if self.year:
                    datetime(self.year, self.month, self.day)

                # Check year and weekday
                if self.year and self.weekday is not None:
                    python_weekday = get_python_weekday(self.weekday)
                    if datetime(self.year, self.month, self.day).weekday() != python_weekday:
                        raise ValueError(f'Invalid weekday for {self}')

            return True
        except ValueError:
            return False

    def get_date(self, default_year: int) -> date:
        if self.liturgical_day:
            return get_liturgical_date(self.liturgical_day, self.year or default_year)

        if not self.year:
            if self.weekday is not None:
                year = guess_year_from_weekday(default_year, self.month, self.day, self.weekday)
            else:
                year = default_year
        else:
            year = self.year

        return date(year, self.month, self.day)

    def get_key(self):
        return self.year, self.month, self.day, self.weekday, self.liturgical_day

    def __lt__(self, other: 'OneOffRule') -> bool:
        return compare_int_or_none_tuples(self.get_key(), other.get_key())


################
# REGULAR RULE #
################

class Position(Enum):
    FIRST = 1
    SECOND = 2
    THIRD = 3
    FOURTH = 4
    FIFTH = 5
    LAST = -1


class NWeekday(BaseModel, frozen=True):
    weekday: Weekday
    position: Position

    def __lt__(self, other: 'NWeekday') -> bool:
        return (self.weekday.value, self.position.value) < \
            (other.weekday.value, other.position.value)


class DailyRule(BaseModel, frozen=True):
    def get_sorted(self) -> 'DailyRule':
        return self

    def __hash__(self):
        return hash('')


class WeeklyRule(BaseModel, frozen=True):
    by_weekdays: list[Weekday] = Field(..., description='uniqueItems', min_length=1)

    def get_sorted(self) -> 'WeeklyRule':
        return self.model_copy(update={'by_weekdays': list(sorted(set(self.by_weekdays)))})

    def __hash__(self):
        return hash(tuple(sorted(map(lambda w: w.value, self.by_weekdays))))


class MonthlyRule(BaseModel, frozen=True):
    by_nweekdays: list[NWeekday] = Field(..., min_length=1)

    def get_sorted(self) -> 'MonthlyRule':
        return self.model_copy(update={'by_nweekdays': list(sorted(set(self.by_nweekdays)))})

    def __hash__(self):
        return hash(tuple(sorted(self.by_nweekdays)))


class CustomPeriod(BaseModel, frozen=True):
    start: OneOffRule
    end: OneOffRule

    def __lt__(self, other: 'CustomPeriod') -> bool:
        return (self.start, self.end) < (other.start, other.end)

    def is_valid_period(self) -> bool:
        return self.start.is_valid() and self.end.is_valid()


def sort_periods(periods: list[PeriodEnum | CustomPeriod]) -> list[PeriodEnum | CustomPeriod]:
    return list(sorted(periods, key=lambda p: (isinstance(p, PeriodEnum), p)))


class RegularRule(BaseModel, frozen=True):
    rule: DailyRule | WeeklyRule | MonthlyRule
    only_in_periods: list[PeriodEnum | CustomPeriod] = Field(default_factory=list)
    not_in_periods: list[PeriodEnum | CustomPeriod] = Field(default_factory=list)
    not_on_dates: list[OneOffRule] = Field(default_factory=list, description='table')

    def __hash__(self):
        """It would have been simpler to use tuple instead of list for only_in_periods and
        not_in_periods, but openapi schema generation does not support tuple (for now)."""
        return hash((
            hash(self.rule),
            tuple(sort_periods(self.only_in_periods)),
            tuple(sort_periods(self.not_in_periods)),
            tuple(sorted(self.not_on_dates)),
        ))

    def check_is_valid(self):
        if self.rule != self.rule.get_sorted():
            raise ValueError(f'Unsorted rule: {self.rule}')
        if self.only_in_periods != sort_periods(self.only_in_periods):
            raise ValueError(f'Unsorted only_in_periods: {self.only_in_periods}')
        if self.not_in_periods != sort_periods(self.not_in_periods):
            raise ValueError(f'Unsorted not_in_periods: {self.not_in_periods}')
        if self.not_on_dates != list(sorted(self.not_on_dates)):
            raise ValueError(f'Unsorted not_on_dates: {self.not_on_dates}')

        for period in self.only_in_periods:
            if isinstance(period, CustomPeriod):
                period.start.check_is_valid()
                period.end.check_is_valid()
        for period in self.not_in_periods:
            if isinstance(period, CustomPeriod):
                period.start.check_is_valid()
                period.end.check_is_valid()
        for date_rule in self.not_on_dates:
            date_rule.check_is_valid()

    def get_valid(self) -> 'RegularRule':
        return self.model_copy(
            update={
                'rule': self.rule.get_sorted(),
                'only_in_periods': [
                    period
                    for period in sort_periods(self.only_in_periods) if period.is_valid_period()
                ],
                'not_in_periods': [
                    period
                    for period in sort_periods(self.not_in_periods) if period.is_valid_period()
                ],
                'not_on_dates': [
                    one_off_rule for one_off_rule in sorted(self.not_on_dates)
                    if one_off_rule.is_valid()],
            }
        )

    def is_daily_rule(self) -> bool:
        return isinstance(self.rule, DailyRule)

    def is_weekly_rule(self) -> bool:
        return isinstance(self.rule, WeeklyRule)

    def is_monthly_rule(self) -> bool:
        return isinstance(self.rule, MonthlyRule)


#############
# SCHEDULES #
#############

class ScheduleItem(BaseModel, frozen=True):
    church_id: int | None = None
    date_rule: OneOffRule | RegularRule
    is_cancellation: bool = False
    start_time_iso8601: str | None = Field(None, description='time')
    end_time_iso8601: str | None = Field(None, description='time')

    @model_validator(mode='after')
    def validate_times(self) -> 'ScheduleItem':
        self.get_start_time()
        self.get_end_time()

        return self

    def check_is_valid(self):
        self.date_rule.check_is_valid()

    def get_valid(self) -> 'ScheduleItem':
        if self.is_regular_rule():
            return self.model_copy(
                update={
                    'date_rule': self.date_rule.get_valid()
                }
            )

        return self

    def is_one_off_rule(self) -> bool:
        return isinstance(self.date_rule, OneOffRule)

    def is_regular_rule(self) -> bool:
        return isinstance(self.date_rule, RegularRule)

    def get_start_time(self) -> time | None:
        if self.start_time_iso8601 is None or self.start_time_iso8601 in ('', 'null'):
            return None

        return time.fromisoformat(self.start_time_iso8601)

    def get_end_time(self) -> time | None:
        if self.end_time_iso8601 is None or self.end_time_iso8601 in ('', 'null'):
            return None

        return time.fromisoformat(self.end_time_iso8601)

    def has_real_church(self):
        return self.church_id is not None and self.church_id != -1


class SchedulesList(BaseModel):
    schedules: list[ScheduleItem]
    possible_by_appointment: bool = Field(False, description='checkbox')
    is_related_to_mass: bool = Field(False, description='checkbox')
    is_related_to_adoration: bool = Field(False, description='checkbox')
    is_related_to_permanence: bool = Field(False, description='checkbox')
    will_be_seasonal_events: bool = Field(False, description='checkbox')

    def check_is_valid(self):
        """Raises ValueError if not valid.
        This is not a hard validation since some schedules returned by the LLM may be invalid.
        We prefer to handle it manually than raising ValidationError at model creation.
        """
        for schedule in self.schedules:
            schedule.check_is_valid()

    def __eq__(self, other: 'SchedulesList'):
        return self.model_dump(exclude={'schedules'}) == other.model_dump(exclude={'schedules'}) \
            and set(self.schedules) == set(other.schedules)


class Event(BaseModel, frozen=True):
    church_id: Optional[int]
    start: datetime
    end: Optional[datetime]

    def __lt__(self, other: 'Event'):
        return (self.start, self.church_id if self.church_id is not None else 100) \
            < (other.start, other.church_id if other.church_id is not None else 100)


def get_merged_schedules_list(sls: list[SchedulesList]) -> SchedulesList:
    return SchedulesList(
        schedules=[s for sl in sls for s in sl.schedules],
        possible_by_appointment=any(sl.possible_by_appointment for sl in sls),
        is_related_to_mass=any(sl.is_related_to_mass for sl in sls),
        is_related_to_adoration=any(sl.is_related_to_adoration for sl in sls),
        is_related_to_permanence=any(sl.is_related_to_permanence for sl in sls),
        will_be_seasonal_events=any(sl.will_be_seasonal_events for sl in sls),
    )
