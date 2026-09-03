from winspool import server


def test_cache_key_changes_when_kalshi_file_changes(tmp_path, monkeypatch):
    """The sim-matrix cache key must depend on the Kalshi distributions file —
    a Kalshi-only refresh should invalidate the cached matrix, since build_wins
    uses it for both the 'kalshi' source voice and per-team variance calibration."""
    kalshi_path = tmp_path / "kalshi_distributions.csv"
    monkeypatch.setattr(server, "KALSHI", kalshi_path)

    key_absent = server._cache_key()

    kalshi_path.write_text("team,p0\nKC,1.0\n")
    key_v1 = server._cache_key()
    assert key_v1 != key_absent

    # touch mtime with different content to make sure it's tracked
    import time
    time.sleep(0.01)
    kalshi_path.write_text("team,p0\nKC,0.5\n")
    key_v2 = server._cache_key()
    assert key_v2 != key_v1
