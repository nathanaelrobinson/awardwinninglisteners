"""Seed data/cache with REAL 2026 numbers pulled 2026-07-30:
- win totals: mean of Covers + BetMGM
- power: ESPN FPI projected wins, converted to a points strength

Snapshot seeder (uses the real ingestion pipeline with in-memory sources). The
repeatable live scrapers live in winspool.fetch.registry; this just gets real
data into the sim now. Run: uv run python scripts/seed_real_data.py
"""
import numpy as np
from winspool.fetch.pipeline import Source, refresh
from winspool.ratings import WINS_PER_POINT
from winspool.teams import resolve

# --- win totals (nickname -> O/U) ---
COVERS = {
    "Cardinals": 4.5, "Falcons": 7.5, "Ravens": 11.5, "Bills": 10.5, "Panthers": 7.5,
    "Bears": 9.5, "Bengals": 10.5, "Browns": 5.5, "Cowboys": 9.5, "Broncos": 9.5,
    "Lions": 10.5, "Packers": 9.5, "Texans": 9.5, "Colts": 7.5, "Jaguars": 8.5,
    "Chiefs": 10.5, "Chargers": 9.5, "Rams": 11.5, "Raiders": 5.5, "Dolphins": 4.5,
    "Vikings": 8.5, "Patriots": 10.5, "Saints": 7.5, "Giants": 7.5, "Jets": 5.5,
    "Eagles": 10.5, "Steelers": 8.5, "49ers": 9.5, "Seahawks": 10.5, "Buccaneers": 8.5,
    "Titans": 6.5, "Commanders": 7.5,
}
BETMGM = {
    "Cardinals": 3.5, "Falcons": 7.5, "Ravens": 11.5, "Bills": 10.5, "Panthers": 7.5,
    "Bears": 9.5, "Bengals": 9.5, "Browns": 5.5, "Cowboys": 9.5, "Broncos": 9.5,
    "Lions": 10.5, "Packers": 9.5, "Texans": 9.5, "Colts": 7.5, "Jaguars": 9.5,
    "Chiefs": 10.5, "Chargers": 10.5, "Rams": 11.5, "Raiders": 5.5, "Dolphins": 4.5,
    "Vikings": 8.5, "Patriots": 10.5, "Saints": 7.5, "Giants": 7.5, "Jets": 5.5,
    "Eagles": 10.5, "Steelers": 8.5, "49ers": 10.5, "Seahawks": 10.5, "Buccaneers": 8.5,
    "Titans": 6.5, "Commanders": 7.5,
}
# --- ESPN FPI projected wins (nickname -> proj wins) ---
FPI_WINS = {
    "Rams": 11.1, "Bills": 10.7, "Ravens": 10.8, "Seahawks": 10.3, "49ers": 10.2,
    "Lions": 10.4, "Chiefs": 9.8, "Packers": 10.0, "Chargers": 9.7, "Eagles": 9.7,
    "Bengals": 10.0, "Texans": 9.2, "Jaguars": 9.0, "Patriots": 9.3, "Cowboys": 9.0,
    "Broncos": 9.1, "Bears": 9.2, "Buccaneers": 8.5, "Steelers": 8.4, "Falcons": 7.8,
    "Colts": 8.1, "Vikings": 8.2, "Commanders": 7.6, "Titans": 6.5, "Giants": 7.7,
    "Jets": 7.3, "Panthers": 6.7, "Browns": 5.8, "Raiders": 5.9, "Dolphins": 4.8,
    "Cardinals": 5.5, "Saints": 5.0,
}


def to_codes(d):
    return {resolve(name): float(v) for name, v in d.items()}


def fpi_points():
    """Convert projected wins to a neutral-margin points strength (mean 0)."""
    codes = to_codes(FPI_WINS)
    mean = np.mean(list(codes.values()))
    return {c: (w - mean) / WINS_PER_POINT for c, w in codes.items()}


def main():
    sources = [
        Source("covers", "totals", lambda: to_codes(COVERS)),
        Source("betmgm", "totals", lambda: to_codes(BETMGM)),
        Source("fpi", "power", fpi_points),
    ]
    meta = refresh(sources, "data/cache", now="2026-07-30")
    for m in meta:
        print(f"{m['name']:<8}{m['kind']:<8}{m['n_teams']} teams")
    print("wrote data/cache/win_totals.csv, power_ratings.csv, sources_meta.json")


if __name__ == "__main__":
    main()
