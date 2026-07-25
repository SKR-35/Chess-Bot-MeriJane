from __future__ import annotations

import csv
import json
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import chess
import chess.pgn


@dataclass
class LiveMoveMetric:
    ply: int
    move_number: int
    color: str
    san: str
    uci: str
    eval_cp: int
    win_probability: float
    remaining_clock_ms: int
    clock_pressure: float
    position_complexity: float
    anxiety: float
    confidence: float
    panic: float
    think_time_ms: int
    fen_before: str
    fen_after: str


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_csv_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def save_pgn(
    path: Path,
    *,
    moves_uci: list[str],
    headers: dict[str, str],
) -> None:
    game = chess.pgn.Game()
    for key, value in headers.items():
        game.headers[key] = value

    board = game.board()
    node = game
    for move_uci in moves_uci:
        move = chess.Move.from_uci(move_uci)
        if move not in board.legal_moves:
            break
        node = node.add_variation(move)
        board.push(move)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        exporter = chess.pgn.FileExporter(handle)
        game.accept(exporter)
        handle.write("\n")


def save_metric_chart(
    move_metrics: list[LiveMoveMetric],
    output_dir: Path,
    *,
    field: str,
    title: str,
    ylabel: str,
    filename: str,
    ylim: tuple[float, float] | None = (0.0, 1.0),
) -> Path | None:
    try:
        import matplotlib
        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    if not move_metrics:
        return None

    values = [getattr(metric, field) for metric in move_metrics]
    plies = [metric.ply for metric in move_metrics]

    path = output_dir / filename
    plt.figure(figsize=(11, 5))
    plt.plot(plies, values, marker="o", markersize=3, linewidth=1)
    plt.title(title)
    plt.xlabel("Ply")
    plt.ylabel(ylabel)
    if ylim is not None:
        plt.ylim(*ylim)
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()
    return path


def save_think_time_chart(
    move_metrics: list[LiveMoveMetric],
    output_dir: Path,
) -> Path | None:
    try:
        import matplotlib
        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    if not move_metrics:
        return None

    path = output_dir / "think_time_history.png"
    plt.figure(figsize=(11, 5))
    plt.plot(
        [metric.ply for metric in move_metrics],
        [metric.think_time_ms / 1000.0 for metric in move_metrics],
        marker="o",
        markersize=3,
        linewidth=1,
    )
    plt.title("MeriJane Think-Time History")
    plt.xlabel("Ply")
    plt.ylabel("Seconds")
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()
    return path


def build_live_summary(
    *,
    game_id: str,
    bot_username: str,
    opponent_username: str,
    bot_color: str,
    speed: str,
    rated: bool,
    result: str,
    status: str,
    winner: str | None,
    started_at: str,
    finished_at: str,
    moves_uci: list[str],
    move_metrics: list[LiveMoveMetric],
) -> dict[str, Any]:
    anxiety = [metric.anxiety for metric in move_metrics]
    confidence = [metric.confidence for metric in move_metrics]
    panic = [metric.panic for metric in move_metrics]
    think_times = [metric.think_time_ms for metric in move_metrics]

    return {
        "game_id": game_id,
        "bot_username": bot_username,
        "opponent_username": opponent_username,
        "bot_color": bot_color,
        "speed": speed,
        "rated": rated,
        "result": result,
        "status": status,
        "winner": winner,
        "started_at": started_at,
        "finished_at": finished_at,
        "plies": len(moves_uci),
        "full_moves": (len(moves_uci) + 1) // 2,
        "merijane_moves": len(move_metrics),
        "average_eval_cp": round(
            statistics.fmean(metric.eval_cp for metric in move_metrics), 2
        ) if move_metrics else 0.0,
        "average_think_time_ms": round(
            statistics.fmean(think_times), 2
        ) if think_times else 0.0,
        "average_anxiety": round(
            statistics.fmean(anxiety), 4
        ) if anxiety else 0.0,
        "max_anxiety": round(max(anxiety, default=0.0), 4),
        "average_confidence": round(
            statistics.fmean(confidence), 4
        ) if confidence else 0.0,
        "max_panic": round(max(panic, default=0.0), 4),
    }


def export_live_game(
    *,
    game_dir: Path,
    game_id: str,
    bot_username: str,
    opponent_username: str,
    bot_color: str,
    speed: str,
    rated: bool,
    result: str,
    status: str,
    winner: str | None,
    started_at: str,
    finished_at: str,
    moves_uci: list[str],
    move_metrics: list[LiveMoveMetric],
) -> None:
    game_dir.mkdir(parents=True, exist_ok=True)

    summary = build_live_summary(
        game_id=game_id,
        bot_username=bot_username,
        opponent_username=opponent_username,
        bot_color=bot_color,
        speed=speed,
        rated=rated,
        result=result,
        status=status,
        winner=winner,
        started_at=started_at,
        finished_at=finished_at,
        moves_uci=moves_uci,
        move_metrics=move_metrics,
    )

    save_json(game_dir / "game_summary.json", summary)
    save_csv_rows(
        game_dir / "move_history.csv",
        [asdict(metric) for metric in move_metrics],
    )

    white = bot_username if bot_color == "white" else opponent_username
    black = opponent_username if bot_color == "white" else bot_username
    save_pgn(
        game_dir / "game.pgn",
        moves_uci=moves_uci,
        headers={
            "Event": "Lichess BOT Game",
            "Site": f"https://lichess.org/{game_id}",
            "Date": started_at[:10].replace("-", "."),
            "White": white,
            "Black": black,
            "Result": result,
            "TimeControl": speed,
            "Termination": status,
        },
    )

    save_metric_chart(
        move_metrics,
        game_dir,
        field="anxiety",
        title="MeriJane Anxiety History",
        ylabel="Anxiety",
        filename="anxiety_history.png",
    )
    save_metric_chart(
        move_metrics,
        game_dir,
        field="confidence",
        title="MeriJane Confidence History",
        ylabel="Confidence",
        filename="confidence_history.png",
    )
    save_metric_chart(
        move_metrics,
        game_dir,
        field="panic",
        title="MeriJane Panic History",
        ylabel="Panic",
        filename="panic_history.png",
    )
    save_think_time_chart(move_metrics, game_dir)
