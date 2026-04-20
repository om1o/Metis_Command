"""Mission pool bounded submission."""

from __future__ import annotations

import time

import pytest


class _Dummy:
    status = "success"
    final_answer = "ok"


def _install_fake_mission(monkeypatch, delay: float = 0.05):
    import autonomous_loop
    def fake(**_kw):
        time.sleep(delay)
        return _Dummy()
    monkeypatch.setattr(autonomous_loop, "run_mission", fake)


def test_pool_respects_max_queue(monkeypatch):
    monkeypatch.setenv("METIS_MAX_WORKERS", "1")
    monkeypatch.setenv("METIS_MAX_QUEUE", "2")
    _install_fake_mission(monkeypatch, delay=0.2)

    from concurrency import MissionPool, PoolFull
    pool = MissionPool()

    r1 = pool.submit("first")
    r2 = pool.submit("second")
    with pytest.raises(PoolFull):
        pool.submit("third")
    assert r1.id != r2.id


def test_pool_stats_shape(monkeypatch):
    monkeypatch.setenv("METIS_MAX_WORKERS", "2")
    monkeypatch.setenv("METIS_MAX_QUEUE", "5")
    _install_fake_mission(monkeypatch)
    from concurrency import MissionPool
    pool = MissionPool()
    s = pool.stats()
    assert s["max_workers"] == 2
    assert s["max_queue_depth"] == 5
    assert "by_status" in s
