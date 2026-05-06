import json
import pytest
from agents import FreysaSentientAI, SimpleLimiter
from agents.freysa_agent import InputBundle, StaticClock

class TestFreysaAgent:
    def test_initialization(self):
        agent = FreysaSentientAI(name="TestAI", version="0.1")
        assert agent.name == "TestAI"
        assert agent.version == "0.1"
        assert agent.id is not None
        assert agent.state.health == "idle"
        assert len(agent.memory) == 1
        assert agent.memory[0].event == "boot"

    def test_run_cycle_basic(self):
        agent = FreysaSentientAI()
        payload = {
            "price_feed": {"BTC": 50000.0},
            "messages": ["hello"]
        }
        status = agent.run_cycle(payload, current_time=100)

        assert status["state"]["last_update"] == 100
        assert status["state"]["health"] == "idle" # Assuming 50k is not a spike
        assert status["last_message"] == "hello"
        assert status["avg_price"] == 50000.0
        assert agent.state.inputs.price_feed == {"BTC": 50000.0}

        # Check logs
        events = [e.event for e in agent.memory]
        assert "oracle_input" in events
        assert "reflect" in events
        assert "self_update" in events

    def test_run_cycle_spike(self):
        agent = FreysaSentientAI()
        # BTC spike threshold is 690_000_000_000
        spike_price = 700_000_000_000.0
        payload = {
            "price_feed": {"BTC": spike_price},
            "messages": ["panic"]
        }
        status = agent.run_cycle(payload, current_time=200)

        assert status["state"]["health"] == "active"

    def test_invalid_payload(self):
        agent = FreysaSentientAI()
        status = agent.run_cycle("invalid", current_time=300)

        assert status["state"]["health"] == "idle"
        assert agent.memory[-1].event == "error"

    def test_memory_export_reset(self):
        agent = FreysaSentientAI()
        agent.run_cycle({"messages": ["one"]}, current_time=1)

        dump = agent.export_memory()
        assert isinstance(dump, str)
        data = json.loads(dump)
        assert len(data) > 1

        agent.reset_memory()
        # Wait, reset_memory does:
        # self.memory.clear()
        # self.state = SelfState()
        # self._log("reset", ...)
        # So memory should have 1 entry

        assert len(agent.memory) == 1
        assert agent.memory[0].event == "reset"

    def test_limiter(self):
        limiter = SimpleLimiter()
        assert not limiter.spike({})
        assert not limiter.spike({"BTC": 100})
        assert limiter.spike({"BTC": SimpleLimiter.BTC_SPIKE + 1})
        assert limiter.spike({"ETH": SimpleLimiter.ETH_SPIKE + 1})
        # AVG SPIKE is 6_290_000_000.0
        assert limiter.spike({"A": 7_000_000_000.0})

    def test_market_insight_tracks_risk_and_trend(self):
        agent = FreysaSentientAI()

        first = agent.run_cycle(
            {"price_feed": {"btc": 100.0, "ETH": 300.0}, "messages": [" baseline "]},
            current_time=10,
        )
        assert first["market_insight"]["asset_count"] == 2
        assert first["market_insight"]["average_price"] == 200.0
        assert first["market_insight"]["trend"] == "baseline"
        assert first["market_insight"]["risk_level"] == "normal"
        assert first["last_message"] == "baseline"

        second = agent.run_cycle(
            {"price_feed": {"BTC": SimpleLimiter.BTC_SPIKE + 1, "ETH": 500.0}},
            current_time=20,
        )
        assert second["state"]["health"] == "active"
        assert second["market_insight"]["trend"] == "rising"
        assert second["market_insight"]["risk_level"] == "critical"
        assert second["market_insight"]["spike_detected"] is True

    def test_input_normalization_warns_and_recent_memory_filters(self):
        agent = FreysaSentientAI()
        status = agent.run_cycle(
            {
                "price_feed": {
                    " btc ": "42.5",
                    "BAD": "nope",
                    "NEG": -1,
                },
                "messages": [" ok ", "", 12],
                "extra": "ignored",
            },
            current_time=50,
        )

        assert status["state"]["inputs"]["price_feed"] == {"BTC": 42.5}
        assert status["state"]["inputs"]["messages"] == ["ok"]
        assert status["event_counts"]["warn"] == 3
        warnings = agent.recent_memory(limit=10, event="warn")
        assert [entry["event"] for entry in warnings] == ["warn", "warn", "warn"]
