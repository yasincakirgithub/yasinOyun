from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
import unicodedata
from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse

logger = logging.getLogger(__name__)

_ROOM_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
_CONTROL_RE = re.compile(r'[\x00-\x1f\x7f]')


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = 'invalid_request'):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


def generate_room_code(length: int = 6) -> str:
    return ''.join(secrets.choice(_ROOM_ALPHABET) for _ in range(length))


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256((token or '').encode('utf-8')).hexdigest()


def clean_display_name(value) -> str:
    text = unicodedata.normalize('NFKC', str(value or ''))
    text = _CONTROL_RE.sub(' ', text)
    text = text.replace('<', '').replace('>', '')
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        raise ApiError('Görünen ad gerekli.', 400, 'name_required')
    if len(text) > 30:
        text = text[:30].strip()
    if not text:
        raise ApiError('Görünen ad gerekli.', 400, 'name_required')
    return text


def name_key(value: str) -> str:
    text = unicodedata.normalize('NFKC', str(value or '')).casefold()
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:60]


def clean_chat_text(value) -> str:
    text = unicodedata.normalize('NFC', str(value or ''))
    text = _CONTROL_RE.sub(' ', text)
    text = text.replace('<', '').replace('>', '')
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        raise ApiError('Mesaj boş olamaz.', 400, 'empty_message')
    if len(text) > 400:
        text = text[:400]
    return text


def parse_json_body(request, max_bytes: int = 16384) -> dict:
    if len(request.body or b'') > max_bytes:
        raise ApiError('İstek gövdesi çok büyük.', 413, 'payload_too_large')
    try:
        data = json.loads((request.body or b'{}').decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ApiError('Geçersiz JSON.', 400, 'invalid_json') from exc
    if not isinstance(data, dict):
        raise ApiError('Geçersiz istek.', 400, 'invalid_json')
    return data


def client_ip(scope_or_request) -> str:
    if hasattr(scope_or_request, 'META'):
        return scope_or_request.META.get('REMOTE_ADDR', '') or 'unknown'
    client = scope_or_request.get('client') if isinstance(scope_or_request, dict) else None
    return (client[0] if client else '') or 'unknown'


def allow_rate(key: str, limit: int, window: int) -> bool:
    """Small cache-backed fixed-window limiter (works with LocMem or Redis)."""
    cache_key = f'codenames:rl:{key}'
    try:
        if cache.add(cache_key, 1, timeout=window):
            return True
        try:
            value = cache.incr(cache_key)
        except ValueError:
            cache.set(cache_key, 1, timeout=window)
            return True
        return value <= limit
    except Exception as exc:  # pragma: no cover - cache outage must not stop play
        logger.warning('Codenames rate limiter unavailable: %s', type(exc).__name__)
        return True


def bearer_token(headers) -> str:
    raw = headers.get('Authorization') or headers.get('authorization') or ''
    if raw.lower().startswith('bearer '):
        return raw[7:].strip()
    return ''


def _origin_host(value: str) -> str:
    parsed = urlparse(value)
    return (parsed.hostname or '').lower()


def origin_is_allowed(origin: str | None, request_host: str | None = None) -> bool:
    """Validate browser Origins for WebSockets.

    Requests without an Origin header come from non-browser clients and are
    allowed; token authentication still protects the room. When an Origin is
    present it must match the request Host (same-origin), ALLOWED_HOSTS or
    CSRF_TRUSTED_ORIGINS. The same-origin check keeps LAN IPs and reverse
    proxies working without weakening token authentication.
    """
    if not origin:
        return True
    host = _origin_host(origin)
    if not host:
        return False
    if request_host:
        request_hostname = _origin_host(f'//{request_host}')
        if request_hostname and host == request_hostname:
            return True
    allowed_origins = {o.rstrip('/') for o in getattr(settings, 'CSRF_TRUSTED_ORIGINS', [])}
    if origin.rstrip('/') in allowed_origins:
        return True
    allowed_hosts = [h.lower() for h in getattr(settings, 'ALLOWED_HOSTS', [])]
    if '*' in allowed_hosts:
        return True
    for entry in allowed_hosts:
        if entry.startswith('.'):
            if host == entry[1:] or host.endswith(entry):
                return True
        elif host == entry:
            return True
    if getattr(settings, 'DEBUG', False) and host in ('localhost', '127.0.0.1', '::1'):
        return True
    return False


def error_response(error: Exception) -> JsonResponse:
    if isinstance(error, ApiError):
        return JsonResponse(
            {'success': False, 'error': error.message, 'code': error.code},
            status=error.status,
        )
    return JsonResponse(
        {'success': False, 'error': 'Beklenmeyen bir hata oluştu.', 'code': 'server_error'},
        status=500,
    )
