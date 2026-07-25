from __future__ import annotations

import chess


# Small transparent repertoire layer. Stockfish remains the evaluator.
ITALIAN_PREFIXES = {
    ("e2e4",): 0.70,
    ("e2e4", "e7e5", "g1f3"): 0.90,
    ("e2e4", "e7e5", "g1f3", "b8c6", "f1c4"): 1.00,
}

WHITE_PREFERENCES = {
    "e2e4": 0.50,
    "g1f3": 0.12,
    "c2c4": 0.18,
    "d2d4": 0.20,
}

BLACK_VS_E4 = {
    "e7e5": 0.42,
    "c7c6": 0.32,
    "e7e6": 0.16,
    "c7c5": 0.10,
}

BLACK_VS_D4 = {
    "d7d5": 0.55,
    "g8f6": 0.45,
}


def repertoire_bonus(board: chess.Board, move: chess.Move) -> float:
    history = tuple(m.uci() for m in board.move_stack)
    candidate = move.uci()

    if not history and board.turn == chess.WHITE:
        return WHITE_PREFERENCES.get(candidate, 0.0)

    if history == ("e2e4",) and board.turn == chess.BLACK:
        return BLACK_VS_E4.get(candidate, 0.0)

    if history == ("d2d4",) and board.turn == chess.BLACK:
        return BLACK_VS_D4.get(candidate, 0.0)

    prospective = history + (candidate,)
    return ITALIAN_PREFIXES.get(prospective, 0.0)
