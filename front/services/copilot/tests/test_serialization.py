"""Pure unit tests for the copilot message-history helpers. No Django / DB needed
(serialization.py imports only pydantic_ai + pure string utils), so this runs in the fast suite:

    python -m unittest front.services.copilot.tests.test_serialization
"""
import unittest

from pydantic_ai.messages import (ModelRequest, ModelResponse, TextPart, ToolCallPart,
                                  ToolReturnPart, UserPromptPart)

from front.services.copilot.serialization import (dump_messages, is_resumable_history,
                                                  latest_user_prompt, load_messages)


def _user(text):
    return ModelRequest(parts=[UserPromptPart(content=text)])


def _tool_return(tool_call_id='c1', text=None):
    return ModelRequest(parts=[ToolReturnPart(
        tool_name='run_sql', content={'rows': []}, tool_call_id=tool_call_id)]
        + ([UserPromptPart(content=text)] if text else []))


def _tool_call(tool_call_id='c1'):
    return ModelResponse(parts=[ToolCallPart(
        tool_name='run_sql', args={'query': 'select 1'}, tool_call_id=tool_call_id)])


class LatestUserPromptTests(unittest.TestCase):
    def test_empty(self):
        self.assertIsNone(latest_user_prompt([]))

    def test_single(self):
        self.assertEqual(latest_user_prompt([_user('x')]), 'x')

    def test_returns_most_recent(self):
        history = [_user('first'), _tool_call(), _tool_return(), _user('second')]
        self.assertEqual(latest_user_prompt(history), 'second')

    def test_prompt_merged_with_tool_returns(self):
        # A ModelRequest carrying both a tool return and a user prompt (the resume-merge shape).
        history = [_user('first'), _tool_call(), _tool_return(text='again')]
        self.assertEqual(latest_user_prompt(history), 'again')

    def test_none_when_no_user_prompt(self):
        self.assertIsNone(latest_user_prompt([_tool_call(), _tool_return()]))


class IsResumableHistoryTests(unittest.TestCase):
    def test_empty_is_resumable(self):
        self.assertTrue(is_resumable_history([]))

    def test_trailing_tool_return_request_is_resumable(self):
        # The real incident shape: crash during a model request after tool returns landed.
        self.assertTrue(is_resumable_history([_user('q'), _tool_call(), _tool_return()]))

    def test_trailing_text_response_is_resumable(self):
        history = [_user('q'), ModelResponse(parts=[TextPart(content='done')])]
        self.assertTrue(is_resumable_history(history))

    def test_trailing_tool_call_is_not_resumable(self):
        # Crash during tool execution: unanswered tool call → PydanticAI would refuse to resume.
        self.assertFalse(is_resumable_history([_user('q'), _tool_call()]))

    def test_trailing_tool_call_with_text_is_not_resumable(self):
        history = [_user('q'), ModelResponse(parts=[
            ToolCallPart(tool_name='run_sql', args={}, tool_call_id='c1'),
            TextPart(content='let me check')])]
        self.assertFalse(is_resumable_history(history))


class RoundTripTests(unittest.TestCase):
    def test_partial_history_round_trips(self):
        # A realistic partial history (user → tool call → tool return) must serialize and reload
        # unchanged, so the persisted partial memory stays valid on resume.
        history = [_user('q'), _tool_call(), _tool_return()]
        reloaded = load_messages(dump_messages(history))
        self.assertEqual(reloaded, history)


if __name__ == '__main__':
    unittest.main()
