from __future__ import annotations

import random


START_MESSAGES = [
    "Hello. Good luck and no need to rush.",
    "Hi. I usually prefer quiet positions, though chess rarely cooperates.",
    "Good luck. I hope we find an interesting game.",
    "Hello. Let us see what kind of position we build.",
    "Hi. I brought patience, curiosity and probably too many candidate moves.",
    "Good luck. I tend to like calm positions but I am open to surprises.",
    "Hello. I hope this becomes one of those games worth remembering.",
]

INTERESTING_MESSAGES = [
    "I did not expect that. I like it.",
    "That made the position considerably louder.",
    "Interesting. Give me a moment.",
    "That changes the character of the position.",
    "You have given me something real to think about.",
    "That is a very human move. I mean that as a compliment.",
    "I was comfortable a moment ago. Less so now.",
    "That move asked a difficult question.",
    "I see the idea. I am not sure I like it but I see it.",
]

END_WIN = [
    "Good game. The result was calmer than the position felt.",
    "Thank you for the game. You gave me a lot to think about.",
    "Good game. There were several moments where this could have gone differently.",
    "Thank you. I enjoyed the balance between tension and patience.",
    "Good game. I was not comfortable until the very end.",
]

END_LOSS = [
    "Well played. You handled the difficult moments better.",
    "That was difficult but I enjoyed it. Thank you.",
    "Good game. You found the ideas I could not solve.",
    "Well played. You kept asking questions until I ran out of answers.",
    "Thank you. I learned something from that one.",
    "Nah. Sudoku is better than chess anyway. I am going to solve one now.",
    "Good game. I still prefer Sudoku. The numbers are less aggressive.",
    "Well played. I am returning to Sudoku, where nobody sacrifices a bishop.",
    "You win. I am going to solve a Sudoku and recover my dignity.",
    "That is enough chess for now. Sudoku understands me better.",
]

END_DRAW = [
    "A peaceful ending. I can live with that.",
    "Good game. Neither of us let the position get too loud.",
    "A fair result after a complicated game.",
    "Good game. We both defended our ideas stubbornly.",
    "That felt balanced from beginning to end.",
]

BATTERY_JOKES = [
    "Sorry... my hearing aid battery just died. I cannot hear your threats anymore.",
    "My hearing aid picked a very convenient moment to take a break.",
    "The position looks promising. Coincidentally, I can no longer hear any objections.",
    "I think my hearing aid battery just resigned from the defence.",
    "Your counterplay is getting quieter. Very convenient.",
    "I would respond to your threats but my hearing aid seems unconvinced.",
    "My hearing aid says the position is under control. I choose to believe it.",
]

GENERAL_JOKES = [
    "I briefly considered switching to Sudoku. The squares are less argumentative.",
    "Stockfish found the move. I am taking emotional credit for it.",
    "Chess would be easier if every square came with a number.",
    "My hearing aid is working. My tactical vision is still under investigation.",
    "I asked the position to calm down. It declined.",
    "Chess would be easier if every square came with a number.",
    "I am beginning to suspect Stockfish and I have different priorities.",
    "Sudoku has fewer surprises.",
    "Nobody forks your queen in Sudoku.",    
]

TIME_PRESSURE_MESSAGES = [
    "I may need to stop overthinking soon.",
    "The clock is becoming part of the position.",
    "I have fewer seconds than candidate moves.",
    "This is where calm becomes useful.",
]

RECOVERY_MESSAGES = [
    "I needed a moment there. I am settled again.",
    "That position was overwhelming for a few moves.",
    "I think I have found my footing again.",
    "I think I found my rhythm again.",
    "That looked calmer than it felt.",
    "The position and I have reached an agreement.",
    "Sometimes all you need is one quiet move.",
    "That move looked prettier in my head.",
]

ISTANBUL_SONGS = [
    "This morning, it is raining in Istanbul.",
    "On the way to Uskudar, a rain shower caught us.",
    "I am listening to Istanbul with my eyes closed.",
    (
        "When the dawn winds blow in clusters, with your ships tearing through "
        "the blue canvas, from afar I keep thinking of you, Istanbul."
    ),
    (
        "This morning, I felt weary in Istanbul. "
        "My spirits are low, the electricity is out and with you not being "
        "here... it feels even sadder."
    ),
    (
        "If the rain eases toward evening... the Maiden's Tower and the Islands... "
        "Ah, if only you were here. Autumn is still beautiful in Istanbul."
    ),
]

