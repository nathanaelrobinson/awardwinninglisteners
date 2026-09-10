import pytest

from winspool.gameodds import (GameOdds, market_prob, prob_from_kalshi,
                               prob_from_moneyline, prob_from_spread, to_prob)


def _o(source, **kw):
    base = dict(source=source, home="KC", away="DEN", fetched_at=0.0, spread=None,
                total=None, ml_home=None, ml_away=None, yes_home=None,
                yes_away=None, p_home=None)
    base.update(kw)
    return GameOdds(**base)


def test_home_favourite_spread_is_negative_and_above_half():
    # ESPN quotes the home side: KC -2.5 means Kansas City favoured by 2.5.
    assert prob_from_spread(-2.5) == pytest.approx(0.5735, abs=1e-4)
    assert prob_from_spread(3.5) == pytest.approx(0.3977, abs=1e-3)


def test_moneyline_devig_sums_to_one_and_removes_the_overround():
    # DEN @ KC, Week 1 2026: DraftKings closed -148 / +124, a 4.3% vig.
    p = prob_from_moneyline(-148, 124)
    assert p == pytest.approx(0.572, abs=1e-3)


def test_kalshi_prices_are_normalised():
    assert prob_from_kalshi(0.55, 0.47) == pytest.approx(0.55 / 1.02)


def test_kalshi_rejects_a_dead_market():
    assert prob_from_kalshi(0.0, 0.0) is None


def test_to_prob_reads_the_sources_in_priority_order():
    # model probability > kalshi > moneyline > spread > nothing usable.
    assert to_prob(_o("model", p_home=0.61, yes_home=0.9, yes_away=0.1,
                      ml_home=-148, ml_away=124, spread=-7.0)) == pytest.approx(0.61)
    assert to_prob(_o("kalshi", yes_home=0.55, yes_away=0.47, ml_home=-148,
                      ml_away=124, spread=-7.0)) == pytest.approx(0.55 / 1.02)
    assert to_prob(_o("book", spread=-7.0, ml_home=-148, ml_away=124)) == (
        pytest.approx(prob_from_moneyline(-148, 124)))
    assert to_prob(_o("nflverse", spread=-2.5)) == pytest.approx(prob_from_spread(-2.5))
    assert to_prob(_o("nflverse")) is None


def test_market_prob_averages_book_and_kalshi():
    book = _o("book", ml_home=-148, ml_away=124)
    kalshi = _o("kalshi", yes_home=0.565, yes_away=0.45)
    got = market_prob([book, kalshi])
    assert got == pytest.approx((to_prob(book) + to_prob(kalshi)) / 2)


def test_market_prob_ignores_the_model_and_prefers_markets_to_nflverse():
    book = _o("book", ml_home=-148, ml_away=124)
    odds = [_o("model", p_home=0.9), _o("nflverse", spread=-9.5), book]
    assert market_prob(odds) == pytest.approx(to_prob(book))


def test_market_prob_falls_back_to_nflverse_then_gives_up():
    assert market_prob([_o("nflverse", spread=-2.5)]) == pytest.approx(
        prob_from_spread(-2.5))
    assert market_prob([]) is None
    assert market_prob([_o("model", p_home=0.7)]) is None
