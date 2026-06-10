import pprint
import re
from datetime import date, timedelta, datetime
from enum import Enum
from typing import List, Dict

import httpx

from scheduling.utils.date_utils import get_current_day


class HolidayZoneEnum(str, Enum):
    FR_ZONE_A = 'fr_zone_a'
    FR_ZONE_B = 'fr_zone_b'
    FR_ZONE_C = 'fr_zone_c'
    CORSICA = 'corsica'
    GUADELOUPE = 'guadeloupe'
    MARTINIQUE = 'martinique'
    DOM = 'dom'

    def __repr__(self):
        return f"'{self.value}'"


HOLIDAY_ZONE_PER_DEPARTMENT = {
    "01": HolidayZoneEnum.FR_ZONE_A,
    "02": HolidayZoneEnum.FR_ZONE_B,
    "03": HolidayZoneEnum.FR_ZONE_A,
    "04": HolidayZoneEnum.FR_ZONE_B,
    "05": HolidayZoneEnum.FR_ZONE_B,
    "06": HolidayZoneEnum.FR_ZONE_B,
    "07": HolidayZoneEnum.FR_ZONE_A,
    "08": HolidayZoneEnum.FR_ZONE_B,
    "09": HolidayZoneEnum.FR_ZONE_C,
    "10": HolidayZoneEnum.FR_ZONE_B,
    "11": HolidayZoneEnum.FR_ZONE_C,
    "12": HolidayZoneEnum.FR_ZONE_C,
    "13": HolidayZoneEnum.FR_ZONE_B,
    "14": HolidayZoneEnum.FR_ZONE_B,
    "15": HolidayZoneEnum.FR_ZONE_A,
    "16": HolidayZoneEnum.FR_ZONE_A,
    "17": HolidayZoneEnum.FR_ZONE_A,
    "18": HolidayZoneEnum.FR_ZONE_B,
    "19": HolidayZoneEnum.FR_ZONE_A,
    "2A": HolidayZoneEnum.CORSICA,
    "2B": HolidayZoneEnum.CORSICA,
    "20": HolidayZoneEnum.CORSICA,
    "21": HolidayZoneEnum.FR_ZONE_A,
    "22": HolidayZoneEnum.FR_ZONE_B,
    "23": HolidayZoneEnum.FR_ZONE_A,
    "24": HolidayZoneEnum.FR_ZONE_A,
    "25": HolidayZoneEnum.FR_ZONE_A,
    "26": HolidayZoneEnum.FR_ZONE_A,
    "27": HolidayZoneEnum.FR_ZONE_B,
    "28": HolidayZoneEnum.FR_ZONE_B,
    "29": HolidayZoneEnum.FR_ZONE_B,
    "30": HolidayZoneEnum.FR_ZONE_C,
    "31": HolidayZoneEnum.FR_ZONE_C,
    "32": HolidayZoneEnum.FR_ZONE_C,
    "33": HolidayZoneEnum.FR_ZONE_A,
    "34": HolidayZoneEnum.FR_ZONE_C,
    "35": HolidayZoneEnum.FR_ZONE_B,
    "36": HolidayZoneEnum.FR_ZONE_B,
    "37": HolidayZoneEnum.FR_ZONE_B,
    "38": HolidayZoneEnum.FR_ZONE_A,
    "39": HolidayZoneEnum.FR_ZONE_A,
    "40": HolidayZoneEnum.FR_ZONE_A,
    "41": HolidayZoneEnum.FR_ZONE_B,
    "42": HolidayZoneEnum.FR_ZONE_A,
    "43": HolidayZoneEnum.FR_ZONE_A,
    "44": HolidayZoneEnum.FR_ZONE_B,
    "45": HolidayZoneEnum.FR_ZONE_B,
    "46": HolidayZoneEnum.FR_ZONE_C,
    "47": HolidayZoneEnum.FR_ZONE_A,
    "48": HolidayZoneEnum.FR_ZONE_C,
    "49": HolidayZoneEnum.FR_ZONE_B,
    "50": HolidayZoneEnum.FR_ZONE_B,
    "51": HolidayZoneEnum.FR_ZONE_B,
    "52": HolidayZoneEnum.FR_ZONE_B,
    "53": HolidayZoneEnum.FR_ZONE_B,
    "54": HolidayZoneEnum.FR_ZONE_B,
    "55": HolidayZoneEnum.FR_ZONE_B,
    "56": HolidayZoneEnum.FR_ZONE_B,
    "57": HolidayZoneEnum.FR_ZONE_B,
    "58": HolidayZoneEnum.FR_ZONE_A,
    "59": HolidayZoneEnum.FR_ZONE_B,
    "60": HolidayZoneEnum.FR_ZONE_B,
    "61": HolidayZoneEnum.FR_ZONE_B,
    "62": HolidayZoneEnum.FR_ZONE_B,
    "63": HolidayZoneEnum.FR_ZONE_A,
    "64": HolidayZoneEnum.FR_ZONE_A,
    "65": HolidayZoneEnum.FR_ZONE_C,
    "66": HolidayZoneEnum.FR_ZONE_C,
    "67": HolidayZoneEnum.FR_ZONE_B,
    "68": HolidayZoneEnum.FR_ZONE_B,
    "69": HolidayZoneEnum.FR_ZONE_A,
    "70": HolidayZoneEnum.FR_ZONE_A,
    "71": HolidayZoneEnum.FR_ZONE_A,
    "72": HolidayZoneEnum.FR_ZONE_B,
    "73": HolidayZoneEnum.FR_ZONE_A,
    "74": HolidayZoneEnum.FR_ZONE_A,
    "75": HolidayZoneEnum.FR_ZONE_C,
    "76": HolidayZoneEnum.FR_ZONE_B,
    "77": HolidayZoneEnum.FR_ZONE_C,
    "78": HolidayZoneEnum.FR_ZONE_C,
    "79": HolidayZoneEnum.FR_ZONE_A,
    "80": HolidayZoneEnum.FR_ZONE_B,
    "81": HolidayZoneEnum.FR_ZONE_C,
    "82": HolidayZoneEnum.FR_ZONE_C,
    "83": HolidayZoneEnum.FR_ZONE_B,
    "84": HolidayZoneEnum.FR_ZONE_B,
    "85": HolidayZoneEnum.FR_ZONE_B,
    "86": HolidayZoneEnum.FR_ZONE_A,
    "87": HolidayZoneEnum.FR_ZONE_A,
    "88": HolidayZoneEnum.FR_ZONE_B,
    "89": HolidayZoneEnum.FR_ZONE_A,
    "90": HolidayZoneEnum.FR_ZONE_A,
    "91": HolidayZoneEnum.FR_ZONE_C,
    "92": HolidayZoneEnum.FR_ZONE_C,
    "93": HolidayZoneEnum.FR_ZONE_C,
    "94": HolidayZoneEnum.FR_ZONE_C,
    "95": HolidayZoneEnum.FR_ZONE_C,
    "971": HolidayZoneEnum.GUADELOUPE,
    "972": HolidayZoneEnum.MARTINIQUE,
    "973": HolidayZoneEnum.DOM,
    "974": HolidayZoneEnum.DOM,
    "975": HolidayZoneEnum.DOM,
    "976": HolidayZoneEnum.DOM,
}


