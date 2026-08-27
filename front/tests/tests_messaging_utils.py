"""Pure unit tests for the messaging helpers. No Django / DB needed (front.utils is ORM-free by
the dependency rules), so this runs in the fast suite."""
import unittest

from front.utils.messaging_utils import (HistoryEntry, append_conversation_footer,
                                         build_history_block, build_outbound_body,
                                         build_reply_subject, build_ses_message_id,
                                         build_thread_headers, conversation_footer,
                                         extract_conversation_uuid, first_external_address,
                                         is_automated_sender, is_same_email, parse_message_ids,
                                         parse_sender)

UUID = '3f2a1b4c-1111-2222-3333-444455556666'
OTHER_UUID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
URL = f'https://confessio.fr/messaging/{UUID}'
# Built, not spelled out: what matters is the `--` delimiter and the link, never the wording.
FOOTER = conversation_footer(URL)
QUOTED_FOOTER = '\n'.join(f'> {line}' for line in FOOTER.split('\n'))


class ExtractConversationUuidTests(unittest.TestCase):
    @staticmethod
    def get_fixtures():
        return [
            # The reply quotes our footer: this is the normal path.
            (('Merci !\n\n> --\n> Conversation : ' + URL, 'Merci !'), UUID),
            # Mailgun stripped the quote, so only body-plain still carries the link.
            ((f'Bonjour\n\n--\nConversation : {URL}', ''), UUID),
            # Nothing to latch on to: the caller opens a new conversation.
            (('Bonjour, j\'ai une question', 'Bonjour, j\'ai une question'), None),
            # A bare uuid quoted in the mail must not hijack a thread.
            ((f'mon identifiant est {OTHER_UUID}', ''), None),
            # First link wins.
            ((f'{URL}\nhttps://confessio.fr/messaging/{OTHER_UUID}', ''), UUID),
            # An empty first text falls through to the next one.
            (('', f'Conversation : {URL}'), UUID),
            (('', ''), None),
        ]

    def test_extract_conversation_uuid(self):
        for texts, expected in self.get_fixtures():
            with self.subTest(texts=texts):
                self.assertEqual(expected, extract_conversation_uuid(*texts))


class ParseSenderTests(unittest.TestCase):
    @staticmethod
    def get_fixtures():
        return [
            # Contact form: SES forces no-reply@ as From, the visitor is in Reply-To.
            (('Jean Dupont <jean@ex.fr>', '"Jean Dupont (via Confessio)" <no-reply@confessio.fr>'),
             ('Jean Dupont', 'jean@ex.fr')),
            # Plain reply: no Reply-To, From is the correspondent.
            (('', 'Jean Dupont <jean@ex.fr>'), ('Jean Dupont', 'jean@ex.fr')),
            (('', 'jean@ex.fr'), ('', 'jean@ex.fr')),
            # A Reply-To without a parseable address falls back to From.
            (('garbage', 'Jean <jean@ex.fr>'), ('Jean', 'jean@ex.fr')),
            (('', ''), ('', '')),
        ]

    def test_parse_sender(self):
        for (reply_to, from_header), expected in self.get_fixtures():
            with self.subTest(reply_to=reply_to, from_header=from_header):
                self.assertEqual(expected, parse_sender(reply_to, from_header))


class IsAutomatedSenderTests(unittest.TestCase):
    @staticmethod
    def get_fixtures():
        return [
            ('MAILER-DAEMON@confessio.fr', True),
            ('postmaster@ex.fr', True),
            ('jean@ex.fr', False),
            ('no-reply@confessio.fr', False),
        ]

    def test_is_automated_sender(self):
        for email, expected in self.get_fixtures():
            with self.subTest(email=email):
                self.assertEqual(expected, is_automated_sender(email))


class FooterAndSubjectTests(unittest.TestCase):
    def test_footer_is_a_signature_block(self):
        # The `--` delimiter is what makes Mailgun drop the footer from stripped-text, keeping it
        # out of what we display while body-plain still carries the uuid.
        body = append_conversation_footer('Bonjour', URL)
        self.assertEqual(f'Bonjour\n\n{FOOTER}', body)
        self.assertEqual(UUID, extract_conversation_uuid(body))

    def test_build_reply_subject(self):
        fixtures = [
            (('Horaires', True), 'Horaires'),
            (('Horaires', False), 'Re: Horaires'),
            # Never stack prefixes on a subject that already came back as a reply.
            (('Re: Horaires', False), 'Re: Horaires'),
            (('RE: Horaires', False), 'RE: Horaires'),
        ]
        for (subject, is_first), expected in fixtures:
            with self.subTest(subject=subject, is_first=is_first):
                self.assertEqual(expected, build_reply_subject(subject, is_first))


