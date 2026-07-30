N_TEAMS = 32
N_PLAYERS = 6
ROSTER_SIZE = 5
N_PICKS = 30

_DIVISIONS = {
    "AFC East": ["BUF", "MIA", "NE", "NYJ"],
    "AFC North": ["BAL", "CIN", "CLE", "PIT"],
    "AFC South": ["HOU", "IND", "JAX", "TEN"],
    "AFC West": ["DEN", "KC", "LAC", "LV"],
    "NFC East": ["DAL", "NYG", "PHI", "WAS"],
    "NFC North": ["CHI", "DET", "GB", "MIN"],
    "NFC South": ["ATL", "CAR", "NO", "TB"],
    "NFC West": ["ARI", "LA", "SEA", "SF"],
}

DIVISION = {code: div for div, codes in _DIVISIONS.items() for code in codes}
TEAMS = sorted(DIVISION.keys())
TEAM_INDEX = {code: i for i, code in enumerate(TEAMS)}

assert len(TEAMS) == N_TEAMS
