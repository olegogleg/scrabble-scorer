"""
Turn scoring: given the board before and after a turn, find the new
word(s) and score them, applying bonus squares.

There is no special "blank tile" concept here at all -- by the time a
board reaches this function, every occupied square (including a
resolved former-blank) just holds a normal letter code and scores at
that letter's full point value.
"""

from scrabble.letters_data import LETTERS, bonus_color


def calculate_turn_score(old_board, new_board) -> tuple[int, list[dict], int]:
    """
    Returns (total_points, word_records, tiles_placed) where:
      - word_records is a list of {"word": str, "points": int}, one per
        new word formed this turn, sorted highest-scoring first.
      - tiles_placed is the count of squares that are genuinely new this
        turn (old_board vs new_board diff). If old_board is a
        correction-excluding baseline (see build_score_baseline), this
        count correctly ignores corrections to previously-placed tiles --
        exactly what you want for an "used all N letters" bonus too.
    Use format_breakdown() to turn word_records into a display string.
    """
    new_letters = []
    for row in range(15):
        for column in range(15):
            if old_board[row][column] != new_board[row][column]:
                new_letters.append((row, column))

    words = {}

    def score_direction(start_row, start_col, dr, dc):
        # walk backwards to the start of the word
        r, c = start_row, start_col
        while 0 <= r < 15 and 0 <= c < 15 and new_board[r][c] != "":
            r -= dr
            c -= dc
        r += dr
        c += dc

        word, word_str, word_points, multiplier = [], "", 0, 1
        while 0 <= r < 15 and 0 <= c < 15 and new_board[r][c] != "":
            code = new_board[r][c]
            word.append((r, c))
            word_str += LETTERS[code]["letter"]

            c_multiplier = 1
            c_points = LETTERS[code]["points"]
            if (r, c) in new_letters:
                tile_color = bonus_color(r, c)
                if tile_color == "red":
                    multiplier = max(multiplier, 3)
                elif tile_color == "green":
                    multiplier = max(multiplier, 2)
                elif tile_color == "yellow":
                    c_multiplier = max(c_multiplier, 3)
                elif tile_color == "blue":
                    c_multiplier = max(c_multiplier, 2)

            word_points += c_points * c_multiplier
            r += dr
            c += dc

        word_points *= multiplier
        if len(word) > 1:
            t_word = tuple(word)
            if t_word not in words:
                words[t_word] = {"string": word_str, "points": word_points}

    for row, column in new_letters:
        score_direction(row, column, 1, 0)  # vertical word through this tile
        score_direction(row, column, 0, 1)  # horizontal word through this tile

    word_records = [{"word": w["string"], "points": w["points"]} for w in words.values()]
    word_records.sort(key=lambda w: -w["points"])
    total_points = sum(w["points"] for w in word_records)

    return total_points, word_records, len(new_letters)


def format_breakdown(word_records: list[dict]) -> str:
    """Human-readable one-liner for a turn's word_records."""
    if not word_records:
        return "No new word detected -- did the board photo capture correctly?"
    return ", ".join(f'{w["word"]} ({w["points"]})' for w in word_records)
