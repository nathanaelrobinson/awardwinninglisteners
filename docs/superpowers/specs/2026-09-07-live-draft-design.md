# Live Draft + Standings — Design

Date: 2026-09-07. Draft is tonight at 6pm PT. Replaces the league Google Sheet.

## Goal

Five people log in from their own devices, see one shared draft board, randomize
slots when everyone is present, draft 6 teams each in the league's fixed 30-pick
order, and then follow regular-season wins per roster all season.

The bar is the spreadsheet it replaces: type a team, see the sum. Nothing harder.

## Non-goals

- A custom domain. The `*.run.app` URL is what gets shared tonight.
- Google/OAuth accounts. Name + shared PIN is enough for five friends.
- WebSockets. Two-second polling is fine for five clients.
- Multi-league or multi-season support. One league document, hard-coded to 2026.
- Playoff wins. Regular season only; ties count 0.

## Design principle: simplicity

Every string in the UI must justify itself. No captions explaining what a number
means; if a number needs a caption, the layout is wrong. Before calling any screen
done, do a text-justification pass and delete anything a spreadsheet user would not
miss. The optimizer's explanatory copy is confined to the commissioner-only panel and
the existing Practice tab.

## Architecture

Same FastAPI + React app, deployed to Cloud Run, with one new backend module and
three new screens.

```
browser (5 clients, poll /api/league every 2s)
   │
FastAPI (Cloud Run, max 1 instance, min 1 instance)
   ├── winspool.league   state machine + auth (new)
   ├── winspool.store    Firestore | InMemory (new)
   ├── winspool.standings  wins from nfl_data_py, 1h cache (new)
   └── existing: recommend / results / autosim (unchanged)
   │
Firestore (native mode) — one doc: leagues/2026
```

### League document

```
leagues/2026
  pin_hash        str   sha256 of league PIN + salt
  commissioner    str   player name
  players         [str] five names (fixed at setup)
  slots           {name: 1..5} | null  (null until randomized)
  status          "lobby" | "drafting" | "done"
  picks           [{n, slot, team, by, ts}]  ordered, n = 1..30
  overrides       {team: wins}  commissioner corrections to the feed
  logged_in       {name: ts}  last-seen timestamps for the lobby
```

```
leagues/2026/messages/{auto-id}
  by      str   player name
  text    str   ≤ 500 chars
  ts      float epoch seconds
```

Messages are a subcollection so the league doc stays small. Picks are not duplicated
into messages; the client merges `picks` and `messages` by timestamp into one feed.

Pick order is `winspool.draft.PICK_ORDER` (fixed, not a snake). Slot for pick `n`
is `PICK_ORDER[n-1]`. Randomize assigns names to slots; the order itself never
changes.

### Auth

`POST /api/login {name, pin}` → checks name ∈ players and PIN hash → sets a signed
cookie `wp_session` (HMAC over name using `SESSION_SECRET` env). Every league
endpoint reads the cookie. Commissioner is the player whose name equals
`commissioner`. No logout needed; cookie lives 7 days.

### Endpoints (new)

| Method | Path | Who | Effect |
|---|---|---|---|
| POST | /api/login | anyone | set cookie |
| GET | /api/me | cookie | `{name, is_commissioner, slot}` |
| GET | /api/league | cookie | full league state for rendering (also touches `logged_in`) |
| POST | /api/league/randomize | commissioner, status=lobby | shuffle names→slots, status=drafting |
| POST | /api/league/reset | commissioner, no picks yet | slots=null, status=lobby |
| POST | /api/league/pick {team} | cookie | transaction: caller's slot == current slot, team not taken → append |
| POST | /api/league/undo | commissioner | pop last pick; if picks empty and status=done, status=drafting |
| GET | /api/messages?since=ts | cookie | messages newer than `since` (all if omitted), oldest first, cap 200 |
| POST | /api/messages {text} | cookie | append a message as the caller |
| GET | /api/standings | cookie | per-team wins (feed + overrides), per-player totals |
| POST | /api/standings/override {team, wins} | commissioner | set/clear override |

Existing `/api/recommend`, `/api/results`, `/api/sample_season` require the cookie
and return 403 unless caller is commissioner. `/api/autosim` and `/api/advance`
(Practice tab) same rule. `/api/teams` is open.

Pick and undo run inside a Firestore transaction so a double click cannot append
twice and undo cannot race a pick.

When the 30th pick lands, status becomes `done`.

### Store interface

```python
class Store(Protocol):
    def get(self) -> dict
    def update(self, fn: Callable[[dict], dict]) -> dict   # transactional read-modify-write
```

`InMemoryStore` for tests and local dev. `FirestoreStore` in prod, selected by
`STORE=firestore` env. All state-machine logic lives in `league.py` as pure
functions over the dict so tests never touch Firestore.

### Standings

