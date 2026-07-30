import csv
import io
from ..teams import resolve


def parse_rating_table(rows, name_key, value_key):
    out = {}
    for row in rows:
        code = resolve(row.get(name_key, ""))
        if code is None:
            continue
        try:
            out[code] = float(row[value_key])
        except (TypeError, ValueError, KeyError):
            continue
    return out


def parse_csv_ratings(text, name_col, value_col):
    reader = csv.DictReader(io.StringIO(text))
    return parse_rating_table(list(reader), name_col, value_col)
