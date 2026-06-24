import unittest

from scheduling.public_model import SourcedSchedulesList, SourcedScheduleItem, \
    SourcedSchedulesOfChurch
from scheduling.workflows.merging.compare_explanations import \
    get_explanations_by_church_id, build_explanation_lines, get_church_label, \
    build_validated_schedules_comparison
from scheduling.workflows.parsing.schedules import OneOffRule, ScheduleItem


def make_sourced_schedule_item(explanation: str, church_id: int | None) -> SourcedScheduleItem:
    return SourcedScheduleItem(
        item=ScheduleItem(church_id=church_id, date_rule=OneOffRule(month=1, day=1)),
        explanation=explanation,
        sources=[],
    )


def make_sourced_schedules_list(explanations_by_church_id: dict[int | None, list[str]]
                                ) -> SourcedSchedulesList:
    return SourcedSchedulesList(
        sourced_schedules_of_churches=[
            SourcedSchedulesOfChurch(
                church_id=church_id,
                sourced_schedules=[
                    make_sourced_schedule_item(explanation, church_id)
                    for explanation in explanations
                ],
            )
            for church_id, explanations in explanations_by_church_id.items()
        ],
        possible_by_appointment_sources=[],
        is_related_to_mass_sources=[],
        is_related_to_adoration_sources=[],
        is_related_to_permanence_sources=[],
        will_be_seasonal_events_sources=[],
    )


class ValidatedSchedulesComparisonTests(unittest.TestCase):
    def test_get_explanations_by_church_id_groups_and_sorts(self):
        sourced_schedules_list = make_sourced_schedules_list({
            1: ['samedi 10:00', 'lundi 09:00'],
            2: ['mardi 18:00'],
        })

        explanations_by_church_id = get_explanations_by_church_id(sourced_schedules_list)

        self.assertEqual(explanations_by_church_id, {
            1: ['lundi 09:00', 'samedi 10:00'],
            2: ['mardi 18:00'],
        })

    def test_build_explanation_lines_marks_only_unmatched(self):
        validated = ['lundi 09:00', 'samedi 10:00']
        indexed = ['samedi 10:00', 'mardi 18:00']

        validated_lines = build_explanation_lines(validated, indexed)
        indexed_lines = build_explanation_lines(indexed, validated)

        self.assertEqual([(line.text, line.changed) for line in validated_lines],
                         [('lundi 09:00', True), ('samedi 10:00', False)])
        self.assertEqual([(line.text, line.changed) for line in indexed_lines],
                         [('samedi 10:00', False), ('mardi 18:00', True)])

    def test_build_explanation_lines_respects_multiplicity(self):
        validated = ['samedi 10:00', 'samedi 10:00']
        indexed = ['samedi 10:00']

        validated_lines = build_explanation_lines(validated, indexed)

        # The second duplicate has no counterpart on the other side.
        self.assertEqual([line.changed for line in validated_lines], [False, True])

    def test_get_church_label_fallbacks(self):
        self.assertEqual(get_church_label(-1, {}), 'Autre église')
        self.assertEqual(get_church_label(None, {}), 'Église inconnue')
        self.assertEqual(get_church_label(42, {}), 'Église #42')

    def test_build_validated_schedules_comparison_end_to_end(self):
        class FakeChurch:
            def __init__(self, desc):
                self._desc = desc

            def get_desc(self):
                return self._desc

        validated = make_sourced_schedules_list({
            1: ['samedi 10:00'],
            2: ['mardi 18:00'],
        })
        indexed = make_sourced_schedules_list({
            1: ['samedi 10:00'],
            2: ['mardi 19:00'],
        })
        church_by_id = {1: FakeChurch('Saint-Pierre'), 2: FakeChurch('Notre-Dame')}

        comparison = build_validated_schedules_comparison(validated, indexed, church_by_id)

        # Differing church surfaces first, identical one last.
        labels = [c.church_label for c in comparison.church_comparisons]
        self.assertEqual(labels, ['Notre-Dame', 'Saint-Pierre'])
        self.assertTrue(comparison.church_comparisons[0].differs)
        self.assertFalse(comparison.church_comparisons[1].differs)
        self.assertTrue(comparison.any_differs)
        # Flags are all off on both sides -> no flag differs.
        self.assertFalse(any(f.differs for f in comparison.flag_comparisons))


if __name__ == '__main__':
    unittest.main()
