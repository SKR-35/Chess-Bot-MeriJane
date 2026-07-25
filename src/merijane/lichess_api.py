from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx


LOGGER = logging.getLogger(__name__)


class LichessAPI:
    BASE_URL = "https://lichess.org"

    def __init__(self, token: str) -> None:
        # Lichess recommends making only one API request at a time.
        self._request_lock = asyncio.Lock()

        self.client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/x-ndjson",
                "User-Agent": "MeriJane-Lichess-Bot/0.1",
            },
            timeout=httpx.Timeout(connect=20.0, read=None, write=20.0, pool=20.0),
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def _stream(self, path: str) -> AsyncIterator[dict[str, Any]]:
        async with self.client.stream("GET", path) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.strip():
                    yield json.loads(line)

    async def stream_events(self) -> AsyncIterator[dict[str, Any]]:
        async for event in self._stream("/api/stream/event"):
            yield event

    async def stream_game(self, game_id: str) -> AsyncIterator[dict[str, Any]]:
        async for event in self._stream(f"/api/bot/game/stream/{game_id}"):
            yield event

    async def accept_challenge(self, challenge_id: str) -> None:
        async with self._request_lock:
            response = await self.client.post(
                f"/api/challenge/{challenge_id}/accept"
            )
        response.raise_for_status()

    async def decline_challenge(
        self,
        challenge_id: str,
        reason: str = "generic",
    ) -> None:
        async with self._request_lock:
            response = await self.client.post(
                f"/api/challenge/{challenge_id}/decline",
                data={"reason": reason},
            )

        # A challenge may disappear before the decline request reaches Lichess.
        if response.status_code == 404:
            LOGGER.info(
                "Challenge %s no longer exists; decline skipped.",
                challenge_id,
            )
            return

        response.raise_for_status()

    async def make_move(self, game_id: str, move_uci: str) -> None:
        async with self._request_lock:
            response = await self.client.post(
                f"/api/bot/game/{game_id}/move/{move_uci}"
            )
        response.raise_for_status()

    async def chat(self, game_id: str, text: str, room: str = "player") -> None:
        LOGGER.info(
            "Sending chat | game=%s | room=%s | chars=%d | bytes=%d | text=%r",
            game_id,
            room,
            len(text),
            len(text.encode("utf-8")),
            text,
        )

        async with self._request_lock:
            response = await self.client.post(
                f"/api/bot/game/{game_id}/chat",
                data={"room": room, "text": text},
            )

        if response.is_error:
            response_body = response.text.strip() or "<empty response body>"
            LOGGER.error(
                "Chat rejected | game=%s | status=%d | reason=%s | "
                "chars=%d | bytes=%d | text=%r | response=%r",
                game_id,
                response.status_code,
                response.reason_phrase,
                len(text),
                len(text.encode("utf-8")),
                text,
                response_body,
            )
            raise httpx.HTTPStatusError(
                (
                    f"Chat request failed with HTTP {response.status_code} "
                    f"{response.reason_phrase}; response={response_body!r}; "
                    f"chars={len(text)}; bytes={len(text.encode('utf-8'))}; "
                    f"text={text!r}"
                ),
                request=response.request,
                response=response,
            )

        LOGGER.info(
            "Chat accepted | game=%s | status=%d | chars=%d",
            game_id,
            response.status_code,
            len(text),
        )
