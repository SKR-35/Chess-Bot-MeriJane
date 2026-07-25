from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import chess
import chess.engine
import chess.pgn

from merijane.engine import StockfishEngine
from merijane.mood import MoodEngine, MoodState
from merijane.personality import PersonalitySelector, estimate_complexity
from merijane.settings import load_config
from merijane.telemetry import save_csv_rows, save_json


DEFAULT_ENGINE_PATH = Path("engine/stockfish-windows-x86-64-avx2.exe")
DEFAULT_CONFIG_PATH = Path("config/merijane.yml")
DEFAULT_OUTPUT_DIR = Path("data/arena")

ArenaMode = Literal["merijane-vs-stockfish", "merijane-vs-merijane"]


@dataclass
class MoveMetric:
    game: int
    ply: int
    move_number: int
    color: str
    actor: str
    san: str
    uci: str
    elapsed_ms: int
    remaining_clock_ms: int
    eval_cp: int | None
    anxiety: float | None
    confidence: float | None
    panic: float | None


@dataclass
class GameMetric:
    game: int
    mode: str
    white: str
    black: str
    result: str
    termination: str
    plies: int
    full_moves: int
    opening: str
    italian: bool
    meri_white: bool | None
    meri_result: str | None
    avg_merijane_time_ms: float
    avg_stockfish_time_ms: float | None
    avg_anxiety: float
    max_anxiety: float
    avg_confidence: float
    max_panic: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MeriJane local arena, benchmark, and analytics."
    )
    parser.add_argument(
        "--menu",
        action="store_true",
        help="Open the interactive terminal menu.",
    )
    parser.add_argument(
        "--mode",
        choices=("merijane-vs-stockfish", "merijane-vs-merijane"),
        default="merijane-vs-stockfish",
    )
    parser.add_argument("--games", type=int, default=1)
    parser.add_argument(
        "--speed",
        choices=("blitz", "rapid", "classical"),
        default="rapid",
    )
    parser.add_argument(
        "--baseline-skill",
        type=int,
        default=15,
        help="Plain Stockfish Skill Level (0-20); used only in vs-stockfish mode.",
    )
    parser.add_argument(
        "--baseline-time-ms",
        type=int,
        default=None,
        help="Override plain Stockfish thinking time per move.",
    )
    parser.add_argument(
        "--max-plies",
        type=int,
        default=240,
        help="Safety limit; 240 plies = 120 full moves.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--engine-path", type=Path, default=DEFAULT_ENGINE_PATH)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def initial_clock_ms(speed: str) -> int:
    return {
        "blitz": 180_000,
        "rapid": 600_000,
        "classical": 1_800_000,
    }[speed]


def clock_pressure(remaining_ms: int, initial_ms: int) -> float:
    if initial_ms <= 0:
        return 0.0
    ratio = remaining_ms / initial_ms
    if ratio >= 0.35:
        return 0.0
    return min(1.0, (0.35 - ratio) / 0.35)


def material_balance_for_side(board: chess.Board, color: chess.Color) -> int:
    values = {
        chess.PAWN: 100,
        chess.KNIGHT: 320,
        chess.BISHOP: 330,
        chess.ROOK: 500,
        chess.QUEEN: 900,
    }
    score = 0
    for piece_type, value in values.items():
        score += len(board.pieces(piece_type, color)) * value
        score -= len(board.pieces(piece_type, not color)) * value
    return score


def build_merijane(engine_path: Path, config, seed: int) -> StockfishEngine:
    selector = PersonalitySelector(
        personality=config.personality,
        engine=config.engine,
        seed=seed,
    )
    engine = StockfishEngine(
        executable=engine_path,
        config=config.engine,
        selector=selector,
    )
    engine.start()
    return engine


def build_mood(config, seed: int) -> MoodEngine:
    return MoodEngine(
        base_anxiety=config.personality.base_anxiety,
        base_confidence=config.personality.base_confidence,
        panic_cap=config.personality.panic_cap,
        recovery_rate=config.personality.recovery_rate,
        seed=seed,
    )


