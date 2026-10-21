import json
import urllib.error
from unittest import mock

from django.test import SimpleTestCase, override_settings

from codenames import deepseek
from codenames.words import ENGLISH_WORDS


def response_with_words(words):
    return {
        'choices': [{
            'message': {'content': json.dumps({'words': words})},
        }],
    }


EN_WORDS = ENGLISH_WORDS[:25]


@override_settings(
    DEEPSEEK_API_KEY='test-key',
    DEEPSEEK_MAX_RETRIES=2,
    DEEPSEEK_TIMEOUT=1,
)
class DeepSeekGenerationTests(SimpleTestCase):
    @mock.patch('codenames.deepseek.time.sleep')
    @mock.patch('codenames.deepseek._post_json')
    def test_successful_generation(self, post_json, sleep):
        post_json.return_value = response_with_words(EN_WORDS)
        words, source = deepseek.generate_words('en')
        self.assertEqual(words, EN_WORDS)
        self.assertEqual(source, 'deepseek')
        post_json.assert_called_once()
        payload = post_json.call_args.args[1]
        self.assertEqual(payload['thinking'], {'type': 'disabled'})
        self.assertGreaterEqual(payload['max_tokens'], 1000)

    @mock.patch('codenames.deepseek.time.sleep')
    @mock.patch('codenames.deepseek._post_json')
    def test_malformed_response_is_retried(self, post_json, sleep):
        post_json.side_effect = [
            {'choices': [{'message': {'content': '{"words": ["only one"]}'}}]},
            response_with_words(EN_WORDS),
        ]
        words, source = deepseek.generate_words('en')
        self.assertEqual(len(words), 25)
        self.assertEqual(source, 'deepseek')
        self.assertEqual(post_json.call_count, 2)

    @mock.patch('codenames.deepseek.time.sleep')
    @mock.patch('codenames.deepseek._post_json')
    def test_timeout_uses_fallback_after_bounded_retries(self, post_json, sleep):
        post_json.side_effect = TimeoutError('slow')
        words, source = deepseek.generate_words('en')
        self.assertEqual(source, 'fallback')
        self.assertEqual(len(words), 25)
        self.assertEqual(post_json.call_count, 3)

    @mock.patch('codenames.deepseek.time.sleep')
    @mock.patch('codenames.deepseek._post_json')
    def test_truncated_response_is_retried_then_falls_back(self, post_json, sleep):
        post_json.return_value = {
            'choices': [{
                'message': {'content': ''},
                'finish_reason': 'length',
            }],
        }
        words, source = deepseek.generate_words('en')
        self.assertEqual(source, 'fallback')
        self.assertEqual(len(words), 25)
        self.assertEqual(post_json.call_count, 3)

    @mock.patch('codenames.deepseek.time.sleep')
    @mock.patch('codenames.deepseek._post_json')
    def test_auth_error_does_not_retry(self, post_json, sleep):
        post_json.side_effect = urllib.error.HTTPError(
            'https://api.deepseek.com/chat/completions',
            401, 'Unauthorized', None, None,
        )
        words, source = deepseek.generate_words('tr')
        self.assertEqual(source, 'fallback')
        self.assertEqual(len(words), 25)
        post_json.assert_called_once()

    @override_settings(DEEPSEEK_API_KEY='')
    def test_missing_key_skips_network(self):
        words, source = deepseek.generate_words('tr')
        self.assertEqual(source, 'fallback')
        self.assertEqual(len(words), 25)
