import unittest
from datetime import datetime, timezone

from front.utils.messaging_utils import build_ses_message_id
from front.utils.ses_utils import (BOUNCE, COMPLAINT, DELIVERY, OPEN, build_bounce_reason,
                                   parse_ses_event, parse_ses_timestamp)

SES_ID = '011301a03ee56b39-7bb2ff5c-a7fe-475a-b30f-e9d125c462b9-000000'
# The mail was handed to SES twelve seconds before it was delivered: taking the wrong timestamp
# is the easy mistake, so every fixture below keeps the two apart.
SENT_AT = '2016-10-19T23:20:52.240Z'
EVENT_AT = '2016-10-19T23:21:04.133Z'
MAIL = {'timestamp': SENT_AT, 'messageId': SES_ID, 'destination': ['cure@paroisse.fr']}


class ParseSesTimestampTests(unittest.TestCase):
    def test_aware_results(self):
        fixtures = [
            ('2016-10-19T23:21:04.133Z', datetime(2016, 10, 19, 23, 21, 4, 133000,
                                                  tzinfo=timezone.utc)),
            ('2017-08-05T00:41:02Z', datetime(2017, 8, 5, 0, 41, 2, tzinfo=timezone.utc)),
            # No suffix at all: assume UTC rather than hand Django a naive datetime.
            ('2016-10-19T23:21:04', datetime(2016, 10, 19, 23, 21, 4, tzinfo=timezone.utc)),
        ]
        for value, expected in fixtures:
            with self.subTest(value=value):
                parsed = parse_ses_timestamp(value)
                self.assertEqual(expected, parsed)
                self.assertIsNotNone(parsed.tzinfo)

    def test_offset_is_preserved(self):
        parsed = parse_ses_timestamp('2017-08-05T00:41:02.669+02:00')
        self.assertEqual(datetime(2017, 8, 4, 22, 41, 2, 669000, tzinfo=timezone.utc), parsed)

    def test_nothing_usable(self):
        # A webhook must never raise on a payload it did not expect.
        for value in ['', None, 'not a date', '2016-13-45T99:99:99Z', 42]:
            with self.subTest(value=value):
                self.assertIsNone(parse_ses_timestamp(value))


class BuildBounceReasonTests(unittest.TestCase):
    def test_type_subtype_and_diagnostic(self):
        reason = build_bounce_reason({
            'bounceType': 'Permanent',
            'bounceSubType': 'General',
            'bouncedRecipients': [{'emailAddress': 'cure@paroisse.fr',
                                   'diagnosticCode': 'smtp; 550 5.1.1 user unknown'}],
        })
        self.assertEqual('Permanent/General — smtp; 550 5.1.1 user unknown', reason)

    def test_no_diagnostic_leaves_no_dangling_separator(self):
        reason = build_bounce_reason({'bounceType': 'Transient',
                                      'bounceSubType': 'MailboxFull',
                                      'bouncedRecipients': []})
        self.assertEqual('Transient/MailboxFull', reason)

    def test_diagnostic_without_type(self):
        reason = build_bounce_reason({'bouncedRecipients': [{'diagnosticCode': 'smtp; 550'}]})
        self.assertEqual('smtp; 550', reason)

    def test_every_field_missing(self):
        self.assertEqual('', build_bounce_reason({}))
        self.assertEqual('', build_bounce_reason({'bouncedRecipients': None}))


class ParseSesEventTests(unittest.TestCase):
    def test_delivery(self):
        event = parse_ses_event({'eventType': 'Delivery', 'mail': MAIL,
                                 'delivery': {'timestamp': EVENT_AT,
                                              'smtpResponse': '250 2.6.0 Message received'}})
        self.assertEqual(DELIVERY, event.event_type)
        self.assertEqual(SES_ID, event.ses_message_id)
        # The delivery's own timestamp, not the mail's.
        self.assertEqual(parse_ses_timestamp(EVENT_AT), event.at)
        self.assertEqual('', event.reason)

    def test_open(self):
        event = parse_ses_event({'eventType': 'Open', 'mail': MAIL,
                                 'open': {'timestamp': EVENT_AT, 'ipAddress': '192.0.2.1',
                                          'userAgent': 'Mozilla/5.0'}})
        self.assertEqual(OPEN, event.event_type)
        self.assertEqual(parse_ses_timestamp(EVENT_AT), event.at)

    def test_bounce_carries_its_reason(self):
        event = parse_ses_event({
            'eventType': 'Bounce', 'mail': MAIL,
            'bounce': {'timestamp': EVENT_AT, 'bounceType': 'Permanent',
                       'bounceSubType': 'General',
                       'bouncedRecipients': [{'diagnosticCode': 'smtp; 550 5.1.1 user unknown'}]},
        })
        self.assertEqual(BOUNCE, event.event_type)
        self.assertIn('Permanent', event.reason)
        self.assertIn('550 5.1.1', event.reason)

    def test_complaint_carries_no_reason(self):
        event = parse_ses_event({'eventType': 'Complaint', 'mail': MAIL,
                                 'complaint': {'timestamp': EVENT_AT,
                                               'complaintFeedbackType': 'abuse'}})
        self.assertEqual(COMPLAINT, event.event_type)
        self.assertEqual('', event.reason)

    def test_legacy_notification_type(self):
        """The per-identity SNS notifications name the field differently."""
        event = parse_ses_event({'notificationType': 'Bounce', 'mail': MAIL,
                                 'bounce': {'timestamp': EVENT_AT, 'bounceType': 'Permanent'}})
        self.assertEqual(BOUNCE, event.event_type)

    def test_event_body_missing_still_parses(self):
        """A timeless event is still an event: the service falls back to now()."""
        event = parse_ses_event({'eventType': 'Delivery', 'mail': MAIL})
        self.assertEqual(DELIVERY, event.event_type)
        self.assertIsNone(event.at)

    def test_ignored(self):
        fixtures = [
            # Types we subscribe to but have nothing to store for, and ones we never subscribe to.
            {'eventType': 'Send', 'mail': MAIL},
            {'eventType': 'Click', 'mail': MAIL},
            {'eventType': 'Reject', 'mail': MAIL},
            {'eventType': 'DeliveryDelay', 'mail': MAIL},
            # Without a messageId there is nothing to correlate on.
            {'eventType': 'Delivery', 'mail': {'messageId': ''}},
            {'eventType': 'Delivery', 'mail': {}},
            {'eventType': 'Delivery'},
            {'eventType': 'Delivery', 'mail': None},
            {},
        ]
        for event_message in fixtures:
            with self.subTest(event_message=event_message):
                self.assertIsNone(parse_ses_event(event_message))


class CorrelationKeyTests(unittest.TestCase):
    def test_event_message_id_matches_what_we_stored(self):
        """The whole feature hangs on this: the id SES reports back is the one we kept.

        `_send_and_record` stores build_ses_message_id(<the id SES returned>, region), and the
        event hands us that same raw id in mail.messageId.
        """
        event = parse_ses_event({'eventType': 'Delivery', 'mail': MAIL,
                                 'delivery': {'timestamp': EVENT_AT}})
        self.assertEqual(f'<{SES_ID}@eu-west-3.amazonses.com>',
                         build_ses_message_id(event.ses_message_id, 'eu-west-3'))


if __name__ == '__main__':
    unittest.main()