def build_baseline(
    engine_path: Path,
    config,
    skill: int,
) -> chess.engine.SimpleEngine:
    if not engine_path.exists():
        raise FileNotFoundError(f"Stockfish not found: {engine_path}")
    engine = chess.engine.SimpleEngine.popen_uci(str(engine_path))
    engine.configure(
        {
            "Threads": config.engine.threads,
            "Hash": config.engine.hash_mb,
            "Skill Level": skill,
        }
    )
    return engine


def update_mood(
    *,
    mood: MoodEngine,
    board: chess.Board,
    color: chess.Color,
    remaining_ms: int,
    initial_ms: int,
    previous_cp: int,
) -> MoodState:
    material = material_balance_for_side(board, color)
    return mood.update(
        time_pressure=clock_pressure(remaining_ms, initial_ms),
        position_complexity=estimate_complexity(board),
        eval_drop_pawns=max(0.0, (previous_cp - material) / 100.0),
        is_ahead=material > 80,
    )


def player_names(
    mode: ArenaMode,
    merijane_color: chess.Color,
) -> tuple[str, str]:
    if mode == "merijane-vs-merijane":
        return "MeriJane34-A", "MeriJane34-B"
    if merijane_color == chess.WHITE:
        return "MeriJane34", "Stockfish"
    return "Stockfish", "MeriJane34"


def detect_opening(moves_uci: list[str]) -> tuple[str, bool]:
    seq = tuple(moves_uci[:8])

    italian = (
        len(seq) >= 5
        and seq[0] == "e2e4"
        and seq[1] == "e7e5"
        and seq[2] == "g1f3"
        and seq[3] == "b8c6"
        and seq[4] == "f1c4"
    )
    if italian:
        return "Italian Game", True

    if seq[:2] == ("e2e4", "c7c6"):
        return "Caro-Kann Defence", False
    if seq[:2] == ("e2e4", "e7e6"):
        return "French Defence", False
    if seq[:2] == ("e2e4", "c7c5"):
        return "Sicilian Defence", False
    if seq[:2] == ("d2d4", "d7d5"):
        return "Queen's Pawn Game", False
    if seq[:2] == ("d2d4", "g8f6"):
        return "Indian Game", False
    if seq and seq[0] == "c2c4":
        return "English Opening", False
    if seq and seq[0] == "g1f3":
        return "Réti Opening", False
    if seq and seq[0] == "e2e4":
        return "King's Pawn Game", False
    if seq and seq[0] == "d2d4":
        return "Queen's Pawn Game", False
    return "Other / Unclassified", False


def merijane_result_from_headers(
    white: str,
    black: str,
    result: str,
) -> tuple[bool | None, str | None]:
    if white.startswith("MeriJane34") and black.startswith("MeriJane34"):
        return None, None

    meri_white = white == "MeriJane34"
    if result == "1/2-1/2":
        return meri_white, "draw"
    meri_won = (result == "1-0" and meri_white) or (
        result == "0-1" and not meri_white
    )
    return meri_white, "win" if meri_won else "loss"


