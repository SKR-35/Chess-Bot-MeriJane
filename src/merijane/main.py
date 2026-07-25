from __future__ import annotations

import argparse
import asyncio
import logging

from .bot import run_bot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the MeriJane34 official Lichess bot."
    )
    parser.add_argument(
        "--games",
        type=int,
        default=None,
        help=(
            "Stop cleanly after this many completed games. "
            "Omit for the config value or unlimited mode."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        asyncio.run(run_bot(session_game_limit=args.games))
    except KeyboardInterrupt:
        logging.getLogger(__name__).info(
            "Shutdown requested. MeriJane is offline."
        )


if __name__ == "__main__":
    main()
