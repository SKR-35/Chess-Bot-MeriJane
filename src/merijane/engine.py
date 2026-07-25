from __future__ import annotations

from pathlib import Path
import logging
import random

import chess
import chess.engine

from .mood import MoodState
from .personality import Candidate, PersonalitySelector
from .settings import EngineConfig


LOGGER = logging.getLogger(__name__)


class StockfishEngine:
    def __init__(
        self,
        executable: Path,
        config: EngineConfig,
        selector: PersonalitySelector,
        seed: int | None = None,
    ) -> None:
        self.executable = executable
        self.config = config
        self.selector = selector
        self.rng = random.Random(seed)
        self._engine: chess.engine.SimpleEngine | None = None

    def start(self) -> None:
        if not self.executable.exists():
            raise FileNotFoundError(f"Stockfish not found: {self.executable}")

        self._engine = chess.engine.SimpleEngine.popen_uci(str(self.executable))

        options: dict[str, int | bool] = {
            "Threads": self.config.threads,
            "Hash": self.config.hash_mb,
            "Skill Level": self.config.skill_level,
        }

        # Skill Level alone mostly weakens Stockfish's own final best-move
        # selection. MeriJane uses analyse(MultiPV) and chooses the move herself,
        # so the personality selector below also applies skill-aware weakening.
        #
        # UCI_LimitStrength is enabled as a second layer when the installed
        # Stockfish build supports it. The Elo mapping is intentionally broad;
        # the personality layer remains the main strength controller.
        if "UCI_LimitStrength" in self._engine.options:
            options["UCI_LimitStrength"] = self.config.skill_level < 20
        if (
            self.config.skill_level < 20
            and "UCI_Elo" in self._engine.options
        ):
            elo_option = self._engine.options["UCI_Elo"]
            minimum_elo = int(elo_option.min or 1320)
            maximum_elo = int(elo_option.max or 3190)
            fraction = max(0.0, min(1.0, self.config.skill_level / 20.0))
            options["UCI_Elo"] = round(
                minimum_elo + fraction * (maximum_elo - minimum_elo)
            )

        self._engine.configure(options)

        LOGGER.info(
            "Stockfish configured | skill=%s | multipv=%s | "
            "max_cp_loss=%s | options=%s",
            self.config.skill_level,
            self.config.multipv,
            self.config.max_cp_loss,
            options,
        )

    def close(self) -> None:
        if self._engine is not None:
            self._engine.quit()
            self._engine = None

    def _mood_adjusted_think_ms(
        self,
        *,
        speed: str,
        mood: MoodState,
    ) -> int:
        """
        Mild/moderate anxiety causes overthinking.
        High panic causes rushed, narrowed decisions.
        Confidence slightly reduces hesitation.

        The random jitter prevents every move with the same mood from taking
        exactly the same amount of time.
        """
        base_ms = self.config.move_time_ms.get(speed, 1200)

        factor = (
            1.0
            + 1.10 * mood.anxiety
            - 0.80 * mood.panic
            - 0.18 * mood.confidence
        )

        # Keep behavior playable and avoid pathological think times.
        factor = min(1.90, max(0.42, factor))
        jitter = self.rng.uniform(0.88, 1.12)

        minimum_ms = {
            "blitz": 90,
            "rapid": 180,
            "classical": 300,
        }.get(speed, 150)

        maximum_ms = {
            "blitz": 1_600,
            "rapid": 4_500,
            "classical": 8_000,
        }.get(speed, 3_000)

        return int(
            min(
                maximum_ms,
                max(minimum_ms, base_ms * factor * jitter),
            )
        )

    def choose_move(
        self,
        board: chess.Board,
        *,
        speed: str,
        mood: MoodState,
    ) -> Candidate:
        if self._engine is None:
            raise RuntimeError("Engine has not been started.")

        think_ms = self._mood_adjusted_think_ms(
            speed=speed,
            mood=mood,
        )

        weakness = max(
            0.0,
            min(1.0, (20 - self.config.skill_level) / 20.0),
        )
        effective_multipv = max(
            self.config.multipv,
            round(self.config.multipv + 6 * weakness),
        )

        analyses = self._engine.analyse(
            board,
            chess.engine.Limit(time=think_ms / 1000.0),
            multipv=effective_multipv,
        )
        if isinstance(analyses, dict):
            analyses = [analyses]
        return self.selector.choose(board, analyses, mood)