def parse_ics(ics_content: str, default_zones: list | None = None) -> List[Dict]:
    events = []
    event_pattern = re.compile(r'BEGIN:VEVENT(.*?)END:VEVENT', re.DOTALL)

    for match in event_pattern.findall(ics_content):
        name = re.search(r'SUMMARY:(.*?)\n', match)

        if not name or not name.group(1).startswith('Vacances'):
            continue

        start_date = re.search(r'DTSTART;VALUE=DATE:(\d+)', match)
        end_date = re.search(r'DTEND;VALUE=DATE:(\d+)', match)
        location = re.search(r'LOCATION:(.*?)\n', match)

        if name and start_date and end_date and (location or default_zones):
            start_date = datetime.strptime(start_date.group(1), "%Y%m%d").date()
            end_date = datetime.strptime(end_date.group(1), "%Y%m%d").date()
            zones = parse_zones(location.group(1)) if default_zones is None else default_zones

            events.append({
                'name': name.group(1),
                'zones': zones,
                'start_date': start_date,
                'end_date': end_date
            })

    return events


def parse_zones(location: str) -> List[HolidayZoneEnum]:
    zones = []
    if 'Zones A/B/C' in location:
        zones.append(HolidayZoneEnum.FR_ZONE_A)
        zones.append(HolidayZoneEnum.FR_ZONE_B)
        zones.append(HolidayZoneEnum.FR_ZONE_C)
    elif 'Zones A/B' in location:
        zones.append(HolidayZoneEnum.FR_ZONE_A)
        zones.append(HolidayZoneEnum.FR_ZONE_B)
    elif 'Zones B/C' in location:
        zones.append(HolidayZoneEnum.FR_ZONE_B)
        zones.append(HolidayZoneEnum.FR_ZONE_C)
    elif 'Zones A/C' in location:
        zones.append(HolidayZoneEnum.FR_ZONE_A)
        zones.append(HolidayZoneEnum.FR_ZONE_C)

    if 'Zone A' in location:
        zones.append(HolidayZoneEnum.FR_ZONE_A)
    elif 'Zone B' in location:
        zones.append(HolidayZoneEnum.FR_ZONE_B)
    elif 'Zone C' in location:
        zones.append(HolidayZoneEnum.FR_ZONE_C)

    if 'Corse' in location:
        zones.append(HolidayZoneEnum.CORSICA)
    return zones


