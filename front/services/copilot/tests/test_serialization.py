"""Pure unit tests for the copilot item->message reconstruction. No Django / DB needed
(serialization.py imports only pydantic_ai + pure string utils), so this runs in the fast suite:

    python -m unittest front.services.copilot.tests.test_serialization
"""
import unittest

from pydantic_ai.messages import (ModelRequest, ModelResponse, TextPart, ToolCallPart,
                                  ToolReturnPart, UserPromptPart)

from front.services.copilot.serialization import (TOOL_DENIED_MESSAGE,
                                                  build_history_from_item_dicts,
                                                  deferred_tool_call_ids, dump_messages,
                                                  load_messages)


def _item(position, item_type, **kw):
    return {
        'position': position,
        'item_type': item_type,
        'text': kw.get('text', ''),
        'tool_name': kw.get('tool_name', ''),
        'tool_args': kw.get('tool_args'),
        'tool_result': kw.get('tool_result'),
        'tool_call_id': kw.get('tool_call_id', ''),
        'approval_status': kw.get('approval_status', ''),
    }


def _only_part(message):
    return message.parts[0]


class BuildHistoryTests(unittest.TestCase):
    def test_user_message(self):
        [msg] = build_history_from_item_dicts([_item(0, 'user_message', text='Salut')])
        self.assertIsInstance(msg, ModelRequest)
        self.assertIsInstance(_only_part(msg), UserPromptPart)
        self.assertEqual(_only_part(msg).content, 'Salut')

    def test_agent_message(self):
        [msg] = build_history_from_item_dicts([_item(0, 'agent_message', text='Voici')])
        self.assertIsInstance(msg, ModelResponse)
        self.assertIsInstance(_only_part(msg), TextPart)
        self.assertEqual(_only_part(msg).content, 'Voici')

    def test_autonomous_pairs_call_and_return_with_synth_id(self):
        item = _item(3, 'autonomous_tool_call', tool_name='run_sql',
                     tool_args={'query': 'select 1'}, tool_result={'rows': []})
        call_msg, return_msg = build_history_from_item_dicts([item])
        call, ret = _only_part(call_msg), _only_part(return_msg)
        self.assertIsInstance(call, ToolCallPart)
        self.assertIsInstance(ret, ToolReturnPart)
        self.assertEqual(call.tool_call_id, 'auton_3')
        self.assertEqual(ret.tool_call_id, 'auton_3')  # same id -> correctly paired
        self.assertEqual(call.args, {'query': 'select 1'})
        self.assertEqual(ret.content, {'rows': []})

    def test_proposed_approved_is_answered(self):
        item = _item(1, 'proposed_tool_call', tool_name='add_church', tool_args={'name': 'X'},
                     tool_call_id='real-1', approval_status='approved',
                     tool_result={'created_church_uuid': 'u'})
        call_msg, return_msg = build_history_from_item_dicts([item])
        self.assertEqual(_only_part(call_msg).tool_call_id, 'real-1')
        self.assertEqual(_only_part(return_msg).content, {'created_church_uuid': 'u'})

    def test_proposed_failure_is_answered_with_error(self):
        item = _item(1, 'proposed_tool_call', tool_name='add_church', tool_call_id='real-1',
                     approval_status='failure', tool_result={'error': 'boom'})
        _, return_msg = build_history_from_item_dicts([item])
        self.assertEqual(_only_part(return_msg).content, {'error': 'boom'})

    def test_proposed_rejected_is_answered_with_denial(self):
        item = _item(1, 'proposed_tool_call', tool_name='delete_church', tool_call_id='real-1',
                     approval_status='rejected')
        call_msg, return_msg = build_history_from_item_dicts([item])
        self.assertIsInstance(_only_part(return_msg), ToolReturnPart)
        self.assertEqual(_only_part(return_msg).content, TOOL_DENIED_MESSAGE)

    def test_proposed_pending_is_left_deferred(self):
        items = [_item(0, 'user_message', text='fais X'),
                 _item(1, 'proposed_tool_call', tool_name='add_church', tool_call_id='real-1',
                       approval_status='pending')]
        history = build_history_from_item_dicts(items)
        # last message is an unanswered tool call -> exactly that id is deferred.
        self.assertIsInstance(history[-1], ModelResponse)
        self.assertEqual(deferred_tool_call_ids(history), {'real-1'})

    def test_round_trips_through_serialization(self):
        items = [_item(0, 'user_message', text='q'),
                 _item(1, 'autonomous_tool_call', tool_name='run_sql',
                       tool_args={'query': 'select 1'}, tool_result={'rows': [['a']]}),
                 _item(2, 'agent_message', text='fini')]
        history = build_history_from_item_dicts(items)
        self.assertEqual(load_messages(dump_messages(history)), history)

    def test_incident_shape_is_resumable_and_complete(self):
        # Reproduce the incident: original human message + 19 autonomous calls, no final agent text
        # (the turn crashed). The rebuilt history must be resumable and carry everything.
        items = [_item(0, 'user_message', text="Il manque l'église Saint-Dominique à Bonifacio")]
        for pos in range(1, 20):
            items.append(_item(pos, 'autonomous_tool_call', tool_name='run_sql',
                               tool_args={'q': pos}, tool_result={'rows': [pos]}))
        history = build_history_from_item_dicts(items)
        # ends with a tool return (resumable "continue from history" shape)
        self.assertIsInstance(history[-1], ModelRequest)
        self.assertIsInstance(_only_part(history[-1]), ToolReturnPart)
        # original human message preserved
        prompts = [p.content for m in history for p in m.parts if isinstance(p, UserPromptPart)]
        self.assertIn("Il manque l'église Saint-Dominique à Bonifacio", prompts)
        # all 19 tool calls preserved and fully paired (nothing left deferred)
        calls = [p for m in history for p in m.parts if isinstance(p, ToolCallPart)]
        self.assertEqual(len(calls), 19)
        self.assertEqual(deferred_tool_call_ids(history), set())


if __name__ == '__main__':
    unittest.main()
