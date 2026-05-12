"""Agent bus publish / inbox / drain."""

from __future__ import annotations


def test_publish_to_direct_inbox():
    import agent_bus as bus
    bus.publish(bus.AgentMessage(
        from_slug="tester", to_slug="subject", kind="ping", payload={"x": 1},
    ))
    msgs = bus.drain("subject", limit=10, timeout=0.5)
    assert any(m.kind == "ping" and m.payload.get("x") == 1 for m in msgs)


def test_publish_to_channel_hits_subscribers():
    import agent_bus as bus
    bus.subscribe(bus.ALERTS, "agent-a")
    bus.subscribe(bus.ALERTS, "agent-b")
    bus.publish(bus.AgentMessage(from_slug="sys", channel=bus.ALERTS,
                                  kind="notice", payload={}))
    assert any(m.kind == "notice" for m in bus.drain("agent-a", timeout=0.2))
    assert any(m.kind == "notice" for m in bus.drain("agent-b", timeout=0.2))


def test_drain_timeout_returns_empty_quickly():
    import time
    import agent_bus as bus
    t0 = time.time()
    msgs = bus.drain("nobody-home", limit=5, timeout=0.1)
    assert msgs == []
    assert time.time() - t0 < 0.8
