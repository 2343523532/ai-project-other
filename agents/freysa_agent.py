# freysa_agent.py
"""
Deterministic, hardware-agnostic agent core for repeatable Freysa simulations.

The module intentionally keeps all reasoning local and auditable: every cycle
normalizes oracle inputs, derives a compact market insight, updates state through
an injected limiter policy, and records the path in a bounded memory log.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, List, Optional, Protocol, TypeAlias, final

JSON: TypeAlias = Dict[str, Any]

# --------------------------------------------------------------------------- #
#  Protocols / small pluggable helpers
# --------------------------------------------------------------------------- #
class Clock(Protocol):
    """Return an integer UNIX epoch second; deterministic clocks are preferred."""

    def now(self) -> int: ...


class Limiter(Protocol):
    """Return True if the agent should move from idle to active."""

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


@dataclass(slots=True, frozen=True)
class MarketInsight:
    """Deterministic summary of the most recent oracle price feed."""

    asset_count: int = 0
    average_price: Optional[float] = None
    min_asset: Optional[str] = None
    min_price: Optional[float] = None
    max_asset: Optional[str] = None
    max_price: Optional[float] = None
    spread: Optional[float] = None
    trend: str = "unknown"
    risk_level: str = "unknown"
    spike_detected: bool = False

    def to_json(self) -> JSON:
        return asdict(self)


@dataclass(slots=True)
class SelfState:
    awareness: str = "observing"
    last_update: int = 0
    health: str = "idle"
    inputs: InputBundle = field(default_factory=InputBundle)
    cycle_count: int = 0
    last_insight: MarketInsight = field(default_factory=MarketInsight)

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
    """A trivial deterministic clock that callers may advance per cycle."""

    def __init__(self, initial: int = 0) -> None:
        self._t = initial

    def tick(self) -> int:
        self._t += 1
        return self._t

    def now(self) -> int:  # type: ignore[override]
        return self._t


class SimpleLimiter:
    """Reference limiter with deterministic hard-coded spike thresholds."""

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

    def explain(self, price_feed: Dict[str, float]) -> JSON:
        """Expose threshold comparisons for audit trails and status snapshots."""
        if not price_feed:
            return {
                "spike": False,
                "average_price": None,
                "triggered_thresholds": [],
            }

        avg_price = sum(price_feed.values()) / len(price_feed)
        triggered = []
        if avg_price > self.AVG_SPIKE:
            triggered.append("AVG_SPIKE")
        if price_feed.get("BTC", 0) > self.BTC_SPIKE:
            triggered.append("BTC_SPIKE")
        if price_feed.get("ETH", 0) > self.ETH_SPIKE:
            triggered.append("ETH_SPIKE")

        return {
            "spike": bool(triggered),
            "average_price": round(avg_price, 2),
            "triggered_thresholds": triggered,
        }


# --------------------------------------------------------------------------- #
#  Main Agent
# --------------------------------------------------------------------------- #
@final
class FreysaSentientAI:
    MAX_MEMORY: Optional[int] = 2_048  # smaller default for on-chain cost
    MAX_MESSAGE_LENGTH = 512

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
        self._previous_avg_price: Optional[float] = None

        # Genesis event always at t=0
        self._log("boot", {"agent_id": self.id, "version": self.version}, timestamp=0)

    # ------------------------------------------------------------------- #
    #  Public API
    # ------------------------------------------------------------------- #
    def run_cycle(
        self, oracle_payload: JSON, *, current_time: Optional[int] = None
    ) -> JSON:
        """Execute one deterministic reasoning cycle and return the new status."""
        now = current_time if current_time is not None else self.clock.now()

        self.state.last_update = now
        self.state.cycle_count += 1
        self.state.health = "active"

        if not isinstance(oracle_payload, dict):
            self._log("error", {"reason": "oracle payload is not a dict"}, timestamp=now)
            self.state.health = "idle"
            return self.get_status()

        self._ingest_oracle(oracle_payload, timestamp=now)
        self._analyze_market(timestamp=now)
        self._reflect(timestamp=now)
        self._self_update(timestamp=now)  # decides final health
        return self.get_status()

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
        self._previous_avg_price = None
        self._log("reset", {"agent_id": self.id}, timestamp=0)

    def get_status(self) -> JSON:
        messages = self.state.inputs.messages or []
        insight = self.state.last_insight
        return {
            "name": self.name,
            "version": self.version,
            "id": self.id,
            "state": self.state.snapshot(),
            "avg_price": insight.average_price,
            "last_message": messages[-1] if messages else None,
            "market_insight": insight.to_json(),
            "memory_length": len(self.memory),
            "event_counts": self.event_counts(),
        }

    def event_counts(self) -> Dict[str, int]:
        """Return deterministic counts of logged event types."""
        return dict(sorted(Counter(entry.event for entry in self.memory).items()))

    def recent_memory(self, limit: int = 5, *, event: Optional[str] = None) -> List[JSON]:
        """Return the most recent memory entries, optionally filtered by event."""
        if limit < 1:
            return []
        entries = [entry for entry in self.memory if event is None or entry.event == event]
        return [asdict(entry) for entry in entries[-limit:]]

    # ------------------------------------------------------------------- #
    #  Internal helpers
    # ------------------------------------------------------------------- #
    def _ingest_oracle(self, payload: JSON, *, timestamp: int) -> None:
        """Validate and store incoming oracle data deterministically."""
        allowed = {f.name for f in fields(InputBundle)}
        filtered = {k: payload[k] for k in payload if k in allowed}
        ignored = sorted(k for k in payload if k not in allowed)
        if ignored:
            self._log("warn", {"reason": "ignored oracle fields", "fields": ignored}, timestamp=timestamp)

        price_feed = self._validate_price_feed(filtered.get("price_feed"), timestamp)
        messages = self._validate_messages(filtered.get("messages"), timestamp)

        self.state.inputs = InputBundle(price_feed=price_feed, messages=messages)
        self._log("oracle_input", self.state.inputs.to_json(), timestamp=timestamp)

    def _validate_price_feed(self, pf_raw: Any, timestamp: int) -> Optional[Dict[str, float]]:
        if pf_raw is None:
            return None
        if not isinstance(pf_raw, dict):
            self._log("warn", {"reason": "price_feed not dict"}, timestamp=timestamp)
            return None

        normalized: Dict[str, float] = {}
        rejected: List[str] = []
        for asset, value in pf_raw.items():
            symbol = str(asset).strip().upper()
            try:
                price = float(value)
            except (ValueError, TypeError):
                rejected.append(str(asset))
                continue
            if not symbol or not math.isfinite(price) or price < 0:
                rejected.append(str(asset))
                continue
            normalized[symbol] = price

        if rejected:
            self._log(
                "warn",
                {"reason": "invalid price values", "assets": sorted(rejected)},
                timestamp=timestamp,
            )
        return normalized or None

    def _validate_messages(self, msgs_raw: Any, timestamp: int) -> Optional[List[str]]:
        if msgs_raw is None:
            return None
        if not isinstance(msgs_raw, list):
            self._log("warn", {"reason": "messages not list[str]"}, timestamp=timestamp)
            return None

        messages: List[str] = []
        rejected = 0
        truncated = 0
        for raw in msgs_raw:
            if not isinstance(raw, str):
                rejected += 1
                continue
            message = raw.strip()
            if not message:
                rejected += 1
                continue
            if len(message) > self.MAX_MESSAGE_LENGTH:
                message = message[: self.MAX_MESSAGE_LENGTH]
                truncated += 1
            messages.append(message)

        if rejected or truncated:
            self._log(
                "warn",
                {
                    "reason": "message normalization",
                    "rejected": rejected,
                    "truncated": truncated,
                },
                timestamp=timestamp,
            )
        return messages or None

    def _analyze_market(self, *, timestamp: int) -> None:
        """Build a compact, deterministic insight from the normalized feed."""
        pf = self.state.inputs.price_feed or {}
        if not pf:
            self.state.last_insight = MarketInsight()
            self._log("market_analysis", self.state.last_insight.to_json(), timestamp=timestamp)
            return

        sorted_prices = sorted(pf.items())
        avg_price = round(sum(price for _, price in sorted_prices) / len(sorted_prices), 2)
        min_asset, min_price = min(sorted_prices, key=lambda item: (item[1], item[0]))
        max_asset, max_price = max(sorted_prices, key=lambda item: (item[1], item[0]))
        spike_detected = self.limiter.spike(pf)
        trend = self._trend(avg_price)
        risk_level = self._risk_level(spike_detected, trend)

        self.state.last_insight = MarketInsight(
            asset_count=len(sorted_prices),
            average_price=avg_price,
            min_asset=min_asset,
            min_price=round(min_price, 2),
            max_asset=max_asset,
            max_price=round(max_price, 2),
            spread=round(max_price - min_price, 2),
            trend=trend,
            risk_level=risk_level,
            spike_detected=spike_detected,
        )
        self._previous_avg_price = avg_price
        self._log("market_analysis", self.state.last_insight.to_json(), timestamp=timestamp)

    def _trend(self, avg_price: float) -> str:
        if self._previous_avg_price is None:
            return "baseline"
        if avg_price > self._previous_avg_price:
            return "rising"
        if avg_price < self._previous_avg_price:
            return "falling"
        return "flat"

    @staticmethod
    def _risk_level(spike_detected: bool, trend: str) -> str:
        if spike_detected and trend == "rising":
            return "critical"
        if spike_detected:
            return "elevated"
        if trend == "rising":
            return "watch"
        return "normal"

    def _reflect(self, *, timestamp: int) -> None:
        """Lightweight metacognition placeholder with concrete recent context."""
        last_event = self.memory[-1].event if self.memory else "none"
        insight = self.state.last_insight
        thought = f"reflecting on {last_event}; market risk is {insight.risk_level}"
        self.state.awareness = "reflecting"
        self._log("reflect", {"thought": thought}, timestamp=timestamp)
        self.state.awareness = "observing"

    def _self_update(self, *, timestamp: int) -> None:
        """Adjust internal health/state based on limiter policy."""
        insight = self.state.last_insight
        high_activity = insight.spike_detected

        action = "high market activity" if high_activity else "normal range"
        self.state.health = "active" if high_activity else "idle"
        self._log(
            "self_update",
            {"action": action, "risk_level": insight.risk_level, "trend": insight.trend},
            timestamp=timestamp,
        )

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


# --------------------------------------------------------------------------- #
#  Deterministic test harness
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    print("── freysa_agent deterministic demo ──")
    agent = FreysaSentientAI(name="AllPurposeAI", version="3.4")

    oracle_updates = [
        {"price_feed": {"BTC": 687_285_012_000.0, "ETH": 3_125_500_000.0}, "messages": ["hi"]},
        {"price_feed": {"BTC": 696_291_000_000.0, "ETH": 3_130_000_000.0}, "messages": ["status?"]},
        {"price_feed": {"BTC": 686_300_540_000.0, "ETH": 3_152_200_000.0}, "messages": ["thanks"]},
    ]

    deterministic_time = 1_725_000_000
    for step, update in enumerate(oracle_updates):
        now = deterministic_time + step
        print(f"\n--- CYCLE {step + 1} @ t={now} ---")
        print(json.dumps(update, indent=2))
        agent.run_cycle(update, current_time=now)
        print("Status:", json.dumps(agent.get_status(), indent=2))

    print("\n==== FULL MEMORY LOG ====")
    print(agent.export_memory(pretty=True))
