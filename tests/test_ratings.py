import numpy as np
from winspool.ratings import strength_from_totals

def test_higher_total_gets_higher_strength():
    totals = np.array([11.5, 6.5, 9.0])
    s = strength_from_totals(totals)
    assert s[0] > s[2] > s[1]

def test_strengths_mean_centered():
    s = strength_from_totals(np.array([11.5, 6.5, 9.0, 8.0]))
    assert abs(s.mean()) < 1e-9
