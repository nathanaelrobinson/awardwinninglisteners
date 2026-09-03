# Data sources

`winspool fetch` pulls live data into `data/cache/` via `winspool.fetch.registry`.
Parse logic lives in `winspool/fetch/scrapers.py` (unit-tested against fixtures);
network fetchers are validated by the live smoke test (`winspool fetch`).

## Wired & live (`winspool fetch`)

| Source | Kind | Method | Notes |
|--------|------|--------|-------|
| Covers | win totals | requests + bs4 (HTML table) | nicknames |
| BetMGM | win totals | requests + bs4 (HTML table) | full names |
| ESPN FPI | power | JSON API (`site.web.api.espn.com/.../powerindex`) | `fpi` value = points vs avg |
| nfelo | power | headless Chromium (playwright) + bs4 | Elo → points (÷25); JS-rendered |

Win-total sources are averaged per team into `win_totals.csv`; each power source
becomes a column in `power_ratings.csv` (points scale, so the blend averages them
coherently). Provenance + timestamps in `sources_meta.json`.

## Available but not auto-wired

- **Mike Clay projections (ESPN)** — distributed as a PDF
  (`g.espncdn.com/s/ffldraftkit/26/NFLDK2026_CS_ClayProjections2026.pdf`), page 61 =
  projected standings (per-team projected wins). Reputable. Not yet auto-fetched
  (needs PDF parsing); can be added with a download+parse fetcher.

## Blocked / not accessible

- **Oddspedia** — HTTP 403 to non-browser clients (Cloudflare).
- **The Analyst (Opta)** — JS-rendered landing; would need the Opta data API or headless.
- **Sagarin** (sagarin.com) — TLS certificate expired.
- **TeamRankings, DRatings, Massey** — HTTP 403 to non-browser clients.

Oddspedia / TeamRankings / DRatings could likely be scraped with the same headless
(playwright) path used for nfelo — a follow-up if more sources are wanted.

## Schedule

`scripts/fetch_data.py` pulls the real 2026 schedule via `nfl_data_py` into
`data/cache/schedule_2026.csv`.

## Adding a source

Write a `parse_*` (pure, testable) + a fetch wrapper in `scrapers.py` returning
`{team_code: value}` (resolve names with `winspool.teams.resolve`), then append a
`Source(name, "totals"|"power", fetch)` in `registry.default_sources()`.