def play_one_game(
    *,
    mode: ArenaMode,
    game_number: int,
    merijane_color: chess.Color,
    speed: str,
    baseline_skill: int,
    baseline_time_ms: int | None,
    max_plies: int,
    seed: int,
    engine_path: Path,
    config,
) -> tuple[chess.pgn.Game, GameMetric, list[MoveMetric]]:
    board = chess.Board()
    game = chess.pgn.Game()
    white_name, black_name = player_names(mode, merijane_color)

    game.headers["Event"] = "MeriJane Local Arena"
    game.headers["Site"] = "Local"
    game.headers["Date"] = datetime.now(timezone.utc).strftime("%Y.%m.%d")
    game.headers["Round"] = str(game_number)
    game.headers["White"] = white_name
    game.headers["Black"] = black_name
    game.headers["TimeControl"] = speed
    game.headers["ArenaMode"] = mode
    game.headers["MeriJaneEngine"] = "Stockfish MultiPV + personality layer"
    if mode == "merijane-vs-stockfish":
        game.headers["BaselineSkill"] = str(baseline_skill)

    node = game
    initial_ms = initial_clock_ms(speed)
    clocks = {chess.WHITE: initial_ms, chess.BLACK: initial_ms}

    engines: dict[chess.Color, StockfishEngine | chess.engine.SimpleEngine] = {}
    moods: dict[chess.Color, MoodEngine] = {}
    previous_cp = {chess.WHITE: 0, chess.BLACK: 0}

    if mode == "merijane-vs-merijane":
        engines[chess.WHITE] = build_merijane(engine_path, config, seed)
        engines[chess.BLACK] = build_merijane(engine_path, config, seed + 10_000)
        moods[chess.WHITE] = build_mood(config, seed)
        moods[chess.BLACK] = build_mood(config, seed + 10_000)
    else:
        engines[merijane_color] = build_merijane(engine_path, config, seed)
        engines[not merijane_color] = build_baseline(
            engine_path,
            config,
            baseline_skill,
        )
        moods[merijane_color] = build_mood(config, seed)

    moves_uci: list[str] = []
    move_metrics: list[MoveMetric] = []

    try:
        while not board.is_game_over(claim_draw=True) and board.ply() < max_plies:
            moving_color = board.turn
            actor_engine = engines[moving_color]
            is_merijane = (
                mode == "merijane-vs-merijane"
                or moving_color == merijane_color
            )

            started = time.perf_counter()

            if is_merijane:
                mood_state = update_mood(
                    mood=moods[moving_color],
                    board=board,
                    color=moving_color,
                    remaining_ms=clocks[moving_color],
                    initial_ms=initial_ms,
                    previous_cp=previous_cp[moving_color],
                )
                candidate = actor_engine.choose_move(
                    board,
                    speed=speed,
                    mood=mood_state,
                )
                move = candidate.move
                previous_cp[moving_color] = candidate.cp
                label = (
                    "MeriJane34-A"
                    if mode == "merijane-vs-merijane"
                    and moving_color == chess.WHITE
                    else "MeriJane34-B"
                    if mode == "merijane-vs-merijane"
                    else "MeriJane34"
                )
                eval_cp = candidate.cp
            else:
                think_ms = (
                    baseline_time_ms
                    if baseline_time_ms is not None
                    else config.engine.move_time_ms.get(speed, 1200)
                )
                result = actor_engine.play(
                    board,
                    chess.engine.Limit(time=think_ms / 1000.0),
                )
                move = result.move
                label = "Stockfish"
                mood_state = None
                eval_cp = None

            elapsed_ms = max(1, int((time.perf_counter() - started) * 1000))
            clocks[moving_color] = max(0, clocks[moving_color] - elapsed_ms)

            san = board.san(move)
            uci = move.uci()
            moves_uci.append(uci)
            board.push(move)
            node = node.add_variation(move)

            if is_merijane and mood_state is not None:
                node.comment = (
                    f"{label}; eval {eval_cp / 100:+.2f}; "
                    f"anxiety {mood_state.anxiety:.2f}; "
                    f"confidence {mood_state.confidence:.2f}; "
                    f"panic {mood_state.panic:.2f}; "
                    f"elapsed {elapsed_ms} ms; "
                    f"clock {clocks[moving_color] / 1000:.1f}s"
                )
            else:
                node.comment = (
                    f"Plain Stockfish; skill {baseline_skill}; "
                    f"elapsed {elapsed_ms} ms; "
                    f"clock {clocks[moving_color] / 1000:.1f}s"
                )

            move_metrics.append(
                MoveMetric(
                    game=game_number,
                    ply=board.ply(),
                    move_number=(board.ply() + 1) // 2,
                    color="white" if moving_color == chess.WHITE else "black",
                    actor=label,
                    san=san,
                    uci=uci,
                    elapsed_ms=elapsed_ms,
                    remaining_clock_ms=clocks[moving_color],
                    eval_cp=eval_cp,
                    anxiety=mood_state.anxiety if mood_state else None,
                    confidence=mood_state.confidence if mood_state else None,
                    panic=mood_state.panic if mood_state else None,
                )
            )

            move_number = (board.ply() + 1) // 2
            side = "..." if moving_color == chess.BLACK else "."
            print(
                f"{move_number:03d}{side} {san:<8} "
                f"{label:<13} "
                f"time={elapsed_ms:>5}ms "
                f"clock={clocks[moving_color] / 1000:>7.1f}s"
            )

        if board.is_game_over(claim_draw=True):
            result = board.result(claim_draw=True)
            outcome = board.outcome(claim_draw=True)
            termination = (
                outcome.termination.name if outcome is not None else "normal"
            )
        else:
            result = "1/2-1/2"
            termination = "max plies adjudication"

        game.headers["Result"] = result
        game.headers["Termination"] = termination

        opening, italian = detect_opening(moves_uci)
        meri_times = [
            m.elapsed_ms for m in move_metrics if m.actor.startswith("MeriJane34")
        ]
        stockfish_times = [
            m.elapsed_ms for m in move_metrics if m.actor == "Stockfish"
        ]
        anxiety_values = [
            m.anxiety for m in move_metrics if m.anxiety is not None
        ]
        confidence_values = [
            m.confidence for m in move_metrics if m.confidence is not None
        ]
        panic_values = [
            m.panic for m in move_metrics if m.panic is not None
        ]

        meri_white, meri_result = merijane_result_from_headers(
            white_name,
            black_name,
            result,
        )

        metric = GameMetric(
            game=game_number,
            mode=mode,
            white=white_name,
            black=black_name,
            result=result,
            termination=termination,
            plies=board.ply(),
            full_moves=math.ceil(board.ply() / 2),
            opening=opening,
            italian=italian,
            meri_white=meri_white,
            meri_result=meri_result,
            avg_merijane_time_ms=statistics.fmean(meri_times) if meri_times else 0.0,
            avg_stockfish_time_ms=(
                statistics.fmean(stockfish_times) if stockfish_times else None
            ),
            avg_anxiety=(
                statistics.fmean(anxiety_values) if anxiety_values else 0.0
            ),
            max_anxiety=max(anxiety_values, default=0.0),
            avg_confidence=(
                statistics.fmean(confidence_values) if confidence_values else 0.0
            ),
            max_panic=max(panic_values, default=0.0),
        )
        print(f"\nGame {game_number} result: {result} | {opening}\n")
        return game, metric, move_metrics

    finally:
        closed: set[int] = set()
        for engine in engines.values():
            engine_id = id(engine)
            if engine_id in closed:
                continue
            closed.add(engine_id)
            if isinstance(engine, StockfishEngine):
                engine.close()
            else:
                engine.quit()


