# Codenames

Real-time multiplayer Codenames for the unified Django games platform. Two
teams race to reveal their agents on a shared 5×5 board while only the two
spymasters can see the secret colour map.

- 4–10 players, 25 words, standard 9/8/7/1 agent distribution.
- Authoritative server rules, server-side timers and atomic guesses.
- Hidden categories are filtered **on the server**; operatives never receive
  unrevealed colours over HTTP, WebSocket JSON or the DOM.
- DeepSeek-generated Turkish/English vocabulary with a curated fallback.
- Reconnect via an opaque player token; host transfer on leave.
- Tab-scoped sessions: a new tab can join as another player, while the
  previous seat remains resumable from the join gate.
- Responsive lobby, game board, chat, event log, clue-by-clue guess history
  and game-over overlay.

## Rules implemented

- Each team needs exactly one spymaster and at least one operative. In the
  lobby every player can choose their own team and role; choosing spymaster
  fails if that team already has one. The host can still override everyone.
- The starting team receives 9 agents, the other team 8. Neutral and assassin
  cards complete the board.
- A spymaster gives one word and a number from 0–9. The clue cannot match a
  board word. Giving a second clue in the same turn is rejected.
- Operatives reveal one card at a time. A correct card keeps the turn alive.
  Neutral or opponent cards end the turn. The assassin loses the game.
- `extra_guess` gives `number + 1` guesses (classic rule). A clue of `0` is
  only accepted when the host enables `allow_zero_clue`.
- The turn timer starts when the turn starts and is enforced by the database
  (`GameSession.turn_deadline`), not by the browser. Expired turns are ended
  idempotently by the next action/state request or the WebSocket timer.
- A spymaster leaving during a game abandons the game and reveals the board.
  The game is also abandoned if a team loses its last operative.

## Local setup

Requirements: Python 3.12 and a Redis instance (for WebSockets).

```bash
python3 -m pip install -r requirements.txt
cp .env.example .env
# Edit .env: set SECRET_KEY, database and Redis values.
python3 manage.py migrate
```

Run the ASGI server (WebSockets need ASGI, not plain `runserver`):

```bash
python3 -m uvicorn config.asgi:application --reload --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/codenames/>.

If Redis is not running, start the project Redis container:

```bash
docker compose up -d redis
```

When the ASGI server runs directly on the host (not inside Docker), point both
Redis variables at localhost instead of `host.docker.internal`:

```dotenv
REDIS_URL=redis://127.0.0.1:6379
CACHE_URL=redis://127.0.0.1:6379/1
```

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | empty | Server-only key. Empty means fallback vocabulary. |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI-compatible API base. |
| `DEEPSEEK_MODEL` | `deepseek-flash` | Model name used for board generation. |
| `DEEPSEEK_TIMEOUT` | `12` | Per-request timeout in seconds. |
| `DEEPSEEK_MAX_RETRIES` | `2` | Extra attempts on transient/validation errors. |
| `CACHE_URL` | empty | Shared Redis cache for rate limits. Empty uses LocMem. |
| `REDIS_URL` | `redis://127.0.0.1:6379` | Channels layer address. |
| `DATA_UPLOAD_MAX_MEMORY_SIZE` | `262144` | Django upload cap in bytes. |

DeepSeek is optional. If the key is missing, the API errors, returns invalid
JSON or produces an invalid list, the game falls back to the curated pool and
continues normally. The API key is read only in `codenames/deepseek.py` and is
never sent to templates or browser code.

### Kelime kaynağı / troubleshooting

Each started game stores `GameSession.word_source` as `deepseek` or `fallback`.
The game HUD shows **DeepSeek kelimeleri** or **Yerel kelime havuzu** so it is
clear which source produced the board. Fallback words come from the curated
`TURKISH_WORDS` / `ENGLISH_WORDS` lists in `codenames/words.py`.

If boards still say **Yerel kelime havuzu**:

1. Confirm `DEEPSEEK_API_KEY` is a non-empty line in the server's `.env` (not
   only in a local shell) and contains no quotes or spaces.
2. Restart the Django/Uvicorn process; settings are read at startup.
3. Check server logs for `DEEPSEEK_API_KEY is not configured`, `DeepSeek HTTP
   error` or `DeepSeek vocabulary validation failed`.
4. Keep `DEEPSEEK_MODEL=deepseek-flash` and the official base URL unless your
   provider explicitly supports a different model name.

