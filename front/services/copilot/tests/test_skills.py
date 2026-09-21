"""Pure unit tests for the copilot skills. No Django / DB needed (skills.py imports only
pydantic_ai + the deps dataclass, and the parsing prompt is a plain string literal), so this runs
in the fast suite:

    python -m unittest front.services.copilot.tests.test_skills
"""
import unittest

from front.services.copilot.skills import (FIX_PARSING_SCHEDULES_ID, SKILLS,
                                           _parsing_prompt_instructions, fix_parsing_schedules)


class TestFixParsingSchedulesSkill(unittest.TestCase):
    def test_is_deferred_and_catalogued(self):
        self.assertIn(fix_parsing_schedules, SKILLS)
        self.assertTrue(fix_parsing_schedules.defer_loading)
        self.assertEqual(FIX_PARSING_SCHEDULES_ID, fix_parsing_schedules.id)
        self.assertTrue(fix_parsing_schedules.description)

    def test_states_when_to_correct(self):
        static_text = fix_parsing_schedules.get_instructions()[0]
        self.assertIn("QUAND corriger", static_text)
        self.assertIn("Ne modifie un parsing QUE si le LLM de parsing s'est effectivement "
                      "trompé", static_text)
        self.assertIn("JAMAIS un parsing artificiellement", static_text)
        self.assertIn('report_bug', static_text)

    def test_carries_the_parsing_prompt_unformatted(self):
        text = _parsing_prompt_instructions()
        self.assertIn('{truncated_html}', text)
        self.assertIn('{church_description}', text)
        self.assertIn('extract the schedule of confession', text)

    def test_prompt_is_only_resolved_on_load(self):
        """The prompt is an instruction FUNCTION, not a baked-in string: it stays out of the
        module (and out of the base prompt) until the model calls load_capability."""
        instructions = fix_parsing_schedules.get_instructions()
        self.assertIs(instructions[1], _parsing_prompt_instructions)


if __name__ == '__main__':
    unittest.main()
