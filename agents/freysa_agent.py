# freysa_agent.py
"""
Deterministic, hardware-agnostic agent skeleton for the freysa.ai
TEE / on-chain environment.
"""

from __future__ import annotations

import hashlib
import json
import math
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


@dataclass(slots=True, frozen=True)
class PriceMove:
    """Per-asset movement between the previous and current oracle snapshots."""

    asset: str
    previous: Optional[float]
    current: float
    change: Optional[float]
    change_pct: Optional[float]
    direction: str


@dataclass(slots=True, frozen=True)
class CycleAnalysis:
    """Deterministic analytics derived during a single reasoning cycle."""

    avg_price: Optional[float] = None
    price_moves: List[PriceMove] = field(default_factory=list)
    trend: str = "unknown"
    risk_score: int = 0
    risk_level: str = "low"
    message_signal: str = "neutral"
    alerts: List[str] = field(default_factory=list)

    def to_json(self) -> JSON:
        return asdict(self)


@dataclass(slots=True)
class SelfState:
    awareness: str = "observing"
    last_update: int = 0
    health: str = "idle"
    inputs: InputBundle = field(default_factory=InputBundle)
    cycle_count: int = 0
    analysis: CycleAnalysis = field(default_factory=CycleAnalysis)

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
    PRICE_MOVE_ALERT_PCT = 5.0
    MESSAGE_SIGNALS = {
        "urgent": {"panic", "urgent", "emergency", "crash", "exploit", "hack"},
        "positive": {"buy", "bull", "rally", "growth", "thanks"},
        "inquiry": {"status", "status?", "why", "how", "what", "?"},
    }

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
        self._previous_price_feed: Optional[Dict[str, float]] = None

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
        self._analyze_cycle(timestamp=now)
        self._reflect(timestamp=now)
        self._self_update(timestamp=now)  # decides final health
        self._remember_price_feed()
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
        self._previous_price_feed = None
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
            "analysis": self.state.analysis.to_json(),
            "memory_length": len(self.memory),
        }

    # ------------------------------------------------------------------- #
    #  Internal helpers
    # ------------------------------------------------------------------- #
    def _ingest_oracle(self, payload: JSON, *, timestamp: int) -> None:
        """Validate and store incoming oracle data deterministically."""
        allowed = {f.name for f in fields(InputBundle)}
        filtered = {k: payload[k] for k in payload if k in allowed}
        ignored = sorted(k for k in payload if k not in allowed)
        if ignored:
            self._log("warn", {"reason": "ignored oracle keys", "keys": ignored}, timestamp=timestamp)

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
            price_feed: Dict[str, float] = {}
            for asset, value in pf_raw.items():
                try:
                    price = float(value)
                except (ValueError, TypeError):
                    self._log(
                        "warn",
                        {"reason": "non-numeric price value", "asset": str(asset)},
                        timestamp=timestamp,
                    )
                    continue
                if not math.isfinite(price) or price < 0:
                    self._log(
                        "warn",
                        {"reason": "invalid price value", "asset": str(asset)},
                        timestamp=timestamp,
                    )
                    continue
                price_feed[str(asset).upper()] = price
            return price_feed or None
        else:
            if pf_raw is not None:
                self._log("warn", {"reason": "price_feed not dict"}, timestamp=timestamp)
        return None

    def _validate_messages(self, msgs_raw: Any, timestamp: int) -> Optional[List[str]]:
        if isinstance(msgs_raw, list) and all(isinstance(m, str) for m in msgs_raw):
            cleaned = [message.strip() for message in msgs_raw if message.strip()]
            return cleaned or None
        else:
            if msgs_raw is not None:
                self._log("warn", {"reason": "messages not list[str]"}, timestamp=timestamp)
        return None

    def _analyze_cycle(self, *, timestamp: int) -> None:
        """Compute deterministic market movement, message signal, and risk level."""
        price_feed = self.state.inputs.price_feed or {}
        messages = self.state.inputs.messages or []
        avg_price = round(sum(price_feed.values()) / len(price_feed), 2) if price_feed else None
        price_moves = self._price_moves(price_feed)
        message_signal = self._message_signal(messages)
        risk_score, risk_level, alerts = self._risk_assessment(
            price_feed=price_feed,
            price_moves=price_moves,
            message_signal=message_signal,
        )
        trend = self._trend(price_moves)
        self.state.analysis = CycleAnalysis(
            avg_price=avg_price,
            price_moves=price_moves,
            trend=trend,
            risk_score=risk_score,
            risk_level=risk_level,
            message_signal=message_signal,
            alerts=alerts,
        )
        self._log("analysis", self.state.analysis.to_json(), timestamp=timestamp)

    def _price_moves(self, price_feed: Dict[str, float]) -> List[PriceMove]:
        moves: List[PriceMove] = []
        for asset in sorted(price_feed):
            current = price_feed[asset]
            previous = (self._previous_price_feed or {}).get(asset)
            change = current - previous if previous is not None else None
            change_pct = None
            if previous not in (None, 0):
                change_pct = round((change or 0.0) / previous * 100, 4)
            direction = self._direction(change_pct)
            moves.append(
                PriceMove(
                    asset=asset,
                    previous=previous,
                    current=current,
                    change=round(change, 8) if change is not None else None,
                    change_pct=change_pct,
                    direction=direction,
                )
            )
        return moves

    def _message_signal(self, messages: List[str]) -> str:
        tokens = {token.strip(".,!;:()[]{}").lower() for message in messages for token in message.split()}
        compact_messages = " ".join(messages).lower()
        if tokens & self.MESSAGE_SIGNALS["urgent"]:
            return "urgent"
        if tokens & self.MESSAGE_SIGNALS["positive"]:
            return "positive"
        if tokens & self.MESSAGE_SIGNALS["inquiry"] or "?" in compact_messages:
            return "inquiry"
        return "neutral"

    def _risk_assessment(
        self,
        *,
        price_feed: Dict[str, float],
        price_moves: List[PriceMove],
        message_signal: str,
    ) -> tuple[int, str, List[str]]:
        score = 0
        alerts: List[str] = []
        if self.limiter.spike(price_feed):
            score += 60
            alerts.append("limiter threshold exceeded")

        largest_abs_move = 0.0
        for move in price_moves:
            if move.change_pct is None:
                continue
            largest_abs_move = max(largest_abs_move, abs(move.change_pct))
            if abs(move.change_pct) >= self.PRICE_MOVE_ALERT_PCT:
                alerts.append(f"{move.asset} moved {move.change_pct}%")
        score += min(30, int(largest_abs_move * 2))

        if message_signal == "urgent":
            score += 15
            alerts.append("urgent operator message detected")
        elif message_signal == "inquiry":
            score += 3

        if not price_feed:
            score += 5
            alerts.append("missing price feed")

        score = min(score, 100)
        if score >= 80:
            level = "critical"
        elif score >= 55:
            level = "elevated"
        elif score >= 25:
            level = "moderate"
        else:
            level = "low"
        return score, level, alerts

    def _trend(self, price_moves: List[PriceMove]) -> str:
        known = [move for move in price_moves if move.change_pct is not None]
        if not known:
            return "unknown"
        positive = sum(1 for move in known if move.change_pct and move.change_pct > 0)
        negative = sum(1 for move in known if move.change_pct and move.change_pct < 0)
        if positive > negative:
            return "rising"
        if negative > positive:
            return "falling"
        return "mixed"

    def _direction(self, change_pct: Optional[float]) -> str:
        if change_pct is None:
            return "new"
        if change_pct > 0:
            return "up"
        if change_pct < 0:
            return "down"
        return "flat"

    def _reflect(self, *, timestamp: int) -> None:
        """Lightweight metacognition placeholder."""
        last_event = self.memory[-1].event if self.memory else "none"
        thought = f"reflecting on {last_event}; risk={self.state.analysis.risk_level}"
        self.state.awareness = "reflecting"
        self._log("reflect", {"thought": thought}, timestamp=timestamp)
        self.state.awareness = "observing"

    def _self_update(self, *, timestamp: int) -> None:
        """Adjust internal health/state based on limiter and analysis policies."""
        pf = self.state.inputs.price_feed or {}
        high_activity = self.limiter.spike(pf)
        risky_activity = self.state.analysis.risk_level in {"elevated", "critical"}

        if high_activity or risky_activity:
            action = f"monitoring {self.state.analysis.risk_level} activity"
            self.state.health = "active"
        else:
            action = "normal range"
            self.state.health = "idle"
        self._log("self_update", {"action": action}, timestamp=timestamp)

    def _remember_price_feed(self) -> None:
        if self.state.inputs.price_feed:
            self._previous_price_feed = dict(self.state.inputs.price_feed)

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
