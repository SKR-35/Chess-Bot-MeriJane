from pathlib import Path

import chess

from merijane.engine import StockfishEngine
from merijane.mood import MoodEngine
from merijane.personality import PersonalitySelector
from merijane.settings import load_config


def main() -> None:
    config = load_config(Path("config/merijane.yml"))

    selector = PersonalitySelector(
        personality=config.personality,
        engine=config.engine,
        seed=42,
    )

    engine = StockfishEngine(
        executable=Path(
            "engine/stockfish-windows-x86-64-avx2.exe"
        ),
        config=config.engine,
        selector=selector,
    )

    mood = MoodEngine(
        base_anxiety=config.personality.base_anxiety,
        base_confidence=config.personality.base_confidence,
        panic_cap=config.personality.panic_cap,
        recovery_rate=config.personality.recovery_rate,
        seed=42,
    )

    board = chess.Board()

    try:
        engine.start()

        for ply in range(12):
            mood_state = mood.update(
                time_pressure=0.05,
                position_complexity=0.30,
                eval_drop_pawns=0.0,
                is_ahead=False,
            )

            candidate = engine.choose_move(
                board,
                speed="rapid",
                mood=mood_state,
            )

            print(
                f"{ply + 1:02d}. "
                f"{board.san(candidate.move):8s} "
                f"eval={candidate.cp / 100:+.2f} "
                f"anxiety={mood_state.anxiety:.2f} "
                f"confidence={mood_state.confidence:.2f}"
            )

            board.push(candidate.move)

        print("\nFinal position:")
        print(board)
        print("\nFEN:")
        print(board.fen())

    finally:
        engine.close()


if __name__ == "__main__":
    main()