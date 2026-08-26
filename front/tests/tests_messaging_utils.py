"""Pure unit tests for the messaging helpers. No Django / DB needed (front.utils is ORM-free by
the dependency rules), so this runs in the fast suite."""
import unittest

from front.utils.messaging_utils import (append_conversation_footer, build_reply_subject,
                                         extract_conversation_uuid, is_automated_sender,
                                         parse_sender)

UUID = '3f2a1b4c-1111-2222-3333-444455556666'
OTHER_UUID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
URL = f'https://confessio.fr/messaging/{UUID}'


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
        self.assertEqual(f'Bonjour\n\n--\nConversation : {URL}', body)
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


if __name__ == '__main__':
    unittest.main()
