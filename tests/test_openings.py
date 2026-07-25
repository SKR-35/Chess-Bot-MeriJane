import chess

from merijane.openings import repertoire_bonus


def test_italian_bishop_move_gets_bonus() -> None:
    board = chess.Board()
    for uci in ["e2e4", "e7e5", "g1f3", "b8c6"]:
        board.push_uci(uci)

    assert repertoire_bonus(board, chess.Move.from_uci("f1c4")) > 0.9
