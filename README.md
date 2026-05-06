# Freysa Agent Simulation Toolkit

This repository contains a deterministic agent core inspired by the original
Freysa AI specification together with a lightweight simulation harness. The
goal is to provide a transparent way to test how the agent reacts to different
market scenarios while keeping the runtime deterministic and auditable.

## Project layout

```
.
├── agents/
│   ├── __init__.py          # Convenience exports for the Freysa agent
│   └── freysa_agent.py      # Core deterministic agent implementation
├── freysa0.py               # CLI utilities for running simulations
├── quantum_strat_v3.lisp    # Quantum-Entropic Strategist module (Common Lisp)
├── tests/                   # Test suite
├── pyproject.toml           # Project configuration
├── LICENSE
└── README.md
```

### `agents.freysa_agent`
The module exposes the `FreysaSentientAI` class, a deterministic agent core that
operates on simple oracle payloads containing price feeds and textual messages.
It supports dependency injection for clocks and limiter policies, keeps a bounded
memory log, normalizes incoming oracle payloads, and produces structured status
snapshots with deterministic market insights after each reasoning cycle.

### `freysa0.py`
The script offers a command-line interface around the agent to make it easy to
run repeatable simulations from JSON scenario files. It includes helpers to
summarize the resulting state and to generate a starter scenario template.


### `quantum_strat_v3.lisp`
A standalone Common Lisp module implementing the user-requested Cognitive Layer
V3 "Quantum-Entropic Strategist" with CLOS state objects, entropy-driven signal
collapse, strategy generation, and an executable startup loop.

## Getting started

### 1. Create (or export) a scenario file

```
python freysa0.py --generate-template > scenario.json
```

The generated file contains three sample updates with deterministic timestamps.
Edit the `price_feed`, `messages`, or `offset` fields to model your own market
conditions.

### 2. Run the simulation

```
python freysa0.py scenario.json
```

This will print the status after each cycle followed by the agent's memory log.
If you only need a concise view, use the `--summary` flag:

```
python freysa0.py scenario.json --summary
```

For a full run with a compact event-count section before the memory dump, add
`--events`:

```
python freysa0.py scenario.json --events
```

### 3. Interpreting the results

Each cycle status includes:
- the agent metadata (`name`, `version`, deterministic `id`),
- the internal state snapshot (awareness, health, inputs, etc.),
- the average asset price for the current cycle (when available),
- a `market_insight` block with asset count, min/max assets, spread, trend,
  risk level, and spike detection,
- the most recent normalized message seen by the agent,
- deterministic event counts, and
- how many memory entries are currently stored.

The memory log at the end reveals every logged event in chronological order,
providing full traceability of the reasoning path the agent followed.

## Development

### Running Tests

To run the test suite, ensure you have `pytest` installed (which is standard in many environments).

```bash
pip install pytest
pytest
```

## Extending the toolkit

- Implement a custom limiter by subclassing `agents.freysa_agent.SimpleLimiter`
  and injecting it into the `FreysaSimulation` helper.
- Replace the static clock with a more sophisticated deterministic clock that
  matches your environment.
- Build higher-level analytics by importing the `FreysaSimulation` class from
  `freysa0.py` and embedding it into larger evaluation pipelines.
- Use `FreysaSentientAI.recent_memory()` and `event_counts()` for lightweight
  diagnostics without parsing a full memory export.

## License

This project is distributed under the terms of the MIT License. See `LICENSE`
for details.
