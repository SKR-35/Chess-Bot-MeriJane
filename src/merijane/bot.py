from __future__ import annotations

import asyncio
import logging

from .engine import StockfishEngine
from .game import GameRunner
from .lichess_api import LichessAPI
from .personality import PersonalitySelector
from .settings import EnvSettings, load_config

LOGGER = logging.getLogger(__name__)


def _challenge_allowed(challenge: dict, config) -> tuple[bool, str]:
    variant = challenge.get("variant", {}).get("key", "")
    speed = challenge.get("speed", "")
    rated = bool(challenge.get("rated", False))
    increment = int(challenge.get("timeControl", {}).get("increment", 0) or 0)

    challenger = challenge.get("challenger") or {}
    challenger_title = str(challenger.get("title", "")).upper()
    is_bot_challenger = challenger_title == "BOT"

    if is_bot_challenger and not config.bot.accept_bot_challenges:
        return False, "generic"
    if variant not in config.bot.allowed_variants:
        return False, "variant"
    if speed not in config.bot.allowed_speeds:
        return False, "timeControl"
    if increment < config.bot.min_increment_seconds:
        return False, "tooFast"
    if config.bot.casual_only_while_testing and rated:
        return False, "casual"
    return True, ""


async def run_bot(session_game_limit: int | None = None) -> None:
    env = EnvSettings()
    config = load_config(env.merijane_config)

    limit = (
        session_game_limit
        if session_game_limit is not None
        else config.bot.session_game_limit
    )
    if limit is not None and limit < 1:
        raise ValueError("Session game limit must be at least 1.")

    api = LichessAPI(env.lichess_bot_token)
    selector = PersonalitySelector(config.personality, config.engine)
    engine = StockfishEngine(env.stockfish_path, config.engine, selector)
    engine.start()
    runner = GameRunner(api, engine, config)

    active_games: set[str] = set()
    completed_game_ids: set[str] = set()
    tasks: set[asyncio.Task] = set()
    completed_games = 0

    LOGGER.info(
        "MeriJane started. Session game limit: %s",
        limit if limit is not None else "unlimited",
    )

    async def launch_game(game_id: str) -> None:
        active_games.add(game_id)
        try:
            await runner.run(game_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Game %s failed", game_id)
        finally:
            active_games.discard(game_id)

    try:
        async for event in api.stream_events():
            kind = event.get("type")

            if kind == "challenge":
                challenge = event["challenge"]

                reserved_games = completed_games + len(active_games)
                session_has_capacity = (
                    limit is None or reserved_games < limit
                )
                concurrency_has_capacity = (
                    len(active_games) < config.bot.max_concurrent_games
                )
                allowed, reason = _challenge_allowed(challenge, config)

                if (
                    config.bot.accept_challenges
                    and allowed
                    and session_has_capacity
                    and concurrency_has_capacity
                ):
                    await api.accept_challenge(challenge["id"])
                else:
                    decline_reason = reason or (
                        "later"
                        if not session_has_capacity or not concurrency_has_capacity
                        else "generic"
                    )
                    await api.decline_challenge(
                        challenge["id"],
                        decline_reason,
                    )

            elif kind == "gameStart":
                game_id = event["game"]["id"]

                # Ignore a late duplicate/start after the session limit has
                # already been reserved.
                if limit is not None and completed_games >= limit:
                    LOGGER.warning(
                        "Ignoring gameStart %s because session limit is reached.",
                        game_id,
                    )
                    continue

                task = asyncio.create_task(launch_game(game_id))
                tasks.add(task)
                task.add_done_callback(tasks.discard)

            elif kind == "gameFinish":
                game_id = event.get("game", {}).get("id")
                if game_id and game_id not in completed_game_ids:
                    completed_game_ids.add(game_id)
                    completed_games += 1
                    LOGGER.info(
                        "Completed games: %s%s",
                        completed_games,
                        f"/{limit}" if limit is not None else "",
                    )

                if limit is not None and completed_games >= limit:
                    LOGGER.info(
                        "Session limit reached. MeriJane will stop after "
                        "the current game has fully closed."
                    )
                    break

        # A gameFinish event normally arrives when the game task is ending.
        # Wait briefly for clean PGN/chat/game-stream shutdown rather than
        # cancelling a game in progress.
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    finally:
        # This path is also used on Ctrl+C or connection failure.
        for task in list(tasks):
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await api.close()
        engine.close()
        LOGGER.info("MeriJane is offline.")