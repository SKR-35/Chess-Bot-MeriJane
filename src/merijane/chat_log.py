from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ChatRecord:
    timestamp: str
    game_id: str
    room: str
    username: str
    text: str
    source: str
    event_type: str


class GameChatLogger:
    """Append-only JSONL logger for one Lichess game."""

    def __init__(
        self,
        *,
        game_id: str,
        bot_username: str,
        base_dir: Path,
        enabled: bool = True,
    ) -> None:
        self.game_id = game_id
        self.bot_username = bot_username
        self.enabled = enabled
        self.game_dir = base_dir / game_id
        self.path = self.game_dir / "chat.jsonl"

        # Messages sent by MeriJane may be echoed back by the Lichess game
        # stream as chatLine events. Remember them so they are not logged twice.
        self._sent_fingerprints: set[tuple[str, str]] = set()

        if self.enabled:
            self.game_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _append(self, record: ChatRecord) -> None:
        if not self.enabled:
            return
        with self.path.open("a", encoding="utf-8") as handle:
            json.dump(
                asdict(record),
                handle,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            handle.write("\n")

    def log_generated(
        self,
        *,
        text: str,
        room: str = "player",
    ) -> None:
        fingerprint = (room, text)
        self._sent_fingerprints.add(fingerprint)
        self._append(
            ChatRecord(
                timestamp=self._now_iso(),
                game_id=self.game_id,
                room=room,
                username=self.bot_username,
                text=text,
                source="merijane_generated",
                event_type="chat_sent",
            )
        )

    def log_stream_event(self, event: dict[str, Any]) -> None:
        room = str(event.get("room", "player"))
        username = str(event.get("username", "unknown"))
        text = str(event.get("text", ""))

        if not text:
            return

        fingerprint = (room, text)
        is_own_echo = (
            username.lower() == self.bot_username.lower()
            and fingerprint in self._sent_fingerprints
        )
        if is_own_echo:
            self._sent_fingerprints.discard(fingerprint)
            return

        self._append(
            ChatRecord(
                timestamp=self._now_iso(),
                game_id=self.game_id,
                room=room,
                username=username,
                text=text,
                source="lichess_stream",
                event_type="chat_received",
            )
        )

    def log_system(
        self,
        *,
        event_type: str,
        text: str,
    ) -> None:
        self._append(
            ChatRecord(
                timestamp=self._now_iso(),
                game_id=self.game_id,
                room="system",
                username="system",
                text=text,
                source="merijane_runtime",
                event_type=event_type,
            )
        )