def print_holidays_for_zone(ics_content, default_zones: list | None = None):
    holiday_by_zone = {
        HolidayZoneEnum.FR_ZONE_A: {},
        HolidayZoneEnum.FR_ZONE_B: {},
        HolidayZoneEnum.FR_ZONE_C: {},
        HolidayZoneEnum.CORSICA: {},
        HolidayZoneEnum.GUADELOUPE: {},
        HolidayZoneEnum.MARTINIQUE: {},
    }

    for item in parse_ics(ics_content, default_zones):
        year = item['start_date'].year
        if year < 2024:
            continue
        for zone in item['zones']:
            holiday_by_zone[zone].setdefault(year, []).append((item['start_date'],
                                                               item['end_date']))
    for zone, years in holiday_by_zone.items():
        for year, periods in years.items():
            new_periods = []
            last_end = None
            for start, end in sorted(periods):
                if last_end is not None and start <= last_end:
                    new_periods[-1] = (new_periods[-1][0], end)
                else:
                    new_periods.append((start, end))
                last_end = end
            holiday_by_zone[zone][year] = new_periods

    print(pprint.pformat(holiday_by_zone))


def get_ics_content_from_url(ics_url: str) -> str:
    response = httpx.get(ics_url)
    return response.text


def generate_and_print_holiday_by_zone():
    # https://www.data.gouv.fr/datasets/le-calendrier-scolaire/
    ics_url = ('https://fr.ftp.opendatasoft.com/openscol/fr-en-calendrier-scolaire/'
               'Zone-A-B-C-Corse.ics')
    ics_content = get_ics_content_from_url(ics_url)

    print_holidays_for_zone(ics_content)


def generate_and_print_corsica_holiday():
    # Alternative : https://www.ac-corse.fr/calendrier-scolaire-122048

    ics_url = 'https://fr.ftp.opendatasoft.com/openscol/fr-en-calendrier-scolaire/Corse.ics'
    ics_content = get_ics_content_from_url(ics_url)

    print_holidays_for_zone(ics_content, default_zones=[HolidayZoneEnum.CORSICA])


def generate_and_print_guadeloupe_holiday():
    ics_url = 'https://fr.ftp.opendatasoft.com/openscol/fr-en-calendrier-scolaire/Guadeloupe.ics'
    ics_content = get_ics_content_from_url(ics_url)

    print_holidays_for_zone(ics_content, default_zones=[HolidayZoneEnum.GUADELOUPE])


def generate_and_print_martinique_holiday():
    # https://www.data.gouv.fr/datasets/le-calendrier-scolaire/
    # ou
    # https://www.vacances-scolaires-gouv.com/outremer/martinique
    ics_url = 'https://fr.ftp.opendatasoft.com/openscol/fr-en-calendrier-scolaire/Martinique.ics'
    ics_content = get_ics_content_from_url(ics_url)

    print_holidays_for_zone(ics_content, default_zones=[HolidayZoneEnum.MARTINIQUE])


