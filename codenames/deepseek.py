"""Server-side DeepSeek vocabulary generation with bounded retries + fallback."""

from __future__ import annotations

import json
import logging
import random
import time
import urllib.error
import urllib.request

from django.conf import settings

from .words import (
    WordValidationError,
    fallback_words,
    parse_model_json,
    validate_word_list,
)

logger = logging.getLogger(__name__)

_LANGUAGE_LABEL = {'tr': 'Turkish', 'en': 'English'}


class DeepSeekError(RuntimeError):
    pass


def _prompt(language: str) -> str:
    label = _LANGUAGE_LABEL.get(language, 'English')
    return (
        'You generate vocabulary for a Codenames-style word association game.\n\n'
        f'Generate exactly 25 distinct, recognizable, single-word entries in {label}.\n\n'
        f'Language: {label}\n\n'
        'Requirements:\n'
        '* Use common vocabulary suitable for a general audience.\n'
        '* Include a diverse mixture of objects, places, animals, professions, concepts, and everyday terms.\n'
        '* Avoid duplicates, near-duplicates, obscure terms, proper nouns, offensive terms, and overly technical vocabulary.\n'
        '* Prefer words that support multiple plausible associations.\n'
        '* Every entry must be one single word without spaces or punctuation (hyphens and apostrophes are allowed only inside a word).\n'
        '* Return only valid JSON in exactly this shape, with no extra fields and no markdown fences:\n'
        '{"words": ["word1", "word2"]}\n\n'
        'The words array must contain exactly 25 entries.'
    )


def _system_prompt() -> str:
    return (
        'You are a careful vocabulary generator. Always return valid JSON only, '
        'never prose. The JSON object must contain the single key "words".'
    )


def _post_json(url: str, payload: dict, timeout: float) -> dict:
    data = json.dumps(payload).encode('utf-8')
    request = urllib.request.Request(
        url,
        data=data,
        method='POST',
        headers={
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Bearer {settings.DEEPSEEK_API_KEY}',
            'User-Agent': 'codenames-server/1.0',
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(262145)
    if len(raw) > 262144:
        raise DeepSeekError('response_too_large')
    try:
        return json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as exc:
        raise DeepSeekError('invalid_json_response') from exc


def _request_once(language: str) -> list[str]:
    base = (settings.DEEPSEEK_BASE_URL or 'https://api.deepseek.com').rstrip('/')
    payload = {
        'model': settings.DEEPSEEK_MODEL,
        'messages': [
            {'role': 'system', 'content': _system_prompt()},
            {'role': 'user', 'content': _prompt(language)},
        ],
        'temperature': 1.0,
        'max_tokens': 1200,
        'stream': False,
        'response_format': {'type': 'json_object'},
        # Vocabulary generation needs the JSON answer, not a long reasoning
        # trace. Newer DeepSeek models enable thinking by default; leaving it
        # on can consume the token budget and truncate the word list.
        'thinking': {'type': 'disabled'},
    }
    body = _post_json(f'{base}/chat/completions', payload, settings.DEEPSEEK_TIMEOUT)
    try:
        choice = body['choices'][0]
        content = choice['message']['content']
        finish_reason = choice.get('finish_reason')
    except (KeyError, IndexError, TypeError) as exc:
        raise DeepSeekError('missing_choices') from exc
    if finish_reason == 'length':
        raise DeepSeekError('response_truncated')
    return validate_word_list(parse_model_json(content), language)


def generate_words(language: str) -> tuple[list[str], str]:
    """Return ``(words, source)``; never blocks a game indefinitely on outages.

    Validation failures are retried, transient networking errors use bounded
    exponential backoff with jitter, and authentication/configuration errors
    fall back immediately. The caller receives a safe curated list if DeepSeek
    cannot produce a valid board.
    """
    if not getattr(settings, 'DEEPSEEK_API_KEY', ''):
        logger.info('DEEPSEEK_API_KEY is not configured; using fallback vocabulary')
        return fallback_words(language), 'fallback'

    retries = max(0, int(getattr(settings, 'DEEPSEEK_MAX_RETRIES', 2)))
    attempts = retries + 1

    for attempt in range(attempts):
        try:
            words = _request_once(language)
            logger.info(
                'DeepSeek generated %s words (language=%s, attempt=%s)',
                len(words), language, attempt + 1,
            )
            return words, 'deepseek'
        except WordValidationError as exc:
            logger.warning(
                'DeepSeek vocabulary validation failed (language=%s, attempt=%s): %s',
                language, attempt + 1, exc,
            )
        except urllib.error.HTTPError as exc:
            status = exc.code
            logger.warning(
                'DeepSeek HTTP error (language=%s, attempt=%s, status=%s)',
                language, attempt + 1, status,
            )
            if status in (400, 401, 402, 403, 404, 422):
                break
        except (urllib.error.URLError, TimeoutError, DeepSeekError, OSError) as exc:
            logger.warning(
                'DeepSeek transient error (language=%s, attempt=%s): %s',
                language, attempt + 1, type(exc).__name__,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception(
                'Unexpected DeepSeek error (language=%s, attempt=%s): %s',
                language, attempt + 1, type(exc).__name__,
            )
            break

        if attempt < attempts - 1:
            time.sleep(min(4.0, 0.6 * (2 ** attempt)) + random.uniform(0.05, 0.35))

    logger.warning('Falling back to curated vocabulary (language=%s)', language)
    return fallback_words(language), 'fallback'
