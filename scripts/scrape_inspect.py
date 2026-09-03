"""Inspect raw HTML structure of candidate sources to design bs4 scrapers.
Run: uv run python scripts/scrape_inspect.py
"""
import re
import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}

URLS = {
    "covers": "https://www.covers.com/nfl/nfl-odds-win-totals",
    "betmgm": "https://sports.betmgm.com/en/blog/nfl/nfl-odds-predictions-season-win-totals-bm16/",
    "oddspedia": "https://oddspedia.com/insights/american-football/nfl-win-totals-odds",
}

for name, url in URLS.items():
    print(f"\n########## {name} :: {url}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        print("status", r.status_code, "len", len(r.text))
        if r.status_code != 200:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        tables = soup.find_all("table")
        print("n_tables", len(tables))
        if tables:
            t0 = tables[0]
            rows = t0.find_all("tr")[:4]
            for tr in rows:
                cells = [c.get_text(strip=True) for c in tr.find_all(["th", "td"])]
                print("  row:", cells[:8])
        # embedded JSON blobs
        nd = soup.find("script", id="__NEXT_DATA__")
        print("has __NEXT_DATA__:", bool(nd), "len", len(nd.text) if nd else 0)
        ldjson = soup.find_all("script", type="application/json")
        print("application/json scripts:", len(ldjson))
        # does raw text contain a team + number pattern anywhere?
        hits = re.findall(r"(Ravens|Rams|Bills|Cardinals)\D{0,30}(\d{1,2}\.5)", r.text)
        print("sample team-number regex hits:", hits[:4])
    except Exception as e:
        print("ERROR", repr(e))

# ESPN FPI: try the JSON API endpoints
print("\n########## espn FPI api probes")
espn_urls = [
    "https://site.web.api.espn.com/apis/fitt/v3/sports/football/nfl/powerindex?region=us&lang=en&season=2026",
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/powerindex",
]
for u in espn_urls:
    try:
        r = requests.get(u, headers=HEADERS, timeout=25)
        print(u, "->", r.status_code, "len", len(r.text))
        if r.status_code == 200:
            print("  head:", r.text[:200])
    except Exception as e:
        print(u, "ERROR", repr(e))
