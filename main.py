"""
Main entry point for running a Freysa agent simulation.

This script loads a deterministic agent, provides it with a sample stream
of oracle updates, and prints the agent's status after each cycle. Finally,
it dumps the agent's full memory log.
"""

import json
import sys
from pathlib import Path

# Add src directory to path to allow for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from freysa_agent import FreysaSentientAI


def main():
    """Runs a deterministic agent simulation."""
    print("── freysa_agent deterministic demo ──")
    agent = FreysaSentientAI(name="AllPurposeAI", version="3.4")

    # Sample oracle updates, mimicking an external data feed.
    oracle_updates = [
        {"price_feed": {"BTC": 687_285_012_000.0, "ETH": 3_125_500_000.0}, "messages": ["hi"]},
        {"price_feed": {"BTC": 696_291_000_000.0, "ETH": 3_130_000_000.0}, "messages": ["status?"]},
        {"price_feed": {"BTC": 686_300_540_000.0, "ETH": 3_152_200_000.0}, "messages": ["thanks"]},
    ]

    deterministic_time = 1_725_000_000
    for step, update in enumerate(oracle_updates):
        now = deterministic_time + step
        print(f"\n--- CYCLE {step + 1} @ t={now} ---")
        print("Oracle Payload:", json.dumps(update, indent=2))
        agent.run_cycle(update, current_time=now)
        print("Agent Status:", json.dumps(agent.get_status(), indent=2))

    print("\n==== FULL MEMORY LOG ====")
    print(agent.export_memory(pretty=True))


if __name__ == "__main__":
    main()
