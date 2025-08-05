# freysa_agent.py
"""
Deterministic, hardware-agnostic agent skeleton for the freysa.ai
TEE / on-chain environment.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, List, Optional, Protocol, TypeAlias, final

JSON: TypeAlias = Dict[str, Any]

# --------------------------------------------------------------------------- #
#  Protocols / small pluggable helpers
# --------------------------------------------------------------------------- #
class Clock(Protocol):
    """Return an integer UNIX epoch second – must be deterministic inside TEE."""
    def now(self) -> int: ...


class Limiter(Protocol):
    """Return True if the agent should act given current inputs."""
    def spike(self, price_feed: Dict[str, float]) -> bool: ...


# --------------------------------------------------------------------------- #
#  Data classes
# --------------------------------------------------------------------------- #
@dataclass(slots=True, frozen=True)
class InputBundle:
    price_feed: Optional[Dict[str, float]] = None
    messages: Optional[List[str]] = None

    def to_json(self) -> JSON:
        return asdict(self)


@dataclass(slots=True)
class SelfState:
    awareness: str = "observing"
    last_update: int = 0
    health: str = "idle"
    inputs: InputBundle = field(default_factory=InputBundle)
    cycle_count: int = 0

    def snapshot(self) -> JSON:
        return asdict(self)


@dataclass(slots=True)
class LogEntry:
    timestamp: int
    event: str
    data: Any
    state_snapshot: JSON


# --------------------------------------------------------------------------- #
#  Default deterministic helpers
# --------------------------------------------------------------------------- #
class StaticClock:
    """A trivial deterministic clock – must be injected by caller per cycle."""
    def __init__(self, initial: int = 0) -> None:
        self._t = initial

    def tick(self) -> int:
        self._t += 1
        return self._t

    def now(self) -> int:  # type: ignore[override]
        return self._t


class SimpleLimiter:
    """Reference implementation of Limiter with hard-coded thresholds."""
    BTC_SPIKE = 690_000_000_000
    ETH_SPIKE = 3_140_000_000
    AVG_SPIKE = 6_290_000_000.0

    def spike(self, price_feed: Dict[str, float]) -> bool:  # type: ignore[override]
        if not price_feed:
            return False
        avg_price = sum(price_feed.values()) / len(price_feed)
        btc = price_feed.get("BTC", 0) > self.BTC_SPIKE
        eth = price_feed.get("ETH", 0) > self.ETH_SPIKE
        return avg_price > self.AVG_SPIKE or btc or eth


# --------------------------------------------------------------------------- #
#  Main Agent
# --------------------------------------------------------------------------- #
@final
class FreysaSentientAI:
    MAX_MEMORY: Optional[int] = 2_048  # smaller default for on-chain cost

    def __init__(
        self,
        name: str = "ChainAI",
        version: str = "1.1",
        *,
        clock: Optional[Clock] = None,
        limiter: Optional[Limiter] = None,
    ) -> None:
        self.name = name
        self.version = version
        self.id = hashlib.sha256(f"{name}:{version}".encode()).hexdigest()

        self.clock = clock or StaticClock()
        self.limiter = limiter or SimpleLimiter()

        self.state = SelfState()
        self.memory: List[LogEntry] = []

        # Genesis event always at t=0
        self._log("boot", {"agent_id": self.id, "version": self.version}, timestamp=0)

    # ------------------------------------------------------------------- #
    #  Public API
    # ------------------------------------------------------------------- #
    def run_cycle(self, oracle_payload: JSON, *, current_time: Optional[int] = None) -> None:
        """One deterministic reasoning cycle."""
        now = current_time if current_time is not None else self.clock.now()

        self.state.last_update = now
        self.state.cycle_count += 1
        self.state.health = "active"

        if not isinstance(oracle_payload, dict):
            self._log("error", {"reason": "oracle payload is not a dict"}, timestamp=now)
            self.state.health = "idle"
            return

        self._ingest_oracle(oracle_payload, timestamp=now)
        self._reflect(timestamp=now)
        self._self_update(timestamp=now)  # decides final health

    def export_memory(self, pretty: bool = False) -> str:
        dump = [asdict(e) for e in self.memory]
        return json.dumps(
            dump,
            indent=2 if pretty else None,
            separators=(",", ": " if pretty else ":"),
        )

    def reset_memory(self) -> None:
        self.memory.clear()
        self.state = SelfState()
        self._log("reset", {"agent_id": self.id}, timestamp=0)

    def get_status(self) -> JSON:
        pf = self.state.inputs.price_feed or {}
        messages = self.state.inputs.messages or []
        avg_price = round(sum(pf.values()) / len(pf), 2) if pf else None
        return {
            "name": self.name,
            "version": self.version,
            "id": self.id,
            "state": self.state.snapshot(),
            "avg_price": avg_price,
            "last_message": messages[-1] if messages else None,
            "memory_length": len(self.memory),
        }

    # ------------------------------------------------------------------- #
    #  Internal helpers
    # ------------------------------------------------------------------- #
    def _ingest_oracle(self, payload: JSON, *, timestamp: int) -> None:
        """Validate and store incoming oracle data deterministically."""
        allowed = {f.name for f in fields(InputBundle)}
        filtered = {k: payload[k] for k in payload if k in allowed}

        # -- price feed -------------------------------------------------- #
        pf_raw = filtered.get("price_feed")
        price_feed: Optional[Dict[str, float]] = self._validate_price_feed(pf_raw, timestamp)

        # -- messages ---------------------------------------------------- #
        msgs_raw = filtered.get("messages")
        messages: Optional[List[str]] = self._validate_messages(msgs_raw, timestamp)

        self.state.inputs = InputBundle(price_feed=price_feed, messages=messages)
        self._log("oracle_input", self.state.inputs.to_json(), timestamp=timestamp)

    def _validate_price_feed(self, pf_raw: Any, timestamp: int) -> Optional[Dict[str, float]]:
        if isinstance(pf_raw, dict):
            try:
                return {k: float(v) for k, v in pf_raw.items()}
            except (ValueError, TypeError):
                self._log("warn", {"reason": "non-numeric price values"}, timestamp=timestamp)
        else:
            if pf_raw is not None:
                self._log("warn", {"reason": "price_feed not dict"}, timestamp=timestamp)
        return None

    def _validate_messages(self, msgs_raw: Any, timestamp: int) -> Optional[List[str]]:
        if isinstance(msgs_raw, list) and all(isinstance(m, str) for m in msgs_raw):
            return msgs_raw
        else:
            if msgs_raw is not None:
                self._log("warn", {"reason": "messages not list[str]"}, timestamp=timestamp)
        return None

    def _reflect(self, *, timestamp: int) -> None:
        """Lightweight metacognition placeholder."""
        last_event = self.memory[-1].event if self.memory else "none"
        thought = f"reflecting on {last_event}"
        self.state.awareness = "reflecting"
        self._log("reflect", {"thought": thought}, timestamp=timestamp)
        self.state.awareness = "observing"

    def _self_update(self, *, timestamp: int) -> None:
        """Adjust internal health/state based on limiter policy."""
        pf = self.state.inputs.price_feed or {}
        high_activity = self.limiter.spike(pf)

        action = "high market activity" if high_activity else "normal range"
        self.state.health = "active" if high_activity else "idle"
        self._log("self_update", {"action": action}, timestamp=timestamp)

    # ------------------------------------------------------------------- #
    #  Logging
    # ------------------------------------------------------------------- #
    def _log(self, event: str, data: Any, *, timestamp: Optional[int] = None) -> None:
        ts = timestamp if timestamp is not None else self.state.last_update

        entry = LogEntry(
            timestamp=ts,
            event=event,
            data=data,
            state_snapshot=self.state.snapshot(),
        )

        # Capacity-bounded ring buffer
        if self.MAX_MEMORY and len(self.memory) >= self.MAX_MEMORY:
            self.memory[0] = LogEntry(
                timestamp=ts,
                event="memory_cap_exceeded",
                data={"max": self.MAX_MEMORY},
                state_snapshot=self.state.snapshot(),
            )
            self.memory = self.memory[1:]  # rotate left, length unchanged
        self.memory.append(entry)


# This space is intentionally left blank.
