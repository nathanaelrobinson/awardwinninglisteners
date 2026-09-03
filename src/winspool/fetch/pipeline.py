import json
import os
from dataclasses import dataclass
from typing import Callable

import pandas as pd


@dataclass
class Source:
    name: str
    kind: str  # "totals" | "power"
    fetch: Callable[[], dict]


def refresh(sources, cache_dir, now="unknown"):
    """Fetch every source and write the aggregated cache files.

    Writes win_totals.csv (mean across all "totals" sources, columns
    team,win_total), power_ratings.csv (one column per "power" source, plus
    team), and sources_meta.json (provenance list). Returns the meta list.
    Raises ValueError on an unknown source kind.
    """
    os.makedirs(cache_dir, exist_ok=True)
    totals_cols, power_cols, meta = {}, {}, []
    for s in sources:
        if s.kind not in ("totals", "power"):
            raise ValueError(f"unknown source kind: {s.kind!r}")
        try:
            data = s.fetch()
        except Exception as e:  # one dead source (e.g. HTTP 520) must not abort the run
            print(f"  WARNING: source {s.name!r} failed, skipping: "
                  f"{type(e).__name__}: {e}")
            meta.append({"name": s.name, "kind": s.kind, "n_teams": 0,
                         "fetched_at": now, "ok": False, "error": f"{type(e).__name__}: {e}"})
            continue
        meta.append({"name": s.name, "kind": s.kind, "n_teams": len(data),
                     "fetched_at": now, "ok": True, "error": None})
        (totals_cols if s.kind == "totals" else power_cols)[s.name] = data
    if totals_cols:
        win_total = pd.DataFrame(totals_cols).mean(axis=1)
        (win_total.rename("win_total").rename_axis("team").reset_index()
         .to_csv(os.path.join(cache_dir, "win_totals.csv"), index=False))
    if power_cols:
        (pd.DataFrame(power_cols).rename_axis("team").reset_index()
         .to_csv(os.path.join(cache_dir, "power_ratings.csv"), index=False))
    with open(os.path.join(cache_dir, "sources_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    return meta
