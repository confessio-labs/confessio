from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

from front.models import CopilotDiscussion, CopilotDiscussionItem
from front.services.copilot import tools
from front.services.copilot.items import add_item


class CopilotSqlGuardTests(TestCase):
    def test_rejects_non_select(self):
        result = tools.run_readonly_sql('UPDATE registry_website SET name = name')
        self.assertIn('error', result)
        self.assertNotIn('rows', result)

    def test_rejects_empty(self):
        self.assertIn('error', tools.run_readonly_sql('   '))

    def test_allows_select_keyword(self):
        # A real SELECT goes through to the DB layer (no guard error). Whatever the result,
        # it must not be rejected by the read-only guard.
        result = tools.run_readonly_sql('SELECT 1')
        self.assertNotEqual(result.get('error'), 'Only read-only SELECT/WITH queries are allowed.')


class CopilotItemOrderingTests(TestCase):
    def test_positions_are_monotonic(self):
        discussion = CopilotDiscussion.objects.create(title='t')
        a = add_item(discussion, CopilotDiscussionItem.ItemType.USER_MESSAGE, text='hello')
        b = add_item(discussion, CopilotDiscussionItem.ItemType.AGENT_MESSAGE, text='hi')
        self.assertEqual(a.position, 0)
        self.assertEqual(b.position, 1)


class CopilotViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('admin', password='pw')
        perm = Permission.objects.get(
            content_type__app_label='scheduling', codename='change_sentence')
        self.admin.user_permissions.add(perm)
        self.other = User.objects.create_user('other', password='pw')

    def test_requires_permission(self):
        self.client.login(username='other', password='pw')
        response = self.client.get(reverse('copilot'))
        self.assertEqual(response.status_code, 302)  # redirected to login

    def test_admin_can_open_page(self):
        self.client.login(username='admin', password='pw')
        response = self.client.get(reverse('copilot'))
        self.assertEqual(response.status_code, 200)

    @patch('front.views.copilot_views.worker_run_copilot_turn')
    def test_new_discussion_enqueues_worker(self, mock_worker):
        self.client.login(username='admin', password='pw')
        response = self.client.post(reverse('copilot_new'), {'text': 'église sans horaire'})
        self.assertEqual(response.status_code, 200)
        discussion = CopilotDiscussion.objects.get()
        self.assertEqual(discussion.status, CopilotDiscussion.Status.RUNNING)
        self.assertEqual(discussion.items.count(), 1)
        mock_worker.assert_called_once()

    @patch('front.views.copilot_views.worker_resume_copilot_turn')
    def test_approve_proposed_item(self, mock_resume):
        self.client.login(username='admin', password='pw')
        discussion = CopilotDiscussion.objects.create(
            user=self.admin, status=CopilotDiscussion.Status.AWAITING_APPROVAL)
        item = add_item(
            discussion, CopilotDiscussionItem.ItemType.PROPOSED_TOOL_CALL,
            tool_name='trigger_recrawl', tool_call_id='call_1',
            approval_status=CopilotDiscussionItem.ApprovalStatus.PENDING)
        response = self.client.post(
            reverse('copilot_approve', args=[discussion.uuid]),
            {'item_uuid': str(item.uuid), 'decision': 'approve'})
        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.approval_status, CopilotDiscussionItem.ApprovalStatus.APPROVED)
        mock_resume.assert_called_once_with(str(discussion.uuid), 'call_1', True)

    def test_items_polling_returns_new_items(self):
        self.client.login(username='admin', password='pw')
        discussion = CopilotDiscussion.objects.create(user=self.admin)
        add_item(discussion, CopilotDiscussionItem.ItemType.AGENT_MESSAGE, text='salut')
        response = self.client.get(
            reverse('copilot_items', args=[discussion.uuid]), {'since': -1})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['last_position'], 0)
        self.assertIn('salut', data['html'])
