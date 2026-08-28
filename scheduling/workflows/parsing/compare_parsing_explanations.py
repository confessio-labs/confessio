"""Human-readable ('Explained' tab) rendering of a parsing's SchedulesList, and the before/after
comparison shown on the copilot's approval card.

The parsing-side counterpart of workflows/merging/compare_explanations.py, whose ExplanationLine
and multiplicity-aware build_explanation_lines are reused. That module compares two
SourcedSchedulesList and labels churches from Church rows; here we compare two raw SchedulesList
and label churches from the parsing's own church_desc_by_id.

No Django import: this runs in the fast unittest suite.
"""
from dataclasses import dataclass, field

from scheduling.workflows.merging.compare_explanations import (ExplanationLine,
                                                               build_explanation_lines)
from scheduling.workflows.parsing.explain_schedule import (get_explanation_from_schedule,
                                                           schedule_item_sort_key)
from scheduling.workflows.parsing.schedules import ScheduleItem, SchedulesList

OTHER_CHURCH_DESC = 'Autre église'
UNKNOWN_CHURCH_DESC = 'Église inconnue'

PARSING_FLAG_LABELS = [
    ('possible_by_appointment', 'Sur rendez-vous'),
    ('is_related_to_mass', 'Lié à la messe'),
    ('is_related_to_adoration', "Lié à l'adoration"),
    ('is_related_to_permanence', 'Lié à une permanence'),
    ('will_be_seasonal_events', 'Évènements saisonniers'),
]


def get_church_desc(church_id: int | None, church_desc_by_id: dict[int, str]) -> str:
    if church_id in church_desc_by_id:
        return church_desc_by_id[church_id]
    if church_id == -1:
        return OTHER_CHURCH_DESC

    return UNKNOWN_CHURCH_DESC


def safe_explanation(schedule: ScheduleItem) -> str:
    """get_explanation_from_schedule, but never raising.

    It legitimately raises on a schedule it cannot phrase (an unimplemented frequency, a period
    missing from get_name_by_period). The copilot re-renders every past item on each page load, so
    one such schedule stored in a proposed tool call would 500 the whole discussion.
    """
    try:
        return get_explanation_from_schedule(schedule)
    except (ValueError, KeyError) as e:
        return f'⚠️ Horaire inexplicable : {e}'


@dataclass
class ChurchExplanationDiff:
    church_desc: str
    before_lines: list[ExplanationLine]
    after_lines: list[ExplanationLine]
    differs: bool


@dataclass
class FlagDiff:
    label: str
    before_on: bool
    after_on: bool
    differs: bool


@dataclass
class SchedulesListDiff:
    church_diffs: list[ChurchExplanationDiff] = field(default_factory=list)
    flag_diffs: list[FlagDiff] = field(default_factory=list)
    any_differs: bool = False


def _sort_key(schedule: ScheduleItem) -> tuple:
    """schedule_item_sort_key, but never raising, and total.

    It raises on the same schedules safe_explanation cannot phrase; those are pushed to the end,
    and the explanation text breaks ties so the order stays stable across renders.
    """
    try:
        return 0, schedule_item_sort_key(schedule), safe_explanation(schedule)
    except (ValueError, KeyError):
        return 1, (), safe_explanation(schedule)


def sort_schedules(schedules: list[ScheduleItem]) -> list[ScheduleItem]:
    """The reading order of the public display (regular rules first, then dates chronologically),
    rather than the storage order or an alphabetical one, where 'le lundi' would precede
    'le mardi 3 janvier'."""
    return sorted(schedules, key=_sort_key)


def explain_schedules(schedules_list: SchedulesList | None,
                      church_desc_by_id: dict[int, str]) -> list[str]:
    """One '<église> : <explication>' line per schedule, in display order."""
    return [f'{get_church_desc(s.church_id, church_desc_by_id)} : {safe_explanation(s)}'
            for s in sort_schedules(schedules_list.schedules if schedules_list else [])]


def get_explanations_by_church_desc(schedules_list: SchedulesList | None,
                                    church_desc_by_id: dict[int, str]) -> dict[str, list[str]]:
    explanations_by_church_desc = {}
    for schedule in sort_schedules(schedules_list.schedules if schedules_list else []):
        church_desc = get_church_desc(schedule.church_id, church_desc_by_id)
        explanations_by_church_desc.setdefault(church_desc, []).append(safe_explanation(schedule))

    return explanations_by_church_desc


def build_schedules_list_diff(before: SchedulesList | None, after: SchedulesList | None,
                              church_desc_by_id: dict[int, str]) -> SchedulesListDiff:
    """Compare the explanations of the current schedules with the proposed ones, church by church.

    `before` is None when the parsing has neither a human nor an LLM json yet.
    """
    before_by_desc = get_explanations_by_church_desc(before, church_desc_by_id)
    after_by_desc = get_explanations_by_church_desc(after, church_desc_by_id)

    church_diffs = []
    for church_desc in set(before_by_desc) | set(after_by_desc):
        before_explanations = before_by_desc.get(church_desc, [])
        after_explanations = after_by_desc.get(church_desc, [])
        church_diffs.append(ChurchExplanationDiff(
            church_desc=church_desc,
            before_lines=build_explanation_lines(before_explanations, after_explanations),
            after_lines=build_explanation_lines(after_explanations, before_explanations),
            differs=before_explanations != after_explanations,
        ))
    church_diffs.sort(key=lambda c: (not c.differs, c.church_desc))

    flag_diffs = []
    for attribute_name, label in PARSING_FLAG_LABELS:
        before_on = bool(getattr(before, attribute_name, False)) if before else False
        after_on = bool(getattr(after, attribute_name, False)) if after else False
        flag_diffs.append(FlagDiff(
            label=label,
            before_on=before_on,
            after_on=after_on,
            differs=before_on != after_on,
        ))

    return SchedulesListDiff(
        church_diffs=church_diffs,
        flag_diffs=flag_diffs,
        any_differs=any(c.differs for c in church_diffs) or any(f.differs for f in flag_diffs),
    )
