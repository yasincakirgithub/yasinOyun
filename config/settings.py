"""
Django settings for the unified games platform.

Hosts all games in one project:

  - ``core``    : landing page (game selector)
  - ``sayi``    : 4-digit number guessing game (Bulls and Cows)
  - ``kim``     : "Kim Bu?" / Guess Who character guessing game
  - ``amiral``  : two-player Battleship game ("Amiral Battı")

The games share a single PostgreSQL database and Redis instance.
"""

from pathlib import Path
import os

import dj_database_url
from dotenv import load_dotenv

# Load environment variables from .env file (if present).
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Core settings
# ---------------------------------------------------------------------------

SECRET_KEY = os.environ.get(
    'SECRET_KEY',
    'django-insecure-*-hvzy#^&*()_+=-0987654321qwertyuiopasdfghjklzxcvbnm',
)

DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
    if host.strip()
]

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get('CSRF_TRUSTED_ORIGINS', '').split(',')
    if origin.strip()
]


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'channels',
    'core',
    'sayi',
    'kim',
    'amiral',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
# Single database shared by both games. Configure either with DATABASE_URL or
# with the individual DB_* variables. When neither is provided (e.g. local
# development without Docker) it falls back to SQLite.

CONN_MAX_AGE = int(os.environ.get('DB_CONN_MAX_AGE', '600'))
DATABASE_URL = os.environ.get('DATABASE_URL')

if DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=CONN_MAX_AGE,
            conn_health_checks=True,
        )
    }
elif os.environ.get('DB_ENGINE'):
    DATABASES = {
        'default': {
            'ENGINE': os.environ.get('DB_ENGINE', 'django.db.backends.postgresql'),
            'NAME': os.environ.get('DB_NAME', 'oyunlar'),
            'USER': os.environ.get('DB_USER', 'postgres'),
            'PASSWORD': os.environ.get('DB_PASSWORD', 'postgres'),
            'HOST': os.environ.get('DB_HOST', 'host.docker.internal'),
            'PORT': os.environ.get('DB_PORT', '5432'),
            'CONN_MAX_AGE': CONN_MAX_AGE,
            'CONN_HEALTH_CHECKS': True,
            'OPTIONS': {
                # RDS requires/supports TLS; `prefer` uses it when available.
                'sslmode': os.environ.get('DB_SSL_MODE', 'prefer'),
            },
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }


AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = []

# WhiteNoise serves static files under ASGI (uvicorn/gunicorn).
WHITENOISE_USE_FINDERS = DEBUG
WHITENOISE_AUTOREFRESH = DEBUG

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ---------------------------------------------------------------------------
# Channels (WebSocket) configuration
# ---------------------------------------------------------------------------
# NOTE: redis-py >= 8 defaults socket_timeout to 5s, which collides with the
# layer's blocking BZPOPMIN (brpop_timeout = 5s) and raises redis TimeoutError.
# Set socket_timeout=None so the blocking read never times out client-side.

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [{
                'address': os.environ.get('REDIS_URL', 'redis://127.0.0.1:6379'),
                'socket_timeout': None,
                'socket_connect_timeout': 5,
            }],
        },
    },
}


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', 'False').lower() == 'true'

SECURE_CONTENT_TYPE_NOSNIFF = True

if SECURE_SSL_REDIRECT:
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
    },
    'loggers': {
        'sayi': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
        'kim': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
        'amiral': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
    },
}
