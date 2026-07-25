from __future__ import annotations

from dataclasses import dataclass
import math
import random

import chess
import chess.engine

from .mood import MoodState
from .openings import repertoire_bonus
from .settings import EngineConfig, PersonalityConfig


@dataclass(frozen=True)
class Candidate:
    move: chess.Move
    cp: int
    personality_score: float
    pv: list[chess.Move]


def _material_balance(board: chess.Board) -> int:
    values = {
        chess.PAWN: 100,
        chess.KNIGHT: 320,
        chess.BISHOP: 330,
        chess.ROOK: 500,
        chess.QUEEN: 900,
    }
    score = 0
    for piece_type, value in values.items():
        score += len(board.pieces(piece_type, chess.WHITE)) * value
        score -= len(board.pieces(piece_type, chess.BLACK)) * value
    return score if board.turn == chess.WHITE else -score


def _position_complexity(board: chess.Board) -> float:
    legal = board.legal_moves.count()
    captures = sum(1 for move in board.legal_moves if board.is_capture(move))
    checks = sum(1 for move in board.legal_moves if board.gives_check(move))
    queens = len(board.pieces(chess.QUEEN, chess.WHITE)) + len(
        board.pieces(chess.QUEEN, chess.BLACK)
    )
    raw = 0.018 * legal + 0.055 * captures + 0.07 * checks + 0.08 * queens
    return min(1.0, raw)


def _move_features(board: chess.Board, move: chess.Move) -> dict[str, float]:
    child = board.copy(stack=False)
    is_capture = board.is_capture(move)
    gives_check = board.gives_check(move)
    moved_piece = board.piece_at(move.from_square)
    child.push(move)

    king_safety = 0.0
    own_king = child.king(not child.turn)
    if own_king is not None:
        attackers = len(child.attackers(child.turn, own_king))
        king_safety = -0.18 * attackers

    central = 1.0 if chess.square_file(move.to_square) in (2, 3, 4, 5) else 0.0
    develops_minor = (
        moved_piece is not None
        and moved_piece.piece_type in (chess.KNIGHT, chess.BISHOP)
        and chess.square_rank(move.from_square) in (0, 7)
    )
    exchange = 1.0 if is_capture else 0.0
    forcing = float(gives_check) + 0.55 * float(is_capture)
    complexity = _position_complexity(child)

    return {
        "king_safety": king_safety,
        "central": central,
        "development": float(develops_minor),
        "exchange": exchange,
        "forcing": forcing,
        "complexity": complexity,
    }


class PersonalitySelector:
    def __init__(
        self,
        personality: PersonalityConfig,
        engine: EngineConfig,
        seed: int | None = None,
    ) -> None:
        self.cfg = personality
        self.engine_cfg = engine
        self.rng = random.Random(seed)

    def choose(
        self,
        board: chess.Board,
        analyses: list[dict],
        mood: MoodState,
    ) -> Candidate:
        candidates: list[Candidate] = []
        best_cp: int | None = None
        ahead = _material_balance(board) > 80

        for info in analyses:
            pv = info.get("pv") or []
            if not pv:
                continue

            move = pv[0]
            score = info["score"].pov(board.turn).score(
                mate_score=self.engine_cfg.mate_score
            )
            if score is None:
                continue
            cp = int(score)
            best_cp = cp if best_cp is None else max(best_cp, cp)

            features = _move_features(board, move)
            personality_score = cp / 100.0

            personality_score += (
                self.cfg.opening_familiarity_bonus
                * repertoire_bonus(board, move)
                * self.cfg.italian_preference
            )
            personality_score += self.cfg.safety_bonus * features["king_safety"]
            personality_score += 0.05 * features["central"]
            personality_score += 0.07 * features["development"]

            risk_tolerance = self.cfg.base_risk_tolerance
            risk_tolerance += 0.22 * mood.confidence
            risk_tolerance -= 0.34 * mood.anxiety
            risk_tolerance -= 0.40 * mood.panic

            personality_score += (
                self.cfg.creativity
                * risk_tolerance
                * 0.10
                * features["forcing"]
            )
            personality_score -= (
                self.cfg.complexity_penalty
                * (mood.anxiety + 1.3 * mood.panic)
                * features["complexity"]
            )

            if ahead:
                personality_score += (
                    self.cfg.exchange_bonus_when_ahead
                    * (0.6 + mood.anxiety)
                    * features["exchange"]
                )

            candidates.append(
                Candidate(
                    move=move,
                    cp=cp,
                    personality_score=personality_score,
                    pv=pv,
                )
            )

        if not candidates or best_cp is None:
            raise RuntimeError("Stockfish returned no playable candidate.")

        skill = max(0, min(20, self.engine_cfg.skill_level))
        weakness = (20 - skill) / 20.0

        # MeriJane does not use Stockfish's final "bestmove"; she receives a
        # MultiPV analysis and chooses a move herself. Therefore Stockfish's
        # Skill Level option alone has little effect. Apply strength control
        # directly to MeriJane's candidate selection.
        effective_cp_loss = round(
            self.engine_cfg.max_cp_loss + 525 * weakness
        )
        viable = [
            candidate
            for candidate in candidates
            if best_cp - candidate.cp <= effective_cp_loss
        ] or [max(candidates, key=lambda candidate: candidate.cp)]

        # At low skill, occasionally prefer the lower half of the candidate
        # pool. This creates human-like inaccuracies without selecting illegal
        # moves or completely random moves.
        blunder_probability = 0.34 * weakness
        if len(viable) >= 4 and self.rng.random() < blunder_probability:
            ranked = sorted(viable, key=lambda candidate: candidate.cp, reverse=True)
            viable = ranked[len(ranked) // 2 :]

        temperature = max(
            0.04,
            self.cfg.randomness_temperature + 0.85 * weakness,
        )
        noise_scale = 1.15 * weakness

        adjusted_scores = [
            candidate.personality_score
            + self.rng.gauss(0.0, noise_scale)
            for candidate in viable
        ]
        peak = max(adjusted_scores)
        weights = [
            math.exp((score - peak) / temperature)
            for score in adjusted_scores
        ]
        return self.rng.choices(viable, weights=weights, k=1)[0]


def estimate_complexity(board: chess.Board) -> float:
    return _position_complexity(board)