The request disables DeepSeek thinking mode so the token budget is spent on the
25-word JSON answer rather than a reasoning trace.

## HTTP API

All mutating endpoints accept JSON and return `{"success": ...}`. Player
authentication uses `Authorization: Bearer <session_token>` (or
`X-Player-Token`). Error responses use `{"success": false, "error", "code"}`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/codenames/` | Landing/create/join page. |
| `GET` | `/codenames/room/<code>/` | Lobby/game page. |
| `POST` | `/codenames/api/rooms/` | Create a room. |
| `POST` | `/codenames/api/rooms/join/` | Join or reconnect. |
| `GET` | `/codenames/api/rooms/<code>/state/` | Role-filtered snapshot. |
| `POST` | `/codenames/api/rooms/<code>/leave/` | Leave and transfer host. |
| `POST` | `/codenames/api/rooms/<code>/settings/` | Host-only settings. |
| `POST` | `/codenames/api/rooms/<code>/assign-roles/` | Host-only role assignment. |
| `POST` | `/codenames/api/rooms/<code>/preference/` | Choose your own team/role. |
| `POST` | `/codenames/api/rooms/<code>/start/` | Generate board and start. |
| `POST` | `/codenames/api/rooms/<code>/new-game/` | Return to lobby after a game. |
| `POST` | `/codenames/api/rooms/<code>/clue/` | Spymaster clue. |
| `POST` | `/codenames/api/rooms/<code>/chat/` | Send a chat message. |
| `POST` | `/codenames/api/rooms/<code>/guess/` | Operative guess. |
| `POST` | `/codenames/api/rooms/<code>/end-turn/` | Operative passes. |
| `GET` | `/codenames/api/rooms/<code>/events/` | Latest room events. |
| `GET` | `/healthz/` | Database health check. |

WebSocket endpoint: `/codenames/ws/room/<code>/`. The first server message is
`{"type": "auth_required"}`; reply with:

```json
{"type": "authenticate", "session_token": "<token>"}
```

Supported client messages: `authenticate`, `get_state`, `ping`, `chat`, `clue`,
`guess`, `end_turn`. Each authenticated viewer receives a personalized
`{"type": "state", ...}` snapshot.

The browser keeps its seat token in `sessionStorage`, so a new tab does not
silently reconnect as the same player. The game page can resume the stored
seat explicitly. If WebSockets are unavailable, the client falls back to
HTTP state polling every 3 seconds and sends clue/guess/end-turn/chat actions
through the REST API. WebSocket origins are accepted when they match the
request Host, `ALLOWED_HOSTS` or `CSRF_TRUSTED_ORIGINS`.

## Tests

Run the Codenames suite against a temporary SQLite database so the configured
PostgreSQL instance is never touched:

```bash
DATABASE_URL=sqlite:////tmp/codenames-test.sqlite3 python3 manage.py test codenames -v 2
```

Coverage includes vocabulary validation, DeepSeek retries/fallback, board
distribution, clue/guess rules, timers, role-based serialization, HTTP API,
WebSocket authentication/broadcasts and cross-room isolation.

## Deployment notes

The Docker image already runs `uvicorn config.asgi:application`, which supports
WebSockets. For production:

1. Run `python manage.py migrate --noinput` during release.
2. Set `DEBUG=False`, `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`. WebSocket
   same-origin connections are allowed automatically; add any cross-origin
   frontend origin to `CSRF_TRUSTED_ORIGINS`.
3. Keep Redis reachable from every web/ASGI worker. Use `CACHE_URL` so rate
   limits are shared. Multiple workers **require** Redis for channel broadcasts.
4. Terminate TLS at the reverse proxy; WebSocket upgrades must be forwarded.
5. Run the cleanup command periodically (rooms expire after 12 hours):

```cron
0 * * * * cd /code && python manage.py cleanup_codenames_rooms
```

6. Keep `DEEPSEEK_API_KEY` in the server environment only. Do not expose it
   through templates, static files, logs or client-side bundles.

## Data model

- `GameRoom`: code, status, host, language, settings, current session, expiry.
- `GamePlayer`: token hash, team, role, connection count, leave state.
- `GameSession`: turn/clue/guess state, remaining agents, timer, winner.
- `GameWord`: position, normalized word, secret category, reveal metadata.
- `ChatMessage` / `GameEvent`: room chat and a compact audit/event feed.

Room deletion cascades to players, sessions, words, messages and events.
`cleanup_codenames_rooms` removes rooms whose `expires_at` has passed.
