"""Login throttle: exponential backoff per player name."""
import pytest

from winspool.throttle import Throttle


def test_first_attempts_are_free():
    t = Throttle(free=4, cap=300.0)
    for _ in range(4):
        assert t.retry_after("Nate", now=0.0) == 0.0
        t.fail("Nate", now=0.0)


def test_backoff_starts_after_the_free_attempts():
    t = Throttle(free=4, cap=300.0)
    for _ in range(5):
        t.fail("Nate", now=0.0)
    assert t.retry_after("Nate", now=0.0) == 2.0


def test_backoff_doubles_with_each_further_failure():
    t = Throttle(free=4, cap=300.0)
    for _ in range(5):
        t.fail("Nate", now=0.0)
    seen = []
    for _ in range(4):
        seen.append(t.retry_after("Nate", now=0.0))
        t.fail("Nate", now=0.0)
    assert seen == [2.0, 4.0, 8.0, 16.0]


def test_backoff_is_capped():
    t = Throttle(free=4, cap=300.0)
    for _ in range(40):
        t.fail("Nate", now=0.0)
    assert t.retry_after("Nate", now=0.0) == 300.0


def test_penalty_expires_once_the_delay_has_passed():
    t = Throttle(free=4, cap=300.0)
    for _ in range(5):
        t.fail("Nate", now=100.0)
    assert t.retry_after("Nate", now=101.0) == 1.0
    assert t.retry_after("Nate", now=102.0) == 0.0


def test_success_clears_the_penalty():
    t = Throttle(free=4, cap=300.0)
    for _ in range(10):
        t.fail("Nate", now=0.0)
    assert t.retry_after("Nate", now=0.0) > 0
    t.succeed("Nate")
    assert t.retry_after("Nate", now=0.0) == 0.0


def test_throttling_one_name_does_not_throttle_another():
    t = Throttle(free=4, cap=300.0)
    for _ in range(10):
        t.fail("Nate", now=0.0)
    assert t.retry_after("Nate", now=0.0) > 0
    assert t.retry_after("Mitch", now=0.0) == 0.0


def test_stale_entries_are_evicted_so_junk_names_cannot_grow_the_table():
    t = Throttle(free=4, cap=300.0)
    for i in range(500):
        t.fail(f"junk-{i}", now=0.0)
    # Long after every penalty above has expired, one more failure prunes them.
    t.fail("Nate", now=10_000.0)
    assert len(t) < 50


def test_table_stays_bounded_even_while_every_entry_is_still_live():
    """Junk names posted in a burst all sit inside the idle window, so the
    idle purge cannot reclaim them; a hard cap has to."""
    t = Throttle(free=4, cap=300.0)
    for i in range(10_000):
        t.fail(f"junk-{i}", now=0.0)
    assert len(t) <= 1024


def test_the_cap_evicts_junk_before_a_player_under_active_attack():
    t = Throttle(free=4, cap=300.0)
    for _ in range(10):
        t.fail("Nate", now=0.0)
    for i in range(10_000):
        t.fail(f"junk-{i}", now=1.0)
    assert t.retry_after("Nate", now=1.0) > 0