def save_pgn(games: list[chess.pgn.Game], run_dir: Path) -> Path:
    path = run_dir / "games.pgn"
    with path.open("w", encoding="utf-8") as handle:
        exporter = chess.pgn.FileExporter(handle)
        for game in games:
            game.accept(exporter)
            handle.write("\n")
    return path


def elo_delta_from_score(score: float) -> float | None:
    if score <= 0.0 or score >= 1.0:
        return None
    return -400.0 * math.log10((1.0 / score) - 1.0)


def benchmark_summary(
    game_metrics: list[GameMetric],
    move_metrics: list[MoveMetric],
    mode: ArenaMode,
    baseline_skill: int,
) -> dict:
    total = len(game_metrics)
    italian_count = sum(g.italian for g in game_metrics)
    opening_counts: dict[str, int] = {}
    for metric in game_metrics:
        opening_counts[metric.opening] = opening_counts.get(metric.opening, 0) + 1

    meri_moves = [
        m for m in move_metrics if m.actor.startswith("MeriJane34")
    ]
    anxiety_values = [m.anxiety for m in meri_moves if m.anxiety is not None]
    confidence_values = [
        m.confidence for m in meri_moves if m.confidence is not None
    ]
    panic_values = [m.panic for m in meri_moves if m.panic is not None]

    summary: dict = {
        "mode": mode,
        "games": total,
        "average_game_length_full_moves": round(
            statistics.fmean(g.full_moves for g in game_metrics), 2
        ) if game_metrics else 0.0,
        "italian_games": italian_count,
        "italian_frequency": round(italian_count / total, 4) if total else 0.0,
        "openings": dict(
            sorted(opening_counts.items(), key=lambda item: item[1], reverse=True)
        ),
        "average_merijane_think_ms": round(
            statistics.fmean(m.elapsed_ms for m in meri_moves), 2
        ) if meri_moves else 0.0,
        "average_anxiety": round(
            statistics.fmean(anxiety_values), 4
        ) if anxiety_values else 0.0,
        "max_anxiety": round(max(anxiety_values, default=0.0), 4),
        "average_confidence": round(
            statistics.fmean(confidence_values), 4
        ) if confidence_values else 0.0,
        "max_panic": round(max(panic_values, default=0.0), 4),
    }

    if mode == "merijane-vs-stockfish":
        wins = sum(g.meri_result == "win" for g in game_metrics)
        draws = sum(g.meri_result == "draw" for g in game_metrics)
        losses = sum(g.meri_result == "loss" for g in game_metrics)
        score = (wins + 0.5 * draws) / total if total else 0.0
        delta = elo_delta_from_score(score)

        summary.update(
            {
                "merijane_wins": wins,
                "draws": draws,
                "stockfish_wins": losses,
                "merijane_score": round(score, 4),
                "baseline_skill": baseline_skill,
                "estimated_elo_difference": (
                    round(delta, 1) if delta is not None else None
                ),
                "elo_note": (
                    "Elo difference is a rough local estimate against this exact "
                    "baseline configuration, not a Lichess rating."
                ),
            }
        )
    else:
        summary.update(
            {
                "white_wins": sum(g.result == "1-0" for g in game_metrics),
                "draws": sum(g.result == "1/2-1/2" for g in game_metrics),
                "black_wins": sum(g.result == "0-1" for g in game_metrics),
            }
        )

    paired = [
        m for m in meri_moves
        if m.anxiety is not None
        and m.confidence is not None
        and m.panic is not None
    ]
    elapsed_seconds = [m.elapsed_ms / 1000.0 for m in paired]

    anxiety_corr = _safe_correlation(
        [float(m.anxiety) for m in paired],
        elapsed_seconds,
    )
    confidence_corr = _safe_correlation(
        [float(m.confidence) for m in paired],
        elapsed_seconds,
    )
    panic_corr = _safe_correlation(
        [float(m.panic) for m in paired],
        elapsed_seconds,
    )

    summary["timing_correlations"] = {
        "anxiety_vs_think_time": (
            round(anxiety_corr, 4) if anxiety_corr is not None else None
        ),
        "confidence_vs_think_time": (
            round(confidence_corr, 4) if confidence_corr is not None else None
        ),
        "panic_vs_think_time": (
            round(panic_corr, 4) if panic_corr is not None else None
        ),
        "interpretation": (
            "Positive means longer thinking as the mood value rises; "
            "negative means faster play."
        ),
    }

    return summary


