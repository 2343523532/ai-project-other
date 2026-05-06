"""Command-line utilities for running deterministic Freysa agent simulations."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from agents import FreysaSentientAI


@dataclass(slots=True)
class ScenarioUpdate:
    """Single update entry for the agent simulation."""

    offset: int
    price_feed: Optional[dict] = None
    messages: Optional[List[str]] = None

    def payload(self) -> dict:
        data: dict = {}
        if self.price_feed:
            data["price_feed"] = self.price_feed
        if self.messages:
            data["messages"] = self.messages
        return data


@dataclass(slots=True)
class FreysaScenario:
    """A deterministic sequence of updates to feed into the agent."""

    agent_name: str
    agent_version: str
    start_time: int
    updates: List[ScenarioUpdate]

    @classmethod
    def from_json(cls, raw: dict) -> "FreysaScenario":
        try:
            updates_raw = raw["updates"]
        except KeyError as exc:  # pragma: no cover - defensive guard
            raise ValueError("Scenario missing 'updates' key") from exc

        updates = [
            ScenarioUpdate(
                offset=int(item.get("offset", 0)),
                price_feed=item.get("price_feed"),
                messages=item.get("messages"),
            )
            for item in updates_raw
        ]
        return cls(
            agent_name=str(raw.get("agent", {}).get("name", "Freysa")),
            agent_version=str(raw.get("agent", {}).get("version", "1.0")),
            start_time=int(raw.get("start_time", 0)),
            updates=updates,
        )

    def to_json(self) -> dict:
        return {
            "agent": {"name": self.agent_name, "version": self.agent_version},
            "start_time": self.start_time,
            "updates": [
                {
                    "offset": update.offset,
                    "price_feed": update.price_feed,
                    "messages": update.messages,
                }
                for update in self.updates
            ],
        }


@dataclass(slots=True)
class SimulationResult:
    """Container for the statuses produced during a scenario run."""

    statuses: List[dict]
    memory_dump: str

    def summary(self) -> dict:
        cycles = len(self.statuses)
        last_state = self.statuses[-1]["state"] if self.statuses else {}
        last_health = last_state.get("health")
        avg_prices = [status.get("avg_price") for status in self.statuses if status.get("avg_price") is not None]
        avg_price = sum(avg_prices) / len(avg_prices) if avg_prices else None
        risk_levels = [
            status.get("market_insight", {}).get("risk_level")
            for status in self.statuses
            if status.get("market_insight")
        ]
        health_counts = _count_values(
            status.get("state", {}).get("health") for status in self.statuses
        )
        risk_counts = _count_values(risk_levels)
        memory_entries = json.loads(self.memory_dump) if self.memory_dump else []
        event_counts = _count_values(entry.get("event") for entry in memory_entries)
        return {
            "cycles": cycles,
            "last_health": last_health,
            "avg_price_mean": round(avg_price, 2) if avg_price is not None else None,
            "spike_cycles": sum(
                1 for status in self.statuses if status.get("market_insight", {}).get("spike_detected")
            ),
            "health_counts": health_counts,
            "risk_counts": risk_counts,
            "event_counts": event_counts,
            "last_market_insight": self.statuses[-1].get("market_insight") if self.statuses else None,
            "memory_entries": len(memory_entries),
        }


def _count_values(values: Iterable[object]) -> dict:
    """Count non-empty values in deterministic key order."""
    counts: dict = {}
    for value in values:
        if value is None:
            continue
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


class FreysaSimulation:
    """High-level orchestration helper for Freysa deterministic runs."""

    def __init__(self, scenario: FreysaScenario) -> None:
        self.scenario = scenario
        self.agent = FreysaSentientAI(
            name=scenario.agent_name, version=scenario.agent_version
        )

    def run(self) -> SimulationResult:
        statuses: List[dict] = []
        base = self.scenario.start_time
        for update in self.scenario.updates:
            current_time = base + update.offset
            status = self.agent.run_cycle(update.payload(), current_time=current_time)
            statuses.append(status)
        memory_dump = self.agent.export_memory(pretty=True)
        return SimulationResult(statuses=statuses, memory_dump=memory_dump)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "scenario",
        type=Path,
        nargs="?",
        help="Path to a JSON file describing the scenario to execute.",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Only print a summary after execution instead of every cycle status.",
    )
    parser.add_argument(
        "--generate-template",
        action="store_true",
        help="Print a template scenario JSON to stdout and exit.",
    )
    parser.add_argument(
        "--events",
        action="store_true",
        help="Include deterministic event counts when printing a full run.",
    )
    return parser.parse_args(argv)


def template_scenario() -> FreysaScenario:
    return FreysaScenario(
        agent_name="AllPurposeAI",
        agent_version="3.4",
        start_time=1_725_000_000,
        updates=[
            ScenarioUpdate(
                offset=0,
                price_feed={"BTC": 687_285_012_000.0, "ETH": 3_125_500_000.0},
                messages=["hi"],
            ),
            ScenarioUpdate(
                offset=60,
                price_feed={"BTC": 696_291_000_000.0, "ETH": 3_130_000_000.0},
                messages=["status?"],
            ),
            ScenarioUpdate(
                offset=120,
                price_feed={"BTC": 686_300_540_000.0, "ETH": 3_152_200_000.0},
                messages=["thanks"],
            ),
        ],
    )


def load_scenario(path: Path) -> FreysaScenario:
    if not path.exists():
        raise FileNotFoundError(f"Scenario file not found: {path}")
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError("Scenario file must contain a JSON object")
    return FreysaScenario.from_json(raw)


def display_statuses(statuses: Iterable[dict]) -> None:
    for index, status in enumerate(statuses, start=1):
        print(f"\n--- cycle {index} ---")
        print(json.dumps(status, indent=2))


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    if args.generate_template:
        scenario = template_scenario()
        json.dump(scenario.to_json(), sys.stdout, indent=2)
        print()
        return 0

    if args.scenario is None:
        print("No scenario file provided. Use --generate-template to create one.", file=sys.stderr)
        return 2

    try:
        scenario = load_scenario(args.scenario)
    except (OSError, ValueError) as exc:
        print(f"Failed to load scenario: {exc}", file=sys.stderr)
        return 2

    sim = FreysaSimulation(scenario)
    result = sim.run()

    if args.summary:
        print(json.dumps(result.summary(), indent=2))
    else:
        display_statuses(result.statuses)
        if args.events:
            print("\n==== event counts ====")
            print(json.dumps(result.summary()["event_counts"], indent=2))
        print("\n==== memory dump ====")
        print(result.memory_dump)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
