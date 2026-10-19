"""Exercise semantic numeric classes and traceable user normalization."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/training'))
from number_surface import normalize_user_text, validate_surface


class NumberSurfaceTests(unittest.TestCase):
    def test_spoken_forms(self):
        cases = {
            'There are 42 people.': 'There are forty two people.',
            'In 2002, it happened.': 'In two thousand two, it happened.',
            'Since 1889.': 'Since eighteen eighty nine.',
            'In 2026.': 'In twenty twenty six.',
            'Pay 2002 dollars.': 'Pay two thousand two dollars.',
            'At 09:30 AM.': 'At nine thirty AM.',
            'At 06:05.': 'At six oh five.',
            'At 07:00.': "At seven o'clock.",
            'At 9:30am.': 'At nine thirty AM.',
            'Read pages 1-5.': 'Read pages one to five.',
            'At 23:59:01.': 'At twenty three fifty nine and one second.',
            'The price is $42.50.': 'The price is forty two dollars and fifty cents.',
            'Pay £1.01 and €2.00.': 'Pay one pound and one penny and two euros.',
            'Discount 12.5%.': 'Discount twelve point five percent.',
            'Use 3.14 and -2.5.': 'Use three point one four and minus two point five.',
            'Read 0012.': 'Read zero zero one two.',
            'Phone: 555-123-4567.': 'Phone: five five five one two three four five six seven.',
            'Call +1 (555) 123-4567.': 'Call plus one five five five one two three four five six seven.',
            'PIN is 1234.': 'PIN is one two three four.',
            'It is the 21st item.': 'It is the twenty first item.',
            'On 2026-10-19.': 'On October nineteenth twenty twenty six.',
            'On October 19, 2026.': 'On October nineteenth twenty twenty six.',
            'On 19 October 2026.': 'On nineteenth October twenty twenty six.',
            'On 19/10/2026.': 'On October nineteenth twenty twenty six.',
            "I'll call at 9:30; we're ready.": "I'll call at nine thirty; we're ready.",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                result = normalize_user_text(text)
                self.assertEqual(result['text'], expected)
                validate_surface(result)

    def test_ambiguous_or_unsupported_input_is_rejected(self):
        for text in ['On 03/04/2026.', 'On 2026-02-30.', 'At 25:00.',
                     'At 13:00 PM.', 'Version 1.2.3.', 'Use GPT4.',
                     'Use 1e3.', 'Read https://example.org/2002.', '```x = 2```',
                     'Use 1/2 cup.', 'Compute 2+2.', 'What is 2-3?', 'Pay ¥42.']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                normalize_user_text(text)

    def test_mapping_tampering_is_rejected(self):
        result = normalize_user_text('Meet at 09:30 and pay $42.50.')
        result['replacements'][0]['normalized_start'] += 1
        with self.assertRaises(ValueError):
            validate_surface(result)


if __name__ == '__main__':
    unittest.main()
