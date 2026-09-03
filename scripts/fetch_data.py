"""Fetch the real 2026 schedule into a CSV the loaders read.
Run manually (needs network): python scripts/fetch_data.py
Win totals are maintained by hand in data/cache/win_totals.csv (team,win_total)."""
import os
import nfl_data_py as nfl

CACHE = "data/cache"

def main():
    os.makedirs(CACHE, exist_ok=True)
    sched = nfl.import_schedules([2026])
    cols = sched.rename(columns={"game_type": "game_type"})[["home_team", "away_team", "game_type"]]
    cols.to_csv(f"{CACHE}/schedule_2026.csv", index=False)
    print(f"Wrote {CACHE}/schedule_2026.csv ({len(cols)} games)")

if __name__ == "__main__":
    main()