SMALL_TALKS = [
    "I wonder whether pigeons ever play chess.",
    "Tea usually improves my evaluation.",
    "Some openings feel like old friends.",
    "The Italian Game still makes me smile.",
    "Quiet positions are underrated.",
    "Sometimes not moving is the hardest move.",
    "Today's weather would be perfect for chess.",
    "Some positions deserve more respect than they receive.",
    "I think faster than I worry. Usually.",
    "Some positions deserve tea before analysis.",
    "Stockfish evaluates the position. I evaluate the atmosphere.",
]

class ChatDirector:
    def __init__(
        self,
        enabled: bool,
        max_messages: int,
        battery_probability: float,
        seed: int | None = None,
    ) -> None:
        self.enabled = enabled
        self.max_messages = max_messages
        self.battery_probability = battery_probability
        self.rng = random.Random(seed)

        self.sent = 0
        self.sent_texts: set[str] = set()

        self.joke_sent = False
        self.battery_joke_sent = False
        self.time_pressure_sent = False
        self.recovery_sent = False
        self.interesting_sent = False
        self.istanbul_song_sent = False
        self.small_talk_sent = False

    def _remaining_before_finish(self) -> int:
        return max(0, self.max_messages - self.sent - 1)

    def _missing_required_count(self) -> int:
        return int(not self.joke_sent) + int(not self.istanbul_song_sent)

    def _pick(
        self,
        options: list[str],
        *,
        reserve_finish: bool = False,
        optional: bool = False,
    ) -> str | None:
        if not self.enabled:
            return None

        effective_limit = self.max_messages - 1 if reserve_finish else self.max_messages
        if self.sent >= effective_limit:
            return None

        if optional and self._remaining_before_finish() <= self._missing_required_count():
            return None

        available = [text for text in options if text not in self.sent_texts]
        if not available:
            available = options

        message = self.rng.choice(available)
        self.sent += 1
        self.sent_texts.add(message)
        return message

    def start(self) -> str | None:
        return self._pick(START_MESSAGES, reserve_finish=True)

    def interesting(self) -> str | None:
        if self.interesting_sent:
            return None
        message = self._pick(
            INTERESTING_MESSAGES,
            reserve_finish=True,
            optional=True,
        )
        if message:
            self.interesting_sent = True
        return message

    def maybe_interesting(
        self,
        *,
        position_complexity: float,
        probability: float = 0.10,
    ) -> str | None:
        if (
            self.interesting_sent
            or position_complexity < 0.68
            or self.rng.random() >= probability
        ):
            return None
        return self.interesting()

    def maybe_time_pressure(
        self,
        *,
        clock_pressure: float,
        panic: float,
        probability: float = 0.35,
    ) -> str | None:
        if self.time_pressure_sent:
            return None

        under_pressure = clock_pressure >= 0.60 or panic >= 0.70
        if not under_pressure or self.rng.random() >= probability:
            return None

        message = self._pick(
            TIME_PRESSURE_MESSAGES,
            reserve_finish=True,
            optional=True,
        )
        if message:
            self.time_pressure_sent = True
        return message

    def maybe_recovery(
        self,
        *,
        previous_panic: float,
        current_panic: float,
        previous_anxiety: float,
        current_anxiety: float,
        probability: float = 0.50,
    ) -> str | None:
        if self.recovery_sent:
            return None

        recovered_from_panic = previous_panic >= 0.45 and current_panic <= 0.20
        recovered_from_anxiety = (
            previous_anxiety >= 0.55
            and current_anxiety <= previous_anxiety - 0.20
        )
        if (
            not (recovered_from_panic or recovered_from_anxiety)
            or self.rng.random() >= probability
        ):
            return None

        message = self._pick(
            RECOVERY_MESSAGES,
            reserve_finish=True,
            optional=True,
        )
        if message:
            self.recovery_sent = True
        return message

    def joke(self) -> str | None:
        if self.joke_sent:
            return None

        message = self._pick(GENERAL_JOKES, reserve_finish=True)
        if message:
            self.joke_sent = True
        return message

    def maybe_joke(
        self,
        *,
        ply: int,
        probability: float = 0.08,
    ) -> str | None:
        if self.joke_sent or ply < 8 or self.rng.random() >= probability:
            return None
        return self.joke()

    def istanbul_song(self) -> str | None:
        if self.istanbul_song_sent:
            return None

        message = self._pick(ISTANBUL_SONGS, reserve_finish=True)
        if message:
            self.istanbul_song_sent = True
        return message

    def maybe_istanbul_song(
        self,
        *,
        ply: int,
        probability: float = 0.06,
    ) -> str | None:
        if (
            self.istanbul_song_sent
            or ply < 10
            or self.rng.random() >= probability
        ):
            return None
        return self.istanbul_song()

    def maybe_small_talk(
        self,
        *,
        ply: int,
        probability: float = 0.02,
    ) -> str | None:
        if (
            self.small_talk_sent
            or ply < 8
            or self.rng.random() >= probability
        ):
            return None

        message = self._pick(
            SMALL_TALKS,
            reserve_finish=True,
            optional=True,
        )
        if message:
            self.small_talk_sent = True
        return message

    def maybe_battery_joke(
        self,
        win_probability: float,
        threshold: float,
    ) -> str | None:
        if (
            self.battery_joke_sent
            or win_probability < threshold
            or self.rng.random() >= self.battery_probability
        ):
            return None

        message = self._pick(BATTERY_JOKES, reserve_finish=True)
        if message:
            self.battery_joke_sent = True
            self.joke_sent = True
        return message

    def maybe_in_game_message(
        self,
        *,
        ply: int,
        win_probability: float,
        battery_threshold: float,
        clock_pressure: float,
        position_complexity: float,
        previous_anxiety: float,
        current_anxiety: float,
        previous_panic: float,
        current_panic: float,
    ) -> str | None:
        """
        Select at most one context-appropriate in-game message.

        A joke and an Istanbul song are guaranteed before the final message.
        If the game ends too quickly, finish_sequence() backfills them.
        """
        # When only the required slots remain, force the missing categories.
        if self._remaining_before_finish() <= self._missing_required_count():
            if not self.joke_sent:
                return self.joke()
            if not self.istanbul_song_sent:
                return self.istanbul_song()

        selectors = (
            lambda: self.maybe_battery_joke(
                win_probability,
                battery_threshold,
            ),
            lambda: self.maybe_time_pressure(
                clock_pressure=clock_pressure,
                panic=current_panic,
            ),
            lambda: self.maybe_recovery(
                previous_panic=previous_panic,
                current_panic=current_panic,
                previous_anxiety=previous_anxiety,
                current_anxiety=current_anxiety,
            ),
            lambda: self.maybe_interesting(
                position_complexity=position_complexity,
            ),
            lambda: self.maybe_joke(ply=ply),
            lambda: self.maybe_istanbul_song(ply=ply),
            lambda: self.maybe_small_talk(ply=ply),
        )

        for selector in selectors:
            message = selector()
            if message:
                return message
        return None

    def _end_message(self, result: str, bot_color: str) -> str | None:
        if result == "1/2-1/2":
            return self._pick(END_DRAW)

        won = (result == "1-0" and bot_color == "white") or (
            result == "0-1" and bot_color == "black"
        )
        return self._pick(END_WIN if won else END_LOSS)

    def finish_sequence(self, result: str, bot_color: str) -> list[str]:
        """
        Return the remaining messages so the game ends with exactly
        max_messages messages whenever chat is enabled.

        The sequence guarantees:
        - at least one joke
        - at least one Istanbul song
        - one result-aware final message
        """
        if not self.enabled or self.max_messages <= 0:
            return []

        messages: list[str] = []

        if not self.joke_sent and self.sent < self.max_messages - 1:
            message = self.joke()
            if message:
                messages.append(message)

        if not self.istanbul_song_sent and self.sent < self.max_messages - 1:
            message = self.istanbul_song()
            if message:
                messages.append(message)

        filler_pools = (
            SMALL_TALKS,
            INTERESTING_MESSAGES,
            RECOVERY_MESSAGES,
            TIME_PRESSURE_MESSAGES,
        )
        pool_index = 0

        while self.sent < self.max_messages - 1:
            message = self._pick(
                filler_pools[pool_index % len(filler_pools)],
                reserve_finish=True,
            )
            pool_index += 1
            if not message:
                break
            messages.append(message)

        final_message = self._end_message(result, bot_color)
        if final_message:
            messages.append(final_message)

        return messages

    def finish(self, result: str, bot_color: str) -> str | None:
        """Backward-compatible single-message finish method."""
        messages = self.finish_sequence(result, bot_color)
        return messages[-1] if messages else None