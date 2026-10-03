# yazayno - number app

A Django-based online multiplayer implementation of the classic 4-digit number guessing game (Bulls and Cows).

## Features

- Real-time multiplayer using WebSockets (Django Channels)
- Secure game logic (secret numbers never exposed to clients)
- Paper-themed UI with notebook aesthetic
- Room-based gameplay with shareable codes
- Turn-based system with validation
- Responsive design for desktop and mobile
- Dockerized for easy deployment

## Game Rules

1. Each player thinks of a 4-digit number with unique digits (no leading zero)
2. Players take turns guessing each other's numbers
3. After each guess, the player receives feedback:
   - `+` for correct digit in correct position
   - `-` for correct digit in wrong position
4. First player to guess the opponent's number correctly wins
5. Game state is synchronized in real-time between players

## Requirements

- Docker and Docker Compose
- Or Python 3.11+, PostgreSQL, Redis for local development

## Single-Server (EC2) Setup

In this scenario PostgreSQL **and Redis** are already running on the host in
Docker via the shared top-level `../docker-compose.yml`. The app does NOT start
its own database/cache container; it connects to the existing servers and uses
the database named by `DB_NAME` (default: `sayilar`) plus the shared Redis. The
stack only runs the `web` (Django/ASGI) and optional `db-init` services.

1. Start the shared infrastructure (once):
   ```bash
   cd ..
   docker compose up -d
   cd sayi_oyunu
   ```
2. Environment file:
   ```bash
   cp .env.example .env
   # Edit ALLOWED_HOSTS / CSRF_TRUSTED_ORIGINS and the DB_* / DATABASE_URL
   # values for your EC2 IP or domain.
   ```
3. Start the app:
   ```bash
   docker compose up -d --build
   ```
4. Game: `http://<EC2_PUBLIC_IP>:8000`

The container reaches the shared PostgreSQL and Redis via `host.docker.internal`
(`extra_hosts: host-gateway`). Connection details come from the `DB_*` /
`REDIS_URL` variables or a single `DATABASE_URL` in `.env`. On startup
`ensure_db.py` creates the database named by `DB_NAME` if it is missing, then
migrations are applied automatically against it.

> `db-init` is still available as an optional one-shot helper:
> `docker compose --profile init run --rm db-init`.

> Keep `SECURE_SSL_REDIRECT=False` until you set up HTTPS/TLS. It allows access
> over plain HTTP by IP. Switch it to `True` and update `ALLOWED_HOSTS` and
> `CSRF_TRUSTED_ORIGINS` once TLS is in place.

## Quick Start with Docker

1. Clone the repository
2. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```
   (Optional: edit .env to customize settings)
3. Create the database (if it does not exist yet) and start the containers:
   ```bash
   docker compose --profile init run --rm db-init
   docker compose up --build
   ```
4. The game will be available at http://localhost:8000

## Local Development (Without Docker)

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Set up environment variables (copy .env.example to .env and adjust)
3. Apply migrations:
   ```bash
   python manage.py migrate
   ```
4. Create a superuser (optional):
   ```bash
   python manage.py createsuperuser
   ```
5. Start the development server:
   ```bash
   python manage.py runserver
   ```
6. For WebSocket support, also start Redis:
   ```bash
   redis-server
   ```
7. Visit http://127.0.0.1:8000 in your browser

## Project Structure

```
free_application/
├── config/                 # Django project settings
├── game/                   # Main application
│   ├── models.py           # Database models
│   ├── views.py            # HTTP API endpoints
│   ├── consumers.py        # WebSocket consumers
│   ├── services.py         # Game logic and validation
│   ├── validators.py       # Input validation
│   ├── utils.py            # Helper functions
│   ├── routing.py          # URL configuration
│   └── tests/              # Test suite
├── templates/              # HTML templates
├── static/                 # CSS, JavaScript, images
├── Dockerfile              # Docker image definition
├── docker-compose.yml      # Docker Compose configuration
├── requirements.txt        # Python dependencies
└── README.md               # This file
```

## API Endpoints

### Game Room (HTML)
- `GET /` - Home page (create/join game)
- `GET /<room_code>/` - Game room interface

### REST API (under `/api/`)
- `POST /api/create/` - Create a new game room
- `POST /api/join/` - Join an existing game room
- `POST /api/secret/` - Set your secret number
- `POST /api/guess/` - Make a guess
- `GET /api/state/<room_code>/` - Get current room state

### WebSocket
- `WS /ws/game/<room_code>/` - WebSocket connection for real-time gameplay

## Testing

Run the test suite:
```bash
python manage.py test
```

## Docker Files

- `Dockerfile`: default image used by docker-compose (ASGI, uvicorn).
- `Dockerfile.dev`: development image (`config.settings`, auto reload).
- `Dockerfile.prod`: production image (gunicorn + uvicorn worker).
- `docker-compose.yml`: `web` service and the optional `db-init` (PostgreSQL/Redis
  live in the shared top-level `../docker-compose.yml`).
- `ensure_db.py`: creates the configured database at startup if it is missing.
- `.dockerignore`: files not copied into the image.

## Deployment

For production:
1. Set `DEBUG=False` in environment variables
2. Use a proper secret key
3. Configure `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`
4. Use a production ASGI server (gunicorn + uvicorn worker is available in `Dockerfile.prod`)
5. Ensure Redis and the existing PostgreSQL are properly backed up

## Design Notes

- Secret numbers are stored encrypted in the database and never sent to clients
- All validation occurs both client-side and server-side
- WebSocket connections are authenticated and authorized
- Game state is managed server-side with real-time updates via WebSocket
- UI designed to resemble a paper notebook with vintage aesthetics
- Responsive layout works on mobile and desktop devices

## License

MIT