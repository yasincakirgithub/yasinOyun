# FC Manager

Two-player football manager duel for the unified Django games platform. Each
room freezes an 80-player market from `FC26_20250921.csv`, gives both managers
the same random budget and four shared challenges, then turns their 4-3-3
drafts into a server-simulated match.

- Create/join a room with a six-character code or invite link.
- Shared budget between **€400M** and the euro equivalent of **₺1T**.
- Shared challenges such as “3 Spanish players”, “2 Süper Lig players” or
  “5 players under 25”.
- Drag-and-drop squad building with a tap/click fallback for touch devices.
- Position compatibility, unique players, budget limits and live challenge
  progress enforced by the server.
- Host-only match start. Both squads must be locked first.
- Complete 90-minute timeline with goals, cards, saves, possession, xG, MVP,
  penalties on draws, and an animated client-side replay.
- Host-only “Yeni Sezon” resets the room with a fresh market, budget and
  challenges.

## Data and game rules

The CSV is read once through `fcmanager/data.py`. Every draft gets a balanced,
shuffled 80-player snapshot stored in `MarketPlayer` rows, so both managers see
the same market and each player can only be drafted once.

The formation is 4-3-3: GK, LB, CB, CB, RB, CM, CM, CM, LW, ST, RW. Slot
compatibility uses the player's FC26 position list. The budget is canonical in
EUR; the TRY value is a display equivalent at `EUR_TRY_RATE = 47.0`.

Challenge generation avoids impossible combinations. In particular,
`two_squads_feasible()` proves that two disjoint legal squads can satisfy the
shared challenge set before it is accepted. Match strength combines attack,
midfield, defence, goalkeeper, completed challenges and home advantage, then a
Poisson goal model adds football randomness.

## Local setup

```bash
python3 -m pip install -r requirements.txt
cp .env.example .env
python3 manage.py migrate
python3 manage.py runserver 127.0.0.1:8000
```

Open <http://127.0.0.1:8000/fcmanager/>. Daphne is first in `INSTALLED_APPS`,
so the development `runserver` process serves the ASGI app and WebSockets. When
`DEBUG=true` or `REDIS_URL` is unset, the project uses the in-memory channel
layer; set `REDIS_URL` for multi-process deployments.

## HTTP API

Mutating endpoints take JSON and return `{"success": ...}`. Authenticate with
`Authorization: Bearer <session_token>` (or `X-Player-Token`).

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/fcmanager/` | Landing/create/join page. |
| `GET` | `/fcmanager/room/<code>/` | Lobby, draft or match page. |
| `POST` | `/fcmanager/api/rooms/` | Create a room. |
| `POST` | `/fcmanager/api/rooms/join/` | Join or reconnect. |
| `GET` | `/fcmanager/api/rooms/<code>/state/` | Role-aware room snapshot. |
| `POST` | `/fcmanager/api/rooms/<code>/start-draft/` | Host opens the season. |
| `POST` | `/fcmanager/api/rooms/<code>/pick/` | Draft a player into a slot. |
| `POST` | `/fcmanager/api/rooms/<code>/remove/` | Remove a player from a slot. |
| `POST` | `/fcmanager/api/rooms/<code>/clear/` | Clear the whole squad. |
| `POST` | `/fcmanager/api/rooms/<code>/swap/` | Swap two slots. |
| `POST` | `/fcmanager/api/rooms/<code>/lock/` | Lock a complete squad. |
| `POST` | `/fcmanager/api/rooms/<code>/unlock/` | Reopen a locked squad. |
| `POST` | `/fcmanager/api/rooms/<code>/start-match/` | Host starts the match. |
| `POST` | `/fcmanager/api/rooms/<code>/new-season/` | Host starts a new season. |
| `POST` | `/fcmanager/api/rooms/<code>/leave/` | Leave the room. |
| `GET` | `/fcmanager/health/` | Database health check. |

WebSocket endpoint: `/fcmanager/ws/room/<code>/`. The server first sends
`{"type": "auth_required"}`; reply with
`{"type": "authenticate", "session_token": "<token>"}`. Authenticated clients
receive personalised `{"type": "state", ...}` snapshots. `get_state` and `ping`
are also supported. If WebSockets are unavailable, the client polls state every
3.5 seconds and performs actions over HTTP.

## Tests

Run the suite against a temporary SQLite database so the configured PostgreSQL
instance is never touched:

```bash
DATABASE_URL= DB_ENGINE= python3 manage.py test fcmanager -v 2
```

Coverage includes CSV loading, market balance, challenge generation and joint
feasibility, challenge progress, draft rules, budget enforcement, match
simulation, room lifecycle, HTTP authentication/authorisation, WebSocket
authentication and broadcasts.

## Structure

- `data.py` — CSV loader, slots, market generation and currency constants.
- `challenges.py` — challenge catalogue, progress and feasibility checks.
- `simulation.py` — profiles, timeline, score, stats, MVP and shootouts.
- `services.py` — room lifecycle, draft actions and state serialization.
- `views.py` / `consumers.py` — HTTP API and WebSocket transport.
- `static/fcmanager/js/game.js` — room client, drag/drop and match animation.
- `templates/fcmanager/` — landing and game-room markup.