def save_metric_chart(
    move_metrics: list[MoveMetric],
    run_dir: Path,
    *,
    field: str,
    title: str,
    ylabel: str,
    filename: str,
    ylim: tuple[float, float] | None = (0.0, 1.0),
) -> Path | None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print(
            f"{title} skipped: matplotlib is not installed. "
            "Run: pip install matplotlib"
        )
        return None

    rows = [
        m for m in move_metrics
        if m.actor.startswith("MeriJane34")
        and getattr(m, field) is not None
    ]
    if not rows:
        return None

    path = run_dir / filename
    plt.figure(figsize=(11, 5))

    # Plot each game separately. This avoids diagonal lines caused by
    # connecting the end of one game to the beginning of the next.
    groups: dict[tuple[int, str], list[MoveMetric]] = {}
    for metric in rows:
        groups.setdefault((metric.game, metric.actor), []).append(metric)

    for (game_number, actor), subset in sorted(groups.items()):
        subset.sort(key=lambda item: item.ply)
        plt.plot(
            [m.ply for m in subset],
            [getattr(m, field) for m in subset],
            marker="o",
            markersize=2,
            linewidth=1,
            alpha=0.72,
            label=f"Game {game_number} · {actor}",
        )

    plt.title(title)
    plt.xlabel("Ply")
    plt.ylabel(ylabel)
    if ylim is not None:
        plt.ylim(*ylim)

    # A legend becomes unreadable in large benchmarks.
    if len(groups) <= 8:
        plt.legend(fontsize=8)

    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()
    return path


