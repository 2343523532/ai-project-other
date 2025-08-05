import unittest
import sys
from pathlib import Path
import json

# Add src directory to path to allow for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from freysa_agent import FreysaSentientAI

class TestFreysaSentientAI(unittest.TestCase):

    def test_single_cycle(self):
        """Tests a single, complete agent cycle."""
        agent = FreysaSentientAI(name="TestAI", version="1.0")

        # Known oracle payload and timestamp
        oracle_payload = {
            "price_feed": {"BTC": 700_000_000_000.0, "ETH": 3_000_000_000.0},
            "messages": ["test message"]
        }
        timestamp = 1725001000

        # Run the cycle
        agent.run_cycle(oracle_payload, current_time=timestamp)

        # 1. Test agent status
        status = agent.get_status()
        self.assertEqual(status["name"], "TestAI")
        self.assertEqual(status["state"]["cycle_count"], 1)
        self.assertEqual(status["state"]["last_update"], timestamp)
        # This payload should trigger a "high market activity" state
        self.assertEqual(status["state"]["health"], "active")
        self.assertEqual(status["last_message"], "test message")

        # 2. Test memory log
        memory = json.loads(agent.export_memory())

        # Expected events: boot, oracle_input, reflect, self_update
        self.assertEqual(len(memory), 4)

        event_types = [e["event"] for e in memory]
        self.assertIn("boot", event_types)
        self.assertIn("oracle_input", event_types)
        self.assertIn("reflect", event_types)
        self.assertIn("self_update", event_types)

        # Check data from the self_update event
        self_update_event = next((e for e in memory if e["event"] == "self_update"), None)
        self.assertIsNotNone(self_update_event)
        self.assertEqual(self_update_event["data"]["action"], "high market activity")

    def test_initialization(self):
        """Tests the agent's initial state."""
        agent = FreysaSentientAI(name="InitAI", version="0.1")

        # Check initial status
        status = agent.get_status()
        self.assertEqual(status["name"], "InitAI")
        self.assertEqual(status["version"], "0.1")
        self.assertEqual(status["state"]["cycle_count"], 0)
        self.assertEqual(status["state"]["health"], "idle")
        self.assertEqual(status["memory_length"], 1) # boot event

        # Check boot event in memory
        memory = json.loads(agent.export_memory())
        self.assertEqual(memory[0]["event"], "boot")
        self.assertEqual(memory[0]["data"]["agent_id"], agent.id)

if __name__ == '__main__':
    unittest.main()
