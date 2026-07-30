"""Registry of live data sources for `winspool fetch`.

`default_sources()` returns the sources that scrape/pull cleanly with requests:
- covers, betmgm  -> season win totals (kind "totals"; averaged per team)
- espn_fpi         -> FPI rating in points (kind "power"; one column)

The parse logic lives in scrapers.py and is unit-tested against fixtures; the
network fetchers here are validated by a live smoke test, not unit tests.

Other reputable sources and why they aren't wired here yet:
- nfelo (nfeloapp.com)      -> JS-rendered; needs a headless browser to scrape.
- Mike Clay projections     -> distributed as a PDF; parsed via the snapshot seeder.
- Sagarin                   -> site TLS cert expired.
- TeamRankings/DRatings/Massey/Oddspedia -> return HTTP 403 to non-browser clients.
Add a working one by writing a parse_* + fetch in scrapers.py and appending a
Source below.
"""
from .pipeline import Source
from .scrapers import (betmgm_totals, clay_projections, covers_totals, espn_fpi,
                       nfelo_power, pff_projections)


def default_sources(config=None):
    return [
        Source("covers", "totals", covers_totals),
        Source("betmgm", "totals", betmgm_totals),
        Source("espn_fpi", "power", espn_fpi),
        Source("nfelo", "power", nfelo_power),   # JS-rendered via headless browser
        Source("clay", "power", clay_projections),  # ESPN PDF projections
        Source("pff", "power", pff_projections),    # PFF grades-based sims
    ]
