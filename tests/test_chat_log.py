import json

from merijane.chat_log import GameChatLogger


def test_generated_message_and_echo_are_logged_once(tmp_path) -> None:
    logger = GameChatLogger(
        game_id="game123",
        bot_username="MeriJane34",
        base_dir=tmp_path,
        enabled=True,
    )

    text = "Hello. Good luck."
    logger.log_generated(text=text)
    logger.log_stream_event(
        {
            "type": "chatLine",
            "room": "player",
            "username": "MeriJane34",
            "text": text,
        }
    )

    rows = [
        json.loads(line)
        for line in logger.path.read_text(encoding="utf-8").splitlines()
    ]

    assert len(rows) == 1
    assert rows[0]["source"] == "merijane_generated"


def test_opponent_message_is_logged(tmp_path) -> None:
    logger = GameChatLogger(
        game_id="game456",
        bot_username="MeriJane34",
        base_dir=tmp_path,
        enabled=True,
    )

    logger.log_stream_event(
        {
            "type": "chatLine",
            "room": "player",
            "username": "Opponent",
            "text": "Nice move!",
        }
    )

    row = json.loads(
        logger.path.read_text(encoding="utf-8").strip()
    )
    assert row["username"] == "Opponent"
    assert row["text"] == "Nice move!"
    assert row["source"] == "lichess_stream"