class ThreadingTests(unittest.TestCase):
    # Observed on a real delivery: SES replaces the Message-ID Django sets with its own, built
    # from the id it returns to the API.
    SES_ID = '011301a03ee56b39-7bb2ff5c-a7fe-475a-b30f-e9d125c462b9-000000'
    DELIVERED = f'<{SES_ID}@eu-west-3.amazonses.com>'

    def test_build_ses_message_id(self):
        self.assertEqual(self.DELIVERED, build_ses_message_id(self.SES_ID, 'eu-west-3'))
        # A send that told us nothing must not fabricate an id nobody will ever match.
        self.assertEqual('', build_ses_message_id('', 'eu-west-3'))
        self.assertEqual('', build_ses_message_id(self.SES_ID, ''))

    def test_build_thread_headers(self):
        first, second = self.DELIVERED, '<second@eu-west-3.amazonses.com>'
        fixtures = [
            # Opening a thread: nothing to point at.
            ([], {}),
            ([first], {'In-Reply-To': first, 'References': first}),
            ([first, second],
             {'In-Reply-To': second, 'References': f'{first} {second}'}),
            # A failed send leaves no id behind: skip the gap rather than emit an empty reference.
            ([first, '', second],
             {'In-Reply-To': second, 'References': f'{first} {second}'}),
            ([''], {}),
        ]
        for previous, expected in fixtures:
            with self.subTest(previous=previous):
                self.assertEqual(expected, build_thread_headers(previous))


class FirstExternalAddressTests(unittest.TestCase):
    OURS = ('contact@confessio.fr', 'archive@confessio.fr', 'no-reply@confessio.fr')

    def get_fixtures(self):
        return [
            # A reply copied to the archive address: the correspondent is the other recipient.
            (('Jean Dupont <jean@ex.fr>, archive@confessio.fr', self.OURS),
             ('Jean Dupont', 'jean@ex.fr')),
            # Whatever the order, and whatever the case of our own address.
            (('Archive <ARCHIVE@confessio.fr>, jean@ex.fr', self.OURS), ('', 'jean@ex.fr')),
            (('Jean <jean@ex.fr>', self.OURS), ('Jean', 'jean@ex.fr')),
            # Several correspondents: the first one wins.
            (('jean@ex.fr, marie@ex.fr', self.OURS), ('', 'jean@ex.fr')),
            # Nobody but us: a conversation talking to itself is worse than none.
            (('contact@confessio.fr, archive@confessio.fr', self.OURS), ('', '')),
            (('', self.OURS), ('', '')),
            (('garbage', self.OURS), ('', '')),
        ]

    def test_first_external_address(self):
        for (header, ours), expected in self.get_fixtures():
            with self.subTest(header=header):
                self.assertEqual(expected, first_external_address(header, ours))


class ParseMessageIdsTests(unittest.TestCase):
    FIRST = '<first@eu-west-3.amazonses.com>'
    SECOND = '<second@mailgun.org>'
    THIRD = '<third@ex.fr>'

    def get_fixtures(self):
        return [
            (('', ''), []),
            ((self.THIRD, ''), [self.THIRD]),
            # References runs oldest first: the closest ancestor is the likeliest to be ours.
            (('', f'{self.FIRST} {self.SECOND} {self.THIRD}'),
             [self.THIRD, self.SECOND, self.FIRST]),
            # In-Reply-To is read first, and the duplicate it shares with References is dropped.
            ((self.THIRD, f'{self.FIRST} {self.THIRD}'), [self.THIRD, self.FIRST]),
            # Folded headers: real clients wrap References over several lines.
            (('', f'{self.FIRST}\n\t{self.SECOND}'), [self.SECOND, self.FIRST]),
            # Not a Message-ID: no brackets, or no @.
            (('first@ex.fr', '<notanid>'), []),
        ]

    def test_parse_message_ids(self):
        for headers, expected in self.get_fixtures():
            with self.subTest(headers=headers):
                self.assertEqual(expected, parse_message_ids(*headers))


