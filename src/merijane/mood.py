from __future__ import annotations

from dataclasses import dataclass
import random


@dataclass
class MoodState:
    anxiety: float
    confidence: float
    panic: float = 0.0
    recent_eval_drop: float = 0.0

    def clamp(self) -> None:
        self.anxiety = min(1.0, max(0.0, self.anxiety))
        self.confidence = min(1.0, max(0.0, self.confidence))
        self.panic = min(1.0, max(0.0, self.panic))


class MoodEngine:
    def __init__(
        self,
        base_anxiety: float,
        base_confidence: float,
        panic_cap: float,
        recovery_rate: float,
        seed: int | None = None,
    ) -> None:
        self.rng = random.Random(seed)
        self.panic_cap = panic_cap
        self.recovery_rate = recovery_rate
        self.state = MoodState(
            anxiety=min(1.0, max(0.0, base_anxiety + self.rng.uniform(-0.07, 0.07))),
            confidence=min(1.0, max(0.0, base_confidence + self.rng.uniform(-0.08, 0.08))),
        )

    def update(
        self,
        *,
        time_pressure: float,
        position_complexity: float,
        eval_drop_pawns: float,
        is_ahead: bool,
    ) -> MoodState:
        s = self.state
        s.recent_eval_drop = max(0.0, eval_drop_pawns)

        anxiety_target = (
            0.40 * time_pressure
            + 0.34 * position_complexity
            + 0.18 * min(1.0, eval_drop_pawns / 2.0)
            + (0.0 if is_ahead else 0.08)
        )
        s.anxiety = 0.72 * s.anxiety + 0.28 * anxiety_target

        panic_probability = min(
            self.panic_cap,
            max(
                0.0,
                0.02
                + 0.22 * time_pressure
                + 0.18 * position_complexity
                + 0.12 * min(1.0, eval_drop_pawns / 2.0)
                - 0.15 * s.confidence,
            ),
        )
        if self.rng.random() < panic_probability:
            s.panic = min(1.0, s.panic + self.rng.uniform(0.25, 0.55))
        else:
            s.panic *= 1.0 - self.recovery_rate

        if is_ahead:
            s.confidence = min(1.0, s.confidence + 0.025)
        elif eval_drop_pawns > 0.8:
            s.confidence = max(0.0, s.confidence - 0.08)

        s.clamp()
        return s
