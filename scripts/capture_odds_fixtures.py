"""Capture live ESPN and Kalshi payloads as test fixtures.
Run manually (needs network): uv run python scripts/capture_odds_fixtures.py 2026 1
"""
import json
import sys

import requests

ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
KALSHI = "https://external-api.kalshi.com/trade-api/v2/markets"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def main():
    season, week = int(sys.argv[1]), int(sys.argv[2])
    espn = requests.get(ESPN, params={"dates": season, "seasontype": 2, "week": week},
                        timeout=30).json()
    with open(f"tests/fixtures/espn_scoreboard_{season}_wk{week}.json", "w") as f:
        json.dump(espn, f)
    print(f"espn: {len(espn.get('events', []))} events")

    kalshi = requests.get(KALSHI, params={"series_ticker": "KXNFLGAME",
                                          "status": "open", "limit": 1000},
                          headers=HEADERS, timeout=30).json()
    with open(f"tests/fixtures/kalshi_games_{season}_wk{week}.json", "w") as f:
        json.dump(kalshi, f)
    print(f"kalshi: {len(kalshi.get('markets', []))} markets")


if __name__ == "__main__":
    main()
