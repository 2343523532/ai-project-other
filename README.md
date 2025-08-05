# Freysa: Deterministic AI Agent

This project provides a reference implementation of a deterministic, hardware-agnostic AI agent designed for high-stakes environments like Trusted Execution Environments (TEEs) or on-chain smart contracts.

The agent, named "Freysa", is built to be stateless in its execution, processing external data from "oracles" in discrete cycles. It maintains a memory log of its operations, which can be exported and audited.

## Features

- **Deterministic Execution**: Given the same input, the agent will always produce the same output, which is critical for on-chain applications.
- **Stateful Memory**: The agent logs all events, inputs, and state changes to an internal, capacity-bounded memory buffer.
- **Pluggable Components**: Core logic like timekeeping (`Clock`) and action triggers (`Limiter`) are defined by protocols, allowing for custom implementations.
- **Price Spike Detection**: A reference `Limiter` implementation is included to demonstrate how the agent can react to market volatility based on price feeds.
- **Configurable**: Agent properties can be defined in a `freysa.yaml` configuration file (though this is not yet fully implemented in the runner).

## Project Structure

```
.
├── freysa.yaml         # Configuration for the agent (currently informational).
├── LICENSE             # Project license.
├── main.py             # Main entrypoint to run the agent simulation.
├── README.md           # This file.
├── requirements.txt    # Python dependencies.
├── src/
│   └── freysa_agent.py # The core agent source code.
└── tests/
    └── test_agent.py   # Unit tests for the agent.
```

## Installation

Currently, the project has no external dependencies. To set up, simply clone the repository:

```bash
git clone <repository-url>
cd <repository-name>
```

*(Note: A `requirements.txt` file is included for future use and good practice. It will contain `pyyaml` once config loading is implemented.)*

## Usage

The primary way to run the agent is through the `main.py` script. This script initializes the agent, feeds it a hard-coded series of oracle updates, and prints the agent's status and final memory log.

To run the simulation:

```bash
python3 main.py
```

This will output the status of the agent after each cycle and a full dump of its memory at the end.

## Running Tests

The project uses Python's built-in `unittest` module for testing. Tests are located in the `tests/` directory.

To run the tests, execute the following command from the root of the project:

```bash
python3 -m unittest tests/test_agent.py
```

A successful run will show "OK".
