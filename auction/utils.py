"""Utility functions for the Auction game."""

import re
import secrets
import hashlib
from django.utils.crypto import get_random_string


def clean_display_name(name: str) -> str:
    """Sanitize display name."""
    if not name:
        return 'Oyuncu'
    cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', name)
    cleaned = cleaned.strip()
    if len(cleaned) > 30:
        cleaned = cleaned[:30]
    return cleaned or 'Oyuncu'


def generate_room_code(length: int = 6) -> str:
    """Generate a unique room code."""
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # No confusing chars
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def hash_token(token: str) -> str:
    """Hash a session token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def name_key(name: str) -> str:
    """Normalize name for uniqueness checks."""
    return re.sub(r'\s+', '', name.lower())


def new_session_token(length: int = 32) -> str:
    """Generate a new session token."""
    return secrets.token_urlsafe(length)


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = 'error'):
        self.message = message
        self.status = status
        self.code = code
        super().__init__(message)


def clean_chat_text(text: str) -> str:
    """Sanitize chat text."""
    if not text:
        return ''
    cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)
    return cleaned[:400]


def error_response(exc: Exception) -> 'JsonResponse':
    from django.http import JsonResponse
    if isinstance(exc, ApiError):
        return JsonResponse(
            {'success': False, 'error': exc.message, 'code': exc.code},
            status=exc.status,
        )
    return JsonResponse(
        {'success': False, 'error': 'Beklenmeyen bir hata oluştu.', 'code': 'internal_error'},
        status=500,
    )


def parse_json_body(request) -> dict:
    import json
    try:
        return json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def bearer_token(headers: dict) -> str | None:
    """Extract Bearer token from Authorization header."""
    auth = headers.get('Authorization') or headers.get('HTTP_AUTHORIZATION')
    if auth and auth.startswith('Bearer '):
        return auth[7:].strip()
    return None


def client_ip(request) -> str:
    """Get client IP address."""
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')


_rate_limit_cache: dict[str, tuple[int, float]] = {}


def allow_rate(key: str, limit: int, window_seconds: int) -> bool:
    """Simple in-memory rate limiter."""
    import time
    now = time.time()
    if key in _rate_limit_cache:
        count, window_start = _rate_limit_cache[key]
        if now - window_start < window_seconds:
            if count >= limit:
                return False
            _rate_limit_cache[key] = (count + 1, window_start)
            return True
        else:
            _rate_limit_cache[key] = (1, now)
            return True
    _rate_limit_cache[key] = (1, now)
    return True


def origin_is_allowed(origin: str, request_host: str) -> bool:
    """Check if origin is allowed for WebSocket connections."""
    if not origin:
        return True  # Allow non-browser clients
    try:
        from urllib.parse import urlparse
        parsed = urlparse(origin)
        origin_host = parsed.netloc
        return origin_host == request_host
    except Exception:
        return False