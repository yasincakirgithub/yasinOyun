"""Template tags for cache-safe static file URLs.

``static_v`` appends the source file's modification time as a query string so
browsers (and WhiteNoise's cached headers) are forced to fetch the file again
whenever it changes, without needing a manual cache clear.
"""

import os

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def static_v(path):
    """Like ``{% static %}`` but with a ``?v=<mtime>`` cache-busting suffix."""
    url = static(path)
    try:
        found = finders.find(path)
        version = int(os.path.getmtime(found)) if found else None
    except OSError:
        version = None
    return f'{url}?v={version}' if version else url
