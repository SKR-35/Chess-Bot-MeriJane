from __future__ import annotations

import asyncio
import logging
import time

import chess

from .chat import ChatDirector
from .chat_log import GameChatLogger
from .engine import StockfishEngine
from .lichess_api import LichessAPI
from .mood import MoodEngine
from .personality import estimate_complexity
from .settings import AppConfig
from .telemetry import LiveMoveMetric, export_live_game, utc_now_iso

LOGGER = logging.getLogger(__name__)


def _win_probability(cp: int) -> float:
    return 1.0 / (1.0 + 10.0 ** (-cp / 400.0))


def _clock_pressure(remaining_ms: int, initial_ms: int) -> float:
    if initial_ms <= 0:
        return 0.0
    ratio = remaining_ms / initial_ms
    if ratio >= 0.35:
        return 0.0
    return min(1.0, (0.35 - ratio) / 0.35)


class GameRunner:
    def __init__(
        self,
        api: LichessAPI,
        engine: StockfishEngine,
        config: AppConfig,
    ) -> None:
        self.api = api
        self.engine = engine
        self.config = config

    async def _send_chat(
        self,
        *,
        game_id: str,
        logger: GameChatLogger,
        text: str | None,
        room: str = "player",
    ) -> None:
        if not text:
            return

        await self.api.chat(game_id, text, room=room)
        logger.log_generated(text=text, room=room)

    async def run(self, game_id: str) -> None:
        board = chess.Board()
        bot_color: str | None = None
        speed = "rapid"
        initial_ms = 600_000
        previous_cp = 0
        processed_move_count = -1
        previous_anxiety = self.config.personality.base_anxiety
        previous_panic = 0.0
        started_at = utc_now_iso()
        opponent_username = "unknown"
        rated = False
        all_moves_uci: list[str] = []
        live_metrics: list[LiveMoveMetric] = []

        chat_logger = GameChatLogger(
            game_id=game_id,
            bot_username=self.config.bot.username,
            base_dir=self.config.logging.lichess_games_dir,
            enabled=self.config.logging.save_chat,
        )
        chat_logger.log_system(
            event_type="game_runner_started",
            text="MeriJane game runner started.",
        )

        mood = MoodEngine(
            self.config.personality.base_anxiety,
            self.config.personality.base_confidence,
            self.config.personality.panic_cap,
            self.config.personality.recovery_rate,
        )
        chat = ChatDirector(
            self.config.chat.enabled,
            self.config.chat.max_messages_per_game,
            self.config.chat.battery_joke_probability,
        )

        try:
            async for event in self.api.stream_game(game_id):
                kind = event.get("type")

                if kind == "chatLine":
                    chat_logger.log_stream_event(event)
                    continue

                if kind == "gameFull":
                    white_id = event.get("white", {}).get("id", "").lower()
                    bot_color = (
                        "white"
                        if white_id == self.config.bot.username.lower()
                        else "black"
                    )
                    speed = event.get("speed", "rapid")
                    rated = bool(event.get("rated", False))
                    white_name = str(
                        event.get("white", {}).get("name")
                        or event.get("white", {}).get("id")
                        or "unknown"
                    )
                    black_name = str(
                        event.get("black", {}).get("name")
                        or event.get("black", {}).get("id")
                        or "unknown"
                    )
                    opponent_username = (
                        black_name if bot_color == "white" else white_name
                    )
                    clock = event.get("clock") or {}
                    initial_ms = int(clock.get("initial", 600)) * 1000
                    state = event["state"]

                    await self._send_chat(
                        game_id=game_id,
                        logger=chat_logger,
                        text=chat.start(),
                    )

                elif kind == "gameState":
                    state = event
                else:
                    continue

                moves = state.get("moves", "").split()
                status = state.get("status", "started")

                # Handle game termination even when no new move was added,
                # for example after a resignation, timeout, or abort.
                if status != "started":
                    if bot_color:
                        if state.get("winner") == "white":
                            result = "1-0"
                        elif state.get("winner") == "black":
                            result = "0-1"
                        else:
                            result = "1/2-1/2"

                        for message in chat.finish_sequence(result, bot_color):
                            await self._send_chat(
                                game_id=game_id,
                                logger=chat_logger,
                                text=message,
                            )

                    finished_at = utc_now_iso()
                    export_live_game(
                        game_dir=chat_logger.game_dir,
                        game_id=game_id,
                        bot_username=self.config.bot.username,
                        opponent_username=opponent_username,
                        bot_color=bot_color or "unknown",
                        speed=speed,
                        rated=rated,
                        result=result,
                        status=status,
                        winner=state.get("winner"),
                        started_at=started_at,
                        finished_at=finished_at,
                        moves_uci=moves,
                        move_metrics=live_metrics,
                    )

                    chat_logger.log_system(
                        event_type="game_finished",
                        text=(
                            f"Game ended with status={status}; "
                            f"winner={state.get('winner', 'none')}."
                        ),
                    )
                    return

                # gameFull contains the initial position. Its move list is empty,
                # so comparing move counts rather than zero-based ply indices
                # ensures that White can make the first move.
                current_move_count = len(moves)
                if current_move_count <= processed_move_count:
                    continue

                board.reset()
                for move_uci in moves:
                    board.push_uci(move_uci)
                processed_move_count = current_move_count

                is_bot_turn = (
                    bot_color == "white" and board.turn == chess.WHITE
                ) or (
                    bot_color == "black" and board.turn == chess.BLACK
                )
                if not is_bot_turn:
                    continue

                remaining_ms = int(
                    state.get(
                        "wtime" if bot_color == "white" else "btime",
                        initial_ms,
                    )
                )
                pressure = _clock_pressure(remaining_ms, initial_ms)
                complexity = estimate_complexity(board)

                is_ahead = previous_cp > 80
                eval_drop = 0.0
                mood_state = mood.update(
                    time_pressure=pressure,
                    position_complexity=complexity,
                    eval_drop_pawns=eval_drop,
                    is_ahead=is_ahead,
                )

                fen_before = board.fen()
                started_thinking = time.perf_counter()
                candidate = await asyncio.to_thread(
                    self.engine.choose_move,
                    board,
                    speed=speed,
                    mood=mood_state,
                )
                think_time_ms = max(
                    1,
                    int((time.perf_counter() - started_thinking) * 1000),
                )
                previous_cp = candidate.cp

                await self._send_chat(
                    game_id=game_id,
                    logger=chat_logger,
                    text=chat.maybe_in_game_message(
                        ply=board.ply(),
                        win_probability=_win_probability(candidate.cp),
                        battery_threshold=(
                            self.config.chat.win_probability_for_battery_joke
                        ),
                        clock_pressure=pressure,
                        position_complexity=complexity,
                        previous_anxiety=previous_anxiety,
                        current_anxiety=mood_state.anxiety,
                        previous_panic=previous_panic,
                        current_panic=mood_state.panic,
                    ),
                )

                previous_anxiety = mood_state.anxiety
                previous_panic = mood_state.panic

                move_uci = candidate.move.uci()
                move_san = board.san(candidate.move)
                board_after = board.copy(stack=False)
                board_after.push(candidate.move)

                live_metrics.append(
                    LiveMoveMetric(
                        ply=board.ply() + 1,
                        move_number=(board.ply() // 2) + 1,
                        color=bot_color or "unknown",
                        san=move_san,
                        uci=move_uci,
                        eval_cp=candidate.cp,
                        win_probability=_win_probability(candidate.cp),
                        remaining_clock_ms=remaining_ms,
                        clock_pressure=pressure,
                        position_complexity=complexity,
                        anxiety=mood_state.anxiety,
                        confidence=mood_state.confidence,
                        panic=mood_state.panic,
                        think_time_ms=think_time_ms,
                        fen_before=fen_before,
                        fen_after=board_after.fen(),
                    )
                )

                await self.api.make_move(game_id, move_uci)

        except asyncio.CancelledError:
            chat_logger.log_system(
                event_type="game_runner_cancelled",
                text="Game runner was cancelled.",
            )
            raise
        except Exception as exc:
            chat_logger.log_system(
                event_type="game_runner_error",
                text=f"{type(exc).__name__}: {exc}",
            )
            raise
        finally:
            chat_logger.log_system(
                event_type="game_runner_closed",
                text="MeriJane game runner closed.",
            )
