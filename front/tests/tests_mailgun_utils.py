"""Pure unit tests for the Mailgun payload helpers. No Django / DB needed, so this runs in the
fast suite."""
import unittest

from front.utils.mailgun_utils import get_field

# What the stored-message API answers with: RFC casing.
STORED = {
    'From': 'Confessio <contact@confessio.fr>',
    'To': 'Jean Dupont <jean@ex.fr>',
    'Subject': 'Re: Horaires',
    'Message-Id': '<abc@mailgun.org>',
    'body-plain': 'Bonjour',
    'stripped-text': '',
}
# What an inbound route POSTs: its own lowercase names.
ROUTED = {
    'from': 'Jean Dupont <jean@ex.fr>',
    'recipient': 'contact@confessio.fr',
    'subject': 'Horaires',
    'body-plain': 'Bonjour',
}


class GetFieldTests(unittest.TestCase):
    @staticmethod
    def get_fixtures():
        return [
            ((STORED, ('From',)), 'Confessio <contact@confessio.fr>'),
            # The same lookup must work on either spelling of the payload.
            ((STORED, ('from',)), 'Confessio <contact@confessio.fr>'),
            ((ROUTED, ('From',)), 'Jean Dupont <jean@ex.fr>'),
            ((STORED, ('Message-Id',)), '<abc@mailgun.org>'),
            # An empty value falls through to the next name, like a missing one.
            ((STORED, ('stripped-text', 'body-plain')), 'Bonjour'),
            ((STORED, ('To', 'recipient')), 'Jean Dupont <jean@ex.fr>'),
            ((ROUTED, ('To', 'recipient')), 'contact@confessio.fr'),
            ((ROUTED, ('In-Reply-To',)), ''),
            (({}, ('From',)), ''),
        ]

    def test_get_field(self):
        for (payload, names), expected in self.get_fixtures():
            with self.subTest(names=names, payload=sorted(payload)):
                self.assertEqual(expected, get_field(payload, *names))


if __name__ == '__main__':
    unittest.main()