def save_think_time_chart(
    move_metrics: list[MoveMetric],
    run_dir: Path,
) -> Path | None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    rows = [
        m for m in move_metrics if m.actor.startswith("MeriJane34")
    ]
    if not rows:
        return None

    path = run_dir / "think_time_history.png"
    plt.figure(figsize=(11, 5))

    groups: dict[tuple[int, str], list[MoveMetric]] = {}
    for metric in rows:
        groups.setdefault((metric.game, metric.actor), []).append(metric)

    for (game_number, actor), subset in sorted(groups.items()):
        subset.sort(key=lambda item: item.ply)
        plt.plot(
            [m.ply for m in subset],
            [m.elapsed_ms / 1000.0 for m in subset],
            marker="o",
            markersize=2,
            linewidth=1,
            alpha=0.72,
            label=f"Game {game_number} · {actor}",
        )

    plt.title("MeriJane Think-Time History")
    plt.xlabel("Ply")
    plt.ylabel("Seconds")
    if len(groups) <= 8:
        plt.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()
    return path


def _safe_correlation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(ys) < 3:
        return None
    if statistics.pstdev(xs) == 0 or statistics.pstdev(ys) == 0:
        return None
    return statistics.correlation(xs, ys)


def chat_simulator(seed: int = 42) -> None:
    from merijane.chat import (
        START_MESSAGES,
        INTERESTING_MESSAGES,
        END_WIN,
        END_LOSS,
        END_DRAW,
        BATTERY_JOKES,
    )

    rng = random.Random(seed)
    print("\nMeriJane chat simulator")
    print("-----------------------")
    print(f"Start       : {rng.choice(START_MESSAGES)}")
    print(f"Interesting : {rng.choice(INTERESTING_MESSAGES)}")
    print(f"Winning     : {rng.choice(BATTERY_JOKES)}")
    print(f"Win         : {rng.choice(END_WIN)}")
    print(f"Loss        : {rng.choice(END_LOSS)}")
    print(f"Draw        : {rng.choice(END_DRAW)}")


def print_summary(summary: dict) -> None:
    print("\nBenchmark summary")
    print("=================")
    for key, value in summary.items():
        if key == "openings":
            continue
        print(f"{key.replace('_', ' ').title():28}: {value}")

    print("\nOpening statistics")
    print("------------------")
    for opening, count in summary["openings"].items():
        print(f"{opening:<28} {count}")


