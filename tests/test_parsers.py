from winspool.teams import resolve
from winspool.fetch.parsers import parse_rating_table, parse_csv_ratings


def test_resolve_code_nickname_and_full_name():
    assert resolve("KC") == "KC"
    assert resolve("chiefs") == "KC"
    assert resolve("Kansas City Chiefs") == "KC"
    assert resolve("  Buffalo Bills ") == "BUF"


def test_resolve_unknown_is_none():
    assert resolve("Not A Real Team") is None
    assert resolve("") is None


def test_parse_rating_table_resolves_and_skips_unknown():
    rows = [{"name": "Chiefs", "r": "6.0"},
            {"name": "Bogus", "r": "1.0"},
            {"name": "Bills", "r": "not_a_number"}]
    out = parse_rating_table(rows, "name", "r")
    assert out == {"KC": 6.0}  # Bogus skipped (unresolved), Bills skipped (bad value)


def test_parse_csv_ratings_from_text():
    text = open("tests/fixtures/power_table.csv").read()
    out = parse_csv_ratings(text, "name", "rating")
    assert out == {"KC": 6.0, "BUF": 6.5}  # bogus row dropped
