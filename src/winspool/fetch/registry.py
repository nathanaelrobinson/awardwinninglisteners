"""Concrete network data sources.

NOTE: These perform live HTTP and depend on external endpoints/schemas that
change. They are NOT unit-tested. Before relying on them, run a smoke test:
    python -c "from winspool.fetch.registry import default_sources; \
               print([(s.name, len(s.fetch())) for s in default_sources(CONFIG)])"
and confirm each source returns ~32 teams. Add a new source by writing a
fetch function that returns {team_code: value} and appending a Source here.
"""
import json
import urllib.request

from .parsers import parse_csv_ratings
from .pipeline import Source


def http_text(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def http_json(url, timeout=30):
    return json.loads(http_text(url, timeout))


def _odds_api_totals(api_key):
    """Season win totals from The Odds API. Returns {code: mean point across books}.
    Endpoint/market key must be confirmed live; shape assumed:
    [{"home_team": <name>, "bookmakers":[{"markets":[
        {"key":"team_totals","outcomes":[{"name":<team>,"point":<wins>}]}]}]}]"""
    url = (f"https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds"
           f"?regions=us&markets=team_totals&apiKey={api_key}")
    payload = http_json(url)
    from collections import defaultdict

    from ..teams import resolve
    pts = defaultdict(list)
    for event in payload:
        for book in event.get("bookmakers", []):
            for market in book.get("markets", []):
                for o in market.get("outcomes", []):
                    code = resolve(o.get("name", ""))
                    if code is not None and "point" in o:
                        pts[code].append(float(o["point"]))
    return {code: sum(v) / len(v) for code, v in pts.items() if v}


def _csv_power(url, name_col, value_col):
    return parse_csv_ratings(http_text(url), name_col, value_col)


def default_sources(config):
    """Build sources from config, e.g.
    {"odds_api_key": "...",
     "power_csv": [{"name":"sagarin","url":"...","name_col":"team","value_col":"rating"}]}.
    Missing/blank config entries are skipped so a partial config still runs."""
    sources = []
    if config.get("odds_api_key"):
        key = config["odds_api_key"]
        sources.append(Source("odds_api", "totals", lambda: _odds_api_totals(key)))
    for spec in config.get("power_csv", []):
        sources.append(Source(
            spec["name"], "power",
            lambda spec=spec: _csv_power(spec["url"], spec["name_col"], spec["value_col"])))
    return sources