`standings.py` loads the 2026 schedule via `nfl_data_py.import_schedules([2026])`,
keeps rows where `game_type == "REG"` and both scores are non-null, and counts a win
for the higher score (tie → nothing). Cached in memory for one hour; commissioner
can hit `?refresh=1`. Overrides replace the feed's count for that team. Player total
= sum over the player's 6 teams.

Until a game is played the endpoint returns zeros, which is what the sheet shows
today.

## Frontend

Three new screens plus the existing app as a Practice tab. Client polls
`/api/league` every 2 seconds while status is lobby or drafting; every 60 seconds
on the standings tab.

### Login

Five name buttons. A PIN field. One "Enter" button. Nothing else.

### Lobby (status = lobby)

The five names, each with a dot that's filled if seen in the last 30 seconds.
Commissioner sees one button: "Randomize order". Everyone else sees nothing else.

### Draft (status = drafting or done)

- Top: the 30-pick strip. Each cell shows the slot's name and, once picked, the
  team code. Current pick is highlighted.
- Left: 32 team tiles grouped by division. Taken tiles are dimmed with the drafter's
  name. On your turn, tiles are buttons; otherwise they are inert.
- Right: five roster columns, name on top, six rows.
- Below the rosters: the feed. A single-line input with the caller's name as its
  placeholder, and above it the merged list of picks ("Nate Robinson — KC") and
  messages ("Mitch Fischer: ..."), newest at the bottom, auto-scrolled. Polled with
  the league state. The same feed, still writable, appears on the Standings tab so
  the group can keep commenting all season.
- Commissioner-only: an "Undo" button under the strip, and the existing
  Recommendations + Forecast panel below the board. No one else sees these.
- When status = done the strip is full and the pick buttons are gone. No banner.

### Standings

One table. Columns: Player, six team codes each with its win count, Total. Sorted by
Total descending. Commissioner can click a team's number to override it. No prose.

### Practice

The existing single-user draft app, unchanged, commissioner-only. Lets Nate run bot
drafts against the optimizer before 6pm.

### Text-justification rule

Before merge, list every literal string rendered in Login, Lobby, Draft, and
Standings and delete any that a user of the Google Sheet would not miss. Column
headers and button labels stay. Sentences go.

## Deployment

- `Dockerfile`: stage 1 `node:22-alpine` builds `web/dist`; stage 2
  `python:3.12-slim` installs the package with `uv`, copies `web/dist` and
  `data/cache/` (schedule, totals, power, kalshi, and the precomputed
  `sim_matrix.npz`). No Playwright browser install.
- `.dockerignore` excludes `venv/`, `web/node_modules/`, `.git/`. `data/cache/` is
  git-ignored but is **not** docker-ignored; it must exist locally when building.
- Cloud Run service `winspool`, region `us-west1`, `--min-instances=1
  --max-instances=1 --memory=2Gi --cpu=2 --allow-unauthenticated`.
  Env: `STORE=firestore`, `SESSION_SECRET`, `GOOGLE_CLOUD_PROJECT`.
- New GCP project `wins-pool-2026` (personal), billing linked to the same account as
  the active project. Enable Cloud Run, Artifact Registry, Cloud Build, Firestore.
  Firestore native mode, `us-west1`.
- One-time setup via `winspool league-init` which writes the league doc. Players:
  Nate Robinson (commissioner), Evan Goguillon-Bader, Logan Borgelt, Eric Whitley,
  Mitch Fischer. PIN is passed via `--pin` / `LEAGUE_PIN` env, never committed. Re-runnable; refuses if picks exist
  unless `--force`.

## Error handling

- Wrong PIN → 401, field shakes, nothing else.
- Pick out of turn or taken team → 409; client refreshes state. Because tiles are
  inert when it isn't your turn, this only happens on a race.
- Feed unavailable → standings returns last cached values with `stale: true`; the
  client shows the table anyway. If never fetched, zeros.
- Firestore unavailable → 503 with a plain retry.

## Testing

Unit tests (pytest, in-memory store):

- login: right/wrong PIN, unknown name
- randomize: only commissioner, only in lobby, produces a permutation of 1..5
- pick: right slot accepted, wrong slot 409, taken team 409, 30th pick → done
- undo: commissioner only, pops last, reopens from done
- messages: append as caller, `since` filter, 500-char cap, empty text rejected
- standings: fixture schedule with wins, a tie, an unplayed game, one override

Manual before 6pm: deploy, open five browser profiles, run a full 30-pick mock
draft on the live URL, undo once, confirm standings shows 30 zeros. Reset before
handing the link out.

## Timeline (PT)

| By | Done |
|---|---|
| 12:30 | league.py, store.py, auth, endpoints, tests green |
| 14:30 | Login, Lobby, Draft screens incl. message feed; text pass |
| 16:00 | Docker, GCP project, Cloud Run deploy, 5-tab mock draft |
| 17:00 | Standings backend + tab |
| 18:00 | Buffer. Link texted with PIN. |

Cut order if late: Standings tab first (can ship Tue/Wed before Thursday's games),
then override UI, then Practice tab gating.
