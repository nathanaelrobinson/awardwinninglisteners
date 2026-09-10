"""Registry of live data sources for `winspool fetch`.

Now that the season is underway, a forecast that cannot change is not evidence
about a season in progress. `default_sources()` returns only sources that can
be kept current:
- covers   -> season win totals (kind "totals")
- espn_fpi -> FPI rating in points (kind "power")

Everything else has been dropped: PFF (a preseason news article), Clay (a
preseason PDF), betmgm (a blog post failing with HTTP 520), and nfelo (needs a
headless browser the project has refused to run on the Pi).

The parse logic lives in scrapers.py and is unit-tested against fixtures; the
network fetchers here are validated by a live smoke test, not unit tests.

Add a working source by writing a parse_* + fetch in scrapers.py and
appending a Source below.
"""
from .pipeline import Source
from .scrapers import covers_totals, espn_fpi


def default_sources(config=None):
    """Only sources that can be kept current. A forecast that cannot change is
    not evidence about a season in progress, so preseason artifacts (PFF's news
    article, Clay's PDF, betmgm's blog post) are gone, and nfelo is gone with
    the headless browser it needed."""
    return [
        Source("covers", "totals", covers_totals),
        Source("espn_fpi", "power", espn_fpi),
    ]
