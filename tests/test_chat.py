from merijane.chat import ChatDirector


def test_battery_joke_is_sent_at_most_once() -> None:
    chat = ChatDirector(
        enabled=True,
        max_messages=3,
        battery_probability=1.0,
        seed=1,
    )
    first = chat.maybe_battery_joke(0.95, 0.88)
    second = chat.maybe_battery_joke(0.95, 0.88)

    assert first is not None
    assert second is None
