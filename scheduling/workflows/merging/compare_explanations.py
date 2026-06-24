from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from scheduling.public_model import SourcedSchedulesList

if TYPE_CHECKING:
    from registry.models import Church


FLAG_LABELS = [
    ('possible_by_appointment_sources', 'Sur rendez-vous'),
    ('is_related_to_mass_sources', 'Lié à la messe'),
    ('is_related_to_adoration_sources', "Lié à l'adoration"),
    ('is_related_to_permanence_sources', 'Lié à une permanence'),
    ('will_be_seasonal_events_sources', 'Évènements saisonniers'),
]


@dataclass
class ExplanationLine:
    text: str
    changed: bool  # validated-only (removed) or indexed-only (added)


@dataclass
class ChurchScheduleComparison:
    church_label: str
    validated_lines: list[ExplanationLine]
    indexed_lines: list[ExplanationLine]
    differs: bool


@dataclass
class FlagComparison:
    label: str
    validated_on: bool
    indexed_on: bool
    differs: bool


@dataclass
class ValidatedSchedulesComparison:
    church_comparisons: list[ChurchScheduleComparison]
    flag_comparisons: list[FlagComparison]
    any_differs: bool


def get_explanations_by_church_id(
        sourced_schedules_list: SourcedSchedulesList) -> dict[int | None, list[str]]:
    explanations_by_church_id = {}
    for sourced_schedule_of_church in sourced_schedules_list.sourced_schedules_of_churches:
        explanations_by_church_id[sourced_schedule_of_church.church_id] = sorted(
            sourced_schedule_item.explanation
            for sourced_schedule_item in sourced_schedule_of_church.sourced_schedules
        )

    return explanations_by_church_id


def get_church_label(church_id: int | None, church_by_id: 'dict[int, Church]') -> str:
    if church_id in church_by_id:
        return church_by_id[church_id].get_desc()
    if church_id == -1:
        return 'Autre église'
    if church_id is None:
        return 'Église inconnue'
    return f'Église #{church_id}'


def build_explanation_lines(own_explanations: list[str],
                            other_explanations: list[str]) -> list[ExplanationLine]:
    """Mark each explanation as changed when it is not also present (with the same
    multiplicity) on the other side."""
    other_counter = Counter(other_explanations)
    seen = Counter()
    lines = []
    for explanation in own_explanations:
        seen[explanation] += 1
        changed = seen[explanation] > other_counter[explanation]
        lines.append(ExplanationLine(text=explanation, changed=changed))

    return lines


def build_validated_schedules_comparison(
        validated_sourced_schedules_list: SourcedSchedulesList,
        indexed_sourced_schedules_list: SourcedSchedulesList,
        church_by_id: 'dict[int, Church]') -> ValidatedSchedulesComparison:
    validated_by_church_id = get_explanations_by_church_id(validated_sourced_schedules_list)
    indexed_by_church_id = get_explanations_by_church_id(indexed_sourced_schedules_list)

    church_comparisons = []
    for church_id in set(validated_by_church_id) | set(indexed_by_church_id):
        validated_explanations = validated_by_church_id.get(church_id, [])
        indexed_explanations = indexed_by_church_id.get(church_id, [])
        church_comparisons.append(ChurchScheduleComparison(
            church_label=get_church_label(church_id, church_by_id),
            validated_lines=build_explanation_lines(validated_explanations, indexed_explanations),
            indexed_lines=build_explanation_lines(indexed_explanations, validated_explanations),
            differs=validated_explanations != indexed_explanations,
        ))
    church_comparisons.sort(key=lambda c: (not c.differs, c.church_label))

    flag_comparisons = []
    for attribute_name, label in FLAG_LABELS:
        validated_on = bool(getattr(validated_sourced_schedules_list, attribute_name))
        indexed_on = bool(getattr(indexed_sourced_schedules_list, attribute_name))
        flag_comparisons.append(FlagComparison(
            label=label,
            validated_on=validated_on,
            indexed_on=indexed_on,
            differs=validated_on != indexed_on,
        ))

    any_differs = any(c.differs for c in church_comparisons) \
        or any(f.differs for f in flag_comparisons)

    return ValidatedSchedulesComparison(
        church_comparisons=church_comparisons,
        flag_comparisons=flag_comparisons,
        any_differs=any_differs,
    )
