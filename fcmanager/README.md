# FC Manager

Two-player football manager duel for the unified Django games platform. The
full FC26 catalogue (`fcmanager/datasets/FC26_20250921.csv`) is imported into
the `Player` table and searched from there, so both managers draw from the same
15,000+ player pool. Every room still gets the same random budget and four
shared challenges, then turns its 4-3-3 draft into a server-simulated match with
a Haxball-style pseudo-3D replay.

- Create/join a room with a six-character code or invite link.
- Shared budget between **€400M** and **€2B** (five times the minimum).
- Shared challenges such as “3 Spanish players”, “2 Süper Lig players” or
  “5 players under 25”.
- Drag-and-drop squad building with a tap/click fallback for touch devices.
- One-click **auto squad**: fills all eleven slots with the strongest lineup
  that satisfies the shared challenges and stays inside the budget.
- Server-side search, filters, sorting and paginated transfer market over the
  whole catalogue — no 80-player cap.
- Position compatibility, unique players, budget limits and live challenge
  progress enforced by the server.
- Host-only match start. Both squads must be locked first.
- Complete 90-minute timeline with goals, cards, saves, possession, xG, MVP,
  penalties on draws, and a paced client-side replay in a 3D pitch view.
- Host-only “Yeni Sezon” resets the room with a fresh budget and challenges.

## Data and game rules

`fcmanager/datasets/FC26_20250921.csv` is the source of truth. Import it into
the `Player` table with `python3 manage.py import_fc26` (add `--replace` to
re-import, or `--path <csv>` for another file). Set the `FCMANAGER_DATASET`
environment variable to point at a different CSV. The catalogue is imported
lazily on the first draft if the table is still empty, and `data.py` falls back
to reading the CSV directly when the database is unavailable.

`MarketPlayer` rows are created only when a player is actually drafted, so the
market API always reflects the current picks and every player can be taken just
once.

### Player photos

The dataset points each player at a face photo on `cdn.sofifa.net`. That CDN
answers **only** when the request carries a `https://sofifa.com/` Referer — a
browser loading our page cannot send that header cross-origin, and a
`no-referrer` request gets a `403`. So the photos are downloaded once and served
by the app:

```bash
python3 fcmanager/download_player.py                # all players, resumable
python3 fcmanager/download_player.py --limit 100    # quick partial run
python3 fcmanager/download_player.py --workers 12   # more parallel requests
python3 fcmanager/download_player.py --force        # re-download everything
```

Files land in `media/player_images/<player_id>.png` (override with
`--output` or `FCMANAGER_PLAYER_IMAGES`) and are served from
`/fcmanager/photos/<player_id>.png` with a one-year immutable cache header.
`data.photo_url()` prefers the local file and falls back to the dataset CDN
link for any player that has not been downloaded yet, so a partial download
still works. `media/` is gitignored.

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
python3 manage.py import_fc26        # load the FC26 catalogue (--replace to redo)
python3 fcmanager/download_player.py # fetch the face photos (~18k PNGs)
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
| `GET` | `/fcmanager/api/rooms/<code>/market/` | Paginated catalogue search (`q`, `group`, `sort`, `affordable`, `page`). |
| `POST` | `/fcmanager/api/rooms/<code>/start-draft/` | Host opens the season. |
| `POST` | `/fcmanager/api/rooms/<code>/pick/` | Draft a player into a slot. |
| `POST` | `/fcmanager/api/rooms/<code>/remove/` | Remove a player from a slot. |
| `POST` | `/fcmanager/api/rooms/<code>/clear/` | Clear the whole squad. |
| `POST` | `/fcmanager/api/rooms/<code>/auto-fill/` | Build a challenge-aware squad inside the budget. |
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

- `data.py` — CSV loader, catalogue import, slots, market sampling and currency
  constants.
- `challenges.py` — challenge catalogue, progress and feasibility checks.
- `simulation.py` — profiles, timeline, score, stats, MVP and shootouts.
- `services.py` — room lifecycle, draft actions, catalogue search and state
  serialization.
- `views.py` / `consumers.py` — HTTP API and WebSocket transport.
- `management/commands/import_fc26.py` — catalogue import command.
- `download_player.py` — bulk downloader for the FC26 face photos.
- `static/fcmanager/js/game.js` — room client, drag/drop and match animation.
- `static/fcmanager/js/match3d.js` — Haxball-style pseudo-3D pitch renderer.
- `templates/fcmanager/` — landing and game-room markup.

## Simulation pacing

A match now produces roughly 30–40 timeline events (around a dozen chances per
side plus goals and period breaks). The client replay spreads them over
**about two minutes** — each event stays on screen for 2.5–4.2 seconds, with
goals and half/full-time taking a little longer, and shootout kicks a little
less. The replay still has a skip button if someone wants the result sooner.

## 3D pitch view

`static/fcmanager/js/match3d.js` draws the replay on a perspective canvas:

- The ball never teleports and **never rests in empty grass**. Every event first
  carries the ball onto the involved player (the waypoint follows him while he
  moves) and only then shoots; a save is collected by the keeper, a miss becomes
  a goal kick, and between events the ball is passed from player to player.
- Each player wears a **name plate** so both line-ups stay readable.
- Player discs use the **downloaded FC26 face photos** served from
  `/fcmanager/photos/<player_id>.png`. While a photo loads — or if it is
  missing — the disc falls back to the player's initials.

A goal plays a full beat: shoot → ball in the net → big green **GOL!** banner →
the ball walks back to the centre spot for a **santra** (the message changes to
`SANTRA` and a central player restarts). Penalty kicks follow the same rule:
spot kick, then either the net or the keeper.

## Squad quality and win chance

The result is driven by player ratings, so a better-built squad really does win
more often. With equal challenges and 200 seeded simulations:

| Match-up | Home win rate |
| --- | --- |
| 90 overall vs 70 overall | 97.5% |
| 85 vs 75 | 87% |
| 80 vs 80 | 47% |
| equal squads, home completed 3 challenges | 87.5% |

`tests/test_simulation.py` locks this in: a bigger rating gap must produce a
higher win rate, and completed challenges must beat an equally rated side.
