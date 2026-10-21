from django.test import SimpleTestCase

from codenames.words import (
    WordValidationError,
    fallback_words,
    normalize_word,
    parse_model_json,
    validate_word_list,
    TURKISH_WORDS,
)


class WordValidationTests(SimpleTestCase):
    def test_valid_list(self):
        words = [f'word{chr(97 + i)}' for i in range(25)]
        self.assertEqual(validate_word_list(words, 'en'), words)

    def test_turkish_characters_are_accepted(self):
        words = [f'çiçek{chr(97 + i)}' for i in range(25)]
        self.assertEqual(len(validate_word_list(words, 'tr')), 25)

    def test_rejects_duplicates_case_and_diacritics(self):
        words = [f'word{chr(97 + i)}' for i in range(24)] + ['WORDA']
        with self.assertRaises(WordValidationError):
            validate_word_list(words, 'en')
        words = [f'kelime{chr(97 + i)}' for i in range(24)] + ['KELİMEA']
        with self.assertRaises(WordValidationError):
            validate_word_list(words, 'tr')

    def test_rejects_wrong_count(self):
        with self.assertRaises(WordValidationError):
            validate_word_list([f'w{chr(97 + i)}' for i in range(24)], 'en')

    def test_rejects_spaces_numbers_and_turkish_in_english(self):
        for bad in ('two words', 'word1', 'çiçek'):
            words = [f'word{chr(97 + i)}' for i in range(24)] + [bad]
            with self.assertRaises(WordValidationError):
                validate_word_list(words, 'en')

    def test_rejects_non_strings(self):
        words = [f'word{chr(97 + i)}' for i in range(24)] + [42]
        with self.assertRaises(WordValidationError):
            validate_word_list(words, 'en')

    def test_parse_json_accepts_fences(self):
        content = '```json\n{"words": ["a", "b"]}\n```'
        self.assertEqual(parse_model_json(content), ['a', 'b'])

    def test_parse_json_rejects_extra_fields(self):
        with self.assertRaises(WordValidationError):
            parse_model_json('{"words": ["a"], "extra": true}')

    def test_fallback_pool_is_fresh_and_large_enough(self):
        first = fallback_words('tr')
        second = fallback_words('tr')
        self.assertEqual(len(first), 25)
        self.assertEqual(len(set(first)), 25)
        self.assertNotEqual(first, second)
        self.assertEqual(len(fallback_words('en')), 25)

    def test_turkish_fallback_pool_has_extra_vocabulary(self):
        self.assertGreaterEqual(len(TURKISH_WORDS), 350)
        self.assertEqual(
            len(TURKISH_WORDS),
            len({normalize_word(word) for word in TURKISH_WORDS}),
        )

    def test_normalization(self):
        self.assertEqual(normalize_word('KİTAP'), normalize_word('kitap'))
        self.assertEqual(normalize_word('Çiçek'), normalize_word('cicek'))
