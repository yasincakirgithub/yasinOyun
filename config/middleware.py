"""
Custom CORS Middleware for Django
Allows all origins, methods, headers for Flutter web compatibility.
No external dependencies required.
"""

import re


class CorsMiddleware:
    """
    Custom CORS middleware that allows all origins and handles preflight requests.
    Replaces corsheaders package with zero dependencies.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Handle preflight OPTIONS requests
        if request.method == 'OPTIONS':
            response = self._build_cors_response()
            return response

        response = self.get_response(request)
        return self._add_cors_headers(response)

    def _build_cors_response(self):
        """Build response for preflight OPTIONS requests."""
        from django.http import HttpResponse
        response = HttpResponse()
        return self._add_cors_headers(response)

    def _add_cors_headers(self, response):
        """Add CORS headers to response."""
        # Allow all origins
        response['Access-Control-Allow-Origin'] = '*'

        # Allow all common HTTP methods
        response['Access-Control-Allow-Methods'] = 'GET, POST, PUT, PATCH, DELETE, OPTIONS, HEAD'

        # Allow all headers that Flutter/web clients might send
        response['Access-Control-Allow-Headers'] = (
            'accept, accept-encoding, authorization, content-type, dnt, origin, '
            'user-agent, x-csrftoken, x-requested-with, x-device-id, x-player-token, '
            'access-control-allow-origin, access-control-allow-headers, '
            'access-control-allow-methods, access-control-allow-credentials'
        )

        # Allow credentials (cookies, auth headers)
        response['Access-Control-Allow-Credentials'] = 'true'

        # Cache preflight response for 1 hour
        response['Access-Control-Max-Age'] = '3600'

        # Expose headers to client
        response['Access-Control-Expose-Headers'] = 'content-type, authorization, x-csrftoken'

        return response