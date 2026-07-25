from merijane.mood import MoodEngine


def test_pressure_can_raise_anxiety() -> None:
    mood = MoodEngine(0.2, 0.6, panic_cap=0.18, recovery_rate=0.3, seed=2)
    before = mood.state.anxiety
    after = mood.update(
        time_pressure=1.0,
        position_complexity=1.0,
        eval_drop_pawns=1.5,
        is_ahead=False,
    )
    assert after.anxiety > before
