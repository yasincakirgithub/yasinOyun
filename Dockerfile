FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings

WORKDIR /code

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy project (both games share this single Django project; character images
# live in ./kim/static/kim/characters and are served under
# /static/kim/characters/ via the app static finder).
COPY . .

# Collect static files
RUN python manage.py collectstatic --noinput

# Create a non-root user
RUN adduser --disabled-password --gecos '' appuser
USER appuser

EXPOSE 8000

# The command is overridden in docker-compose.yml
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000"]
