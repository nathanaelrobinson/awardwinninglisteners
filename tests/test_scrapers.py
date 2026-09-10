from winspool.fetch.scrapers import parse_win_total_table, parse_espn_fpi

ESPN_JSON = {
    "teams": [
        {"team": {"displayName": "Los Angeles Rams", "abbreviation": "LAR"},
         "categories": [{"name": "fpi", "values": [5.574, 3.9]},
                        {"name": "projections", "values": [11.09, 5.86]}]},
        {"team": {"displayName": "Arizona Cardinals", "abbreviation": "ARI"},
         "categories": [{"name": "fpi", "values": [-4.2]}]},
    ]
}


def _pad(rows):
    body = "".join(f"<tr><td>{name}</td><td>{tot}</td></tr>" for name, tot in rows)
    return f"<table><tr><th>Team</th><th>Total</th></tr>{body}</table>"


def test_parse_win_total_table_maps_and_resolves():
    # 21 rows so the >=20 sanity guard passes; parsers key by TEAM CODE string.
    rows = [("Cardinals", 4.5), ("Ravens", 11.5), ("Bills", 10.5), ("49ers", 9.5),
            ("Commanders", 7.5), ("Chiefs", 10.5), ("Eagles", 10.5), ("Lions", 10.5),
            ("Packers", 9.5), ("Bears", 9.5), ("Vikings", 8.5), ("Cowboys", 9.5),
            ("Giants", 7.5), ("Jets", 5.5), ("Dolphins", 4.5), ("Patriots", 10.5),
            ("Steelers", 8.5), ("Browns", 5.5), ("Bengals", 10.0), ("Texans", 9.5),
            ("Titans", 6.5)]
    out = parse_win_total_table(_pad(rows))
    assert out["ARI"] == 4.5
    assert out["BAL"] == 11.5
    assert out["SF"] == 9.5       # "49ers" nickname resolves
    assert out["WAS"] == 7.5      # "Commanders" resolves
    assert len(out) == 21


def test_parse_win_total_table_below_guard_returns_empty():
    # fewer than 20 resolvable rows -> not a real 32-team table -> {}
    assert parse_win_total_table(_pad([("Cardinals", 4.5), ("Ravens", 11.5)])) == {}


def test_parse_win_total_table_betmgm_full_names():
    rows = [("Arizona Cardinals", 3.5), ("Baltimore Ravens", 11.5)]
    filler = [(n, 8.5) for n in [
        "Buffalo Bills", "Carolina Panthers", "Chicago Bears", "Cincinnati Bengals",
        "Cleveland Browns", "Dallas Cowboys", "Denver Broncos", "Detroit Lions",
        "Green Bay Packers", "Houston Texans", "Indianapolis Colts", "Jacksonville Jaguars",
        "Kansas City Chiefs", "Las Vegas Raiders", "Los Angeles Chargers", "Miami Dolphins",
        "Minnesota Vikings", "New England Patriots", "New Orleans Saints"]]
    body = "".join(f"<tr><td>{n}</td><td>{t}</td><td>x</td><td>y</td></tr>"
                   for n, t in rows + filler)
    html = (f"<table><tr><th>Team</th><th>Win Total</th><th>Over</th><th>Under</th></tr>"
            f"{body}</table>")
    out = parse_win_total_table(html)
    assert out["ARI"] == 3.5
    assert out["BAL"] == 11.5


def test_parse_espn_fpi():
    out = parse_espn_fpi(ESPN_JSON)
    assert out["LA"] == 5.574     # first fpi value; displayName resolves
    assert out["ARI"] == -4.2
    assert len(out) == 2


def test_epa_from_pbp():
    import pandas as pd
    from winspool.fetch.scrapers import epa_from_pbp
    df = pd.DataFrame({
        "posteam": ["KC", "KC", "NYJ", "NYJ"],
        "defteam": ["NYJ", "NYJ", "KC", "KC"],
        "epa": [0.5, 0.5, -0.5, -0.5],
        "pass": [1, 1, 1, 0], "rush": [0, 0, 0, 1],
    })
    out = epa_from_pbp(df)
    assert out["KC"] > out["NYJ"]                 # KC efficient, NYJ not
    assert abs(out["KC"] + out["NYJ"]) < 1e-6     # mean-centered
