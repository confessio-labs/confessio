from datetime import timedelta
from enum import Enum


class NoteTtl(str, Enum):
    ONE_WEEK = 'one_week'
    ONE_MONTH = 'one_month'
    ONE_YEAR = 'one_year'

    @property
    def duration(self) -> timedelta:
        return {
            NoteTtl.ONE_WEEK: timedelta(days=7),
            NoteTtl.ONE_MONTH: timedelta(days=30),
            NoteTtl.ONE_YEAR: timedelta(days=365),
        }[self]