def create_run_dir(output_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = output_dir / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def run_arena(
    *,
    mode: ArenaMode,
    games_count: int,
    speed: str,
    baseline_skill: int,
    baseline_time_ms: int | None,
    max_plies: int,
    seed: int,
    engine_path: Path,
    config_path: Path,
    output_dir: Path,
) -> None:
    config = load_config(config_path)
    run_dir = create_run_dir(output_dir)

    games: list[chess.pgn.Game] = []
    game_metrics: list[GameMetric] = []
    move_metrics: list[MoveMetric] = []

    for index in range(games_count):
        merijane_color = (
            chess.WHITE if (index + seed) % 2 == 0 else chess.BLACK
        )

        if mode == "merijane-vs-merijane":
            matchup = "MeriJane34-A vs MeriJane34-B"
        else:
            matchup = (
                "MeriJane34 vs Stockfish"
                if merijane_color == chess.WHITE
                else "Stockfish vs MeriJane34"
            )

        print(f"\n=== Game {index + 1}/{games_count}: {matchup} ===\n")

        game, metric, moves = play_one_game(
            mode=mode,
            game_number=index + 1,
            merijane_color=merijane_color,
            speed=speed,
            baseline_skill=baseline_skill,
            baseline_time_ms=baseline_time_ms,
            max_plies=max_plies,
            seed=seed + index,
            engine_path=engine_path,
            config=config,
        )
        games.append(game)
        game_metrics.append(metric)
        move_metrics.extend(moves)

    pgn_path = save_pgn(games, run_dir)
    save_csv_rows(
        run_dir / "games_summary.csv",
        [asdict(metric) for metric in game_metrics],
    )
    save_csv_rows(
        run_dir / "move_history.csv",
        [asdict(metric) for metric in move_metrics],
    )

    summary = benchmark_summary(
        game_metrics,
        move_metrics,
        mode,
        baseline_skill,
    )
    save_json(run_dir / "benchmark_summary.json", summary)
    anxiety_path = save_metric_chart(
        move_metrics,
        run_dir,
        field="anxiety",
        title="MeriJane Anxiety History",
        ylabel="Anxiety",
        filename="anxiety_history.png",
    )
    confidence_path = save_metric_chart(
        move_metrics,
        run_dir,
        field="confidence",
        title="MeriJane Confidence History",
        ylabel="Confidence",
        filename="confidence_history.png",
    )
    panic_path = save_metric_chart(
        move_metrics,
        run_dir,
        field="panic",
        title="MeriJane Panic History",
        ylabel="Panic",
        filename="panic_history.png",
    )
    think_time_path = save_think_time_chart(move_metrics, run_dir)

    print_summary(summary)
    print(f"\nPGN export        : {pgn_path}")
    print(f"Game statistics   : {run_dir / 'games_summary.csv'}")
    print(f"Move/mood history : {run_dir / 'move_history.csv'}")
    print(f"Benchmark JSON    : {run_dir / 'benchmark_summary.json'}")
    if anxiety_path:
        print(f"Anxiety graph     : {anxiety_path}")
    if confidence_path:
        print(f"Confidence graph  : {confidence_path}")
    if panic_path:
        print(f"Panic graph       : {panic_path}")
    if think_time_path:
        print(f"Think-time graph  : {think_time_path}")


def ask_int(prompt: str, default: int) -> int:
    raw = input(f"{prompt} [{default}]: ").strip()
    return int(raw) if raw else default


def ask_choice(prompt: str, choices: list[str], default: str) -> str:
    raw = input(f"{prompt} ({'/'.join(choices)}) [{default}]: ").strip().lower()
    return raw if raw in choices else default


def interactive_menu(args: argparse.Namespace) -> None:
    while True:
        print(
            """
========================================
          MERIJANE LOCAL ARENA
========================================
1) MeriJane34 vs Stockfish
2) MeriJane34 vs MeriJane34
3) Arena benchmark
4) Chat simulator
5) Exit
"""
        )
        choice = input("Select an option: ").strip()

        if choice == "5":
            return
        if choice == "4":
            chat_simulator(args.seed)
            input("\nPress Enter to return to the menu...")
            continue
        if choice not in {"1", "2", "3"}:
            print("Invalid option.")
            continue

        mode: ArenaMode = (
            "merijane-vs-merijane"
            if choice == "2"
            else "merijane-vs-stockfish"
        )
        default_games = 10 if choice == "3" else 1
        games_count = ask_int("Number of games", default_games)
        speed = ask_choice(
            "Speed",
            ["blitz", "rapid", "classical"],
            args.speed,
        )
        baseline_skill = args.baseline_skill
        if mode == "merijane-vs-stockfish":
            baseline_skill = ask_int(
                "Plain Stockfish skill level (0-20)",
                args.baseline_skill,
            )
        max_plies = ask_int("Maximum plies", args.max_plies)

        run_arena(
            mode=mode,
            games_count=games_count,
            speed=speed,
            baseline_skill=baseline_skill,
            baseline_time_ms=args.baseline_time_ms,
            max_plies=max_plies,
            seed=args.seed,
            engine_path=args.engine_path,
            config_path=args.config,
            output_dir=args.output_dir,
        )
        input("\nPress Enter to return to the menu...")


def main() -> None:
    args = parse_args()

    if args.menu:
        interactive_menu(args)
        return

    run_arena(
        mode=args.mode,
        games_count=args.games,
        speed=args.speed,
        baseline_skill=args.baseline_skill,
        baseline_time_ms=args.baseline_time_ms,
        max_plies=args.max_plies,
        seed=args.seed,
        engine_path=args.engine_path,
        config_path=args.config,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()