class IsSameEmailTests(unittest.TestCase):
    @staticmethod
    def get_fixtures():
        return [
            (('no-reply@confessio.fr', 'no-reply@confessio.fr'), True),
            # The display name is noise, and mailbox comparison is case-insensitive.
            (('"Jean (via Confessio)" <No-Reply@Confessio.fr>', 'no-reply@confessio.fr'), True),
            (('contact@confessio.fr', 'no-reply@confessio.fr'), False),
            # An unparseable or missing header matches nothing, itself included.
            (('', ''), False),
            (('garbage', 'garbage'), False),
        ]

    def test_is_same_email(self):
        for (one, other), expected in self.get_fixtures():
            with self.subTest(one=one, other=other):
                self.assertEqual(expected, is_same_email(one, other))


def inbound(body):
    return HistoryEntry(label='Jean Dupont', sent_at='27/08/2026 à 14:35', body=body,
                        is_outbound=False)


def outbound(body):
    return HistoryEntry(label='Confessio', sent_at='27/08/2026 à 14:32', body=body,
                        is_outbound=True)


class BuildHistoryBlockTests(unittest.TestCase):
    def test_empty_history(self):
        self.assertEqual('', build_history_block([], URL))

    def test_most_recent_first(self):
        # Entries come in chronological order and are quoted the way a mail client does it.
        block = build_history_block([inbound('Bonjour'), outbound('Bonsoir')], URL)
        self.assertEqual('Le 27/08/2026 à 14:32, Confessio a écrit :\n'
                         '> Bonsoir\n'
                         '>\n'
                         f'{QUOTED_FOOTER}\n'
                         '\n'
                         'Le 27/08/2026 à 14:35, Jean Dupont a écrit :\n'
                         '> Bonjour', block)

    def test_only_the_first_outbound_carries_the_footer(self):
        # It is the only mail that ever went out with one, so it is the only one to render with it.
        block = build_history_block([outbound('Un'), inbound('Deux'), outbound('Trois')], URL)
        self.assertEqual(1, block.count(URL))
        self.assertIn(f'> Un\n>\n{QUOTED_FOOTER}', block)

    def test_an_inbound_only_history_has_no_footer(self):
        self.assertNotIn(URL, build_history_block([inbound('Bonjour')], URL))

    def test_multiline_bodies_are_quoted_line_by_line(self):
        block = build_history_block([inbound('Bonjour,\n\nUne question ?')], URL)
        self.assertEqual('Le 27/08/2026 à 14:35, Jean Dupont a écrit :\n'
                         '> Bonjour,\n'
                         '>\n'
                         '> Une question ?', block)


class BuildOutboundBodyTests(unittest.TestCase):
    def test_footer_on_the_first_mail_of_a_thread(self):
        self.assertEqual(f'Bonjour\n\n{FOOTER}', build_outbound_body('Bonjour', [], URL))

    def test_footer_when_the_history_does_not_carry_the_link_yet(self):
        body = build_outbound_body('Bonjour', [inbound('Une question ?')], URL)
        self.assertEqual(1, body.count(URL))
        self.assertIn(f'Bonjour\n\n{FOOTER}\n\nLe 27/08', body)

    def test_no_second_footer_once_the_history_carries_the_link(self):
        body = build_outbound_body('Ma réponse', [outbound('Bonjour'), inbound('Merci')], URL)
        self.assertEqual(1, body.count(URL))
        self.assertTrue(body.startswith('Ma réponse\n\nLe 27/08'))

    def test_always_footer_forces_the_link(self):
        # The mails we mirror to the contact mailbox exist to hand it the link.
        body = build_outbound_body('', [outbound('Bonjour')], URL, always_footer=True)
        self.assertEqual(2, body.count(URL))
        self.assertTrue(body.startswith(f'{FOOTER}\n\nLe 27/08'))

    def test_the_link_survives_a_round_trip(self):
        body = build_outbound_body('Ma réponse', [outbound('Bonjour'), inbound('Merci')], URL)
        self.assertEqual(UUID, extract_conversation_uuid(body))


if __name__ == '__main__':
    unittest.main()
