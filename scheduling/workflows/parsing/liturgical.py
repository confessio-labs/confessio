from datetime import date, timedelta
from enum import Enum

from scheduling.utils.date_utils import get_current_day


###################
# LITURGICAL DAYS #
###################

class LiturgicalDayEnum(str, Enum):
    ASH_WEDNESDAY = 'ash_wednesday'
    PALM_SUNDAY = 'palm_sunday'
    HOLY_MONDAY = 'holy_monday'
    HOLY_TUESDAY = 'holy_tuesday'
    HOLY_WEDNESDAY = 'holy_wednesday'
    MAUNDY_THURSDAY = 'maundy_thursday'
    GOOD_FRIDAY = 'good_friday'
    HOLY_SATURDAY = 'holy_saturday'
    EASTER_SUNDAY = 'easter_sunday'
    EASTER_MONDAY = 'easter_monday'
    ASCENSION = 'ascension'
    PENTECOST = 'pentecost'

    @classmethod
    def choices(cls):
        return [(item.value, item.name) for item in cls]


# To be filled on year basis
EASTER_DATES_BY_YEAR = {
    2024: date(2024, 3, 31),
    2025: date(2025, 4, 20),
    2026: date(2026, 4, 5),
    2027: date(2027, 3, 28),
}


def get_easter_day(year: int) -> date:
    if year not in EASTER_DATES_BY_YEAR:
        raise ValueError(f'Easter day not implemented for year {year}')

    return EASTER_DATES_BY_YEAR[year]


def check_easter_dates() -> bool:
    # In october, we should have easter date for the next year
    future_date = get_current_day() + timedelta(days=365 + 3 * 30)
    future_year = future_date.year

    return future_year in EASTER_DATES_BY_YEAR


def get_offset(liturgical_day: LiturgicalDayEnum):
    if liturgical_day == LiturgicalDayEnum.ASH_WEDNESDAY:
        return -46
    if liturgical_day == LiturgicalDayEnum.PALM_SUNDAY:
        return -7
    if liturgical_day == LiturgicalDayEnum.HOLY_MONDAY:
        return -6
    if liturgical_day == LiturgicalDayEnum.HOLY_TUESDAY:
        return -5
    if liturgical_day == LiturgicalDayEnum.HOLY_WEDNESDAY:
        return -4
    if liturgical_day == LiturgicalDayEnum.MAUNDY_THURSDAY:
        return -3
    if liturgical_day == LiturgicalDayEnum.GOOD_FRIDAY:
        return -2
    if liturgical_day == LiturgicalDayEnum.HOLY_SATURDAY:
        return -1
    if liturgical_day == LiturgicalDayEnum.EASTER_SUNDAY:
        return 0
    if liturgical_day == LiturgicalDayEnum.EASTER_MONDAY:
        return 1
    if liturgical_day == LiturgicalDayEnum.ASCENSION:
        return 39
    if liturgical_day == LiturgicalDayEnum.PENTECOST:
        return 49

    raise NotImplementedError(f'Liturgical day {liturgical_day} not implemented for offset')


def get_liturgical_date(liturgical_day: LiturgicalDayEnum, year: int) -> date:
    easter_day = get_easter_day(year)
    offset = get_offset(liturgical_day)

    return easter_day + timedelta(days=offset)


def get_solemnities_dates(year: int) -> list[date]:
    return [
        date(year, 1, 1),  # Mary, Mother of God
        get_liturgical_date(LiturgicalDayEnum.EASTER_SUNDAY, year),
        get_liturgical_date(LiturgicalDayEnum.ASCENSION, year),
        get_liturgical_date(LiturgicalDayEnum.PENTECOST, year),
        date(year, 8, 15),  # Assumption
        date(year, 11, 1),  # All Saints
        date(year, 12, 25),  # Christmas
    ]


###########
# PERIODS #
###########

class PeriodEnum(str, Enum):
    # Seasons
    SUMMER = 'summer'
    WINTER = 'winter'

    # Liturgical seasons
    ADVENT = 'advent'
    LENT = 'lent'
    SOLEMNITIES = 'solemnities'
    HOLY_WEEK = 'holy_week'

    # Holidays
    SCHOOL_HOLIDAYS = 'school_holidays'

    @classmethod
    def choices(cls):
        return [(item.value, item.name) for item in cls]

    @staticmethod
    def is_valid_period() -> bool:
        return True


def get_advent_dates(year: int) -> tuple[date, date]:
    christmas = date(year, 12, 25)
    # Find the fourth Sunday before Christmas
    advent_start = christmas - timedelta(days=christmas.weekday() + 22)
    return advent_start, christmas
