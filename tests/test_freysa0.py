import json
import pytest
from pathlib import Path
from freysa0 import FreysaScenario, ScenarioUpdate, FreysaSimulation, load_scenario, template_scenario

class TestFreysaScenario:
    def test_scenario_serialization(self):
        scenario = FreysaScenario(
            agent_name="TestAgent",
            agent_version="1.0",
            start_time=1000,
            updates=[
                ScenarioUpdate(offset=0, messages=["start"]),
                ScenarioUpdate(offset=10, price_feed={"BTC": 100.0})
            ]
        )

        json_data = scenario.to_json()
        assert json_data["agent"]["name"] == "TestAgent"
        assert len(json_data["updates"]) == 2

        loaded = FreysaScenario.from_json(json_data)
        assert loaded.agent_name == "TestAgent"
        assert loaded.start_time == 1000
        assert len(loaded.updates) == 2
        assert loaded.updates[0].messages == ["start"]

    def test_load_scenario_file(self, tmp_path):
        f = tmp_path / "scenario.json"
        scenario = template_scenario()
        f.write_text(json.dumps(scenario.to_json()))

        loaded = load_scenario(f)
        assert loaded.agent_name == "AllPurposeAI"

    def test_load_scenario_file_not_found(self, tmp_path):
        f = tmp_path / "nonexistent.json"
        with pytest.raises(FileNotFoundError):
            load_scenario(f)

class TestFreysaSimulation:
    def test_run_simulation(self):
        scenario = FreysaScenario(
            agent_name="SimAgent",
            agent_version="0.1",
            start_time=1000,
            updates=[
                ScenarioUpdate(offset=0, messages=["msg1"]),
                ScenarioUpdate(offset=10, messages=["msg2"])
            ]
        )

        sim = FreysaSimulation(scenario)
        result = sim.run()

        assert len(result.statuses) == 2
        assert result.statuses[0]["last_message"] == "msg1"
        assert result.statuses[1]["last_message"] == "msg2"

        summary = result.summary()
        assert summary["cycles"] == 2

        memory = json.loads(result.memory_dump)
        assert len(memory) > 0

    def test_summary_includes_analysis_fields(self):
        scenario = FreysaScenario(
            agent_name="SummaryAgent",
            agent_version="0.2",
            start_time=1000,
            updates=[
                ScenarioUpdate(offset=0, price_feed={"BTC": 100.0}, messages=["start"]),
                ScenarioUpdate(offset=10, price_feed={"BTC": 110.0}, messages=["urgent crash"]),
            ],
        )

        result = FreysaSimulation(scenario).run()
        summary = result.summary()

        assert summary["peak_risk_score"] >= 30
        assert summary["alert_count"] >= 2
        assert summary["final_trend"] == "rising"

    def test_load_scenario_rejects_unsorted_offsets(self, tmp_path):
        f = tmp_path / "scenario.json"
        f.write_text(json.dumps({
            "updates": [
                {"offset": 10, "messages": ["late"]},
                {"offset": 5, "messages": ["early"]},
            ]
        }))

        with pytest.raises(ValueError, match="offsets"):
            load_scenario(f)