HOLIDAY_BY_ZONE = {
    'corsica': {2024: [(date(2024, 2, 26), date(2024, 3, 11)),
                       (date(2024, 4, 29), date(2024, 5, 13)),
                       (date(2024, 7, 6), date(2024, 9, 2)),
                       (date(2024, 10, 19), date(2024, 11, 4)),
                       (date(2024, 12, 21), date(2025, 1, 6))],
                2025: [(date(2025, 2, 15), date(2025, 3, 3)),
                       (date(2025, 4, 12), date(2025, 4, 28)),
                       (date(2025, 7, 5), date(2025, 9, 1)),
                       (date(2025, 10, 18), date(2025, 11, 3)),
                       (date(2025, 12, 20), date(2026, 1, 5))],
                2026: [(date(2026, 2, 14), date(2026, 3, 2)),
                       (date(2026, 4, 11), date(2026, 4, 27))]},
    'fr_zone_a': {2024: [(date(2024, 2, 17), date(2024, 3, 4)),
                         (date(2024, 4, 13), date(2024, 4, 29)),
                         (date(2024, 7, 6), date(2024, 9, 2)),
                         (date(2024, 10, 19), date(2024, 11, 4)),
                         (date(2024, 12, 21), date(2025, 1, 6))],
                  2025: [(date(2025, 2, 22), date(2025, 3, 10)),
                         (date(2025, 4, 19), date(2025, 5, 5)),
                         (date(2025, 7, 5), date(2025, 9, 1)),
                         (date(2025, 10, 18), date(2025, 11, 3)),
                         (date(2025, 12, 20), date(2026, 1, 5))],
                  2026: [(date(2026, 2, 7), date(2026, 2, 23)),
                         (date(2026, 4, 4), date(2026, 4, 20)),
                         (date(2026, 7, 4), date(2026, 9, 1)),
                         (date(2026, 10, 17), date(2026, 11, 2)),
                         (date(2026, 12, 19), date(2027, 1, 4))],
                  2027: [(date(2027, 2, 13), date(2027, 3, 1)),
                         (date(2027, 4, 10), date(2027, 4, 26))]},
    'fr_zone_b': {2024: [(date(2024, 2, 24), date(2024, 3, 11)),
                         (date(2024, 4, 20), date(2024, 5, 6)),
                         (date(2024, 7, 6), date(2024, 9, 2)),
                         (date(2024, 10, 19), date(2024, 11, 4)),
                         (date(2024, 12, 21), date(2025, 1, 6))],
                  2025: [(date(2025, 2, 8), date(2025, 2, 24)),
                         (date(2025, 4, 5), date(2025, 4, 22)),
                         (date(2025, 7, 5), date(2025, 9, 1)),
                         (date(2025, 10, 18), date(2025, 11, 3)),
                         (date(2025, 12, 20), date(2026, 1, 5))],
                  2026: [(date(2026, 2, 14), date(2026, 3, 2)),
                         (date(2026, 4, 11), date(2026, 4, 27)),
                         (date(2026, 7, 4), date(2026, 9, 1)),
                         (date(2026, 10, 17), date(2026, 11, 2)),
                         (date(2026, 12, 19), date(2027, 1, 4))],
                  2027: [(date(2027, 2, 20), date(2027, 3, 8)),
                         (date(2027, 4, 17), date(2027, 5, 3))]},
    'fr_zone_c': {2024: [(date(2024, 2, 10), date(2024, 2, 26)),
                         (date(2024, 4, 6), date(2024, 4, 22)),
                         (date(2024, 7, 6), date(2024, 9, 2)),
                         (date(2024, 10, 19), date(2024, 11, 4)),
                         (date(2024, 12, 21), date(2025, 1, 6))],
                  2025: [(date(2025, 2, 15), date(2025, 3, 3)),
                         (date(2025, 4, 12), date(2025, 4, 28)),
                         (date(2025, 7, 5), date(2025, 9, 1)),
                         (date(2025, 10, 18), date(2025, 11, 3)),
                         (date(2025, 12, 20), date(2026, 1, 5))],
                  2026: [(date(2026, 2, 21), date(2026, 3, 9)),
                         (date(2026, 4, 18), date(2026, 5, 4)),
                         (date(2026, 7, 4), date(2026, 9, 1)),
                         (date(2026, 10, 17), date(2026, 11, 2)),
                         (date(2026, 12, 19), date(2027, 1, 4))],
                  2027: [(date(2027, 2, 6), date(2027, 2, 22)),
                         (date(2027, 4, 3), date(2027, 4, 19))]},
    'guadeloupe': {2025: [(date(2025, 2, 22), date(2025, 3, 10)),
                          (date(2025, 4, 17), date(2025, 5, 5)),
                          (date(2025, 7, 5), date(2025, 9, 1)),
                          (date(2025, 10, 18),
                           date(2025, 11, 3)),
                          (date(2025, 12, 20),
                           date(2026, 1, 5))],
                   2026: [(date(2026, 2, 7), date(2026, 2, 23)),
                          (date(2026, 4, 2),
                           date(2026, 4, 20))]},
    'martinique': {2025: [(date(2025, 2, 22), date(2025, 3, 10)),
                          (date(2025, 4, 12), date(2025, 4, 28)),
                          (date(2025, 7, 5), date(2025, 9, 1)),
                          (date(2025, 10, 18), date(2025, 11, 3)),
                          (date(2025, 12, 20), date(2026, 1, 5)), ],
                   2026: [(date(2026, 2, 7), date(2026, 2, 23)),
                          (date(2026, 3, 28), date(2026, 4, 13)),
                          (date(2026, 7, 4), date(2026, 9, 1)),
                          (date(2026, 10, 20), date(2026, 11, 3)),
                          (date(2026, 12, 19), date(2027, 1, 4)),],
                   2027: [(date(2027, 2, 6), date(2027, 2, 22)),
                          (date(2027, 3, 24), date(2027, 4, 1)),
                          (date(2027, 4, 20), date(2027, 5, 3)),],
                   }
}


def check_holiday_by_zone() -> bool:
    # In November, we should have holidays for the next school year
    future_date = get_current_day() + timedelta(days=365 + 2 * 30)
    future_year = future_date.year
    return future_year in HOLIDAY_BY_ZONE[HolidayZoneEnum.FR_ZONE_A]


if __name__ == '__main__':
    generate_and_print_holiday_by_zone()
    # generate_and_print_corsica_holiday()
    # generate_and_print_guadeloupe_holiday()
    # generate_and_print_martinique_holiday()
