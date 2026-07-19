"""
Converts between the internal board representation (letter codes like
"A", "SCH", or the raw extraction sentinel "STAR") and what the player
sees/types in the confirm-board grid.

Blank tiles have NO special representation once resolved: the player
types the plain Cyrillic letter, and from that point on the square is
indistinguishable from a normal tile of that letter -- full point
value, no memory anywhere that it was ever a blank. A freshly-detected,
not-yet-resolved blank tile shows as a "*" (star) glyph until the
player types the letter it's standing in for.
"""

import numpy as np
import pandas as pd

from scrabble.letters_data import LETTERS

# Reverse lookup: Cyrillic letter -> internal code, e.g. "А" -> "A", "Щ" -> "SCH"
CYRILLIC_TO_CODE = {info["letter"]: code for code, info in LETTERS.items()}

UNRESOLVED_BLANK_GLYPH = "\u2605"  # shown for a detected-but-unresolved blank tile


def cell_to_display(code: str) -> str:
    """Internal letter code -> what's shown in the editable grid."""
    if code == "":
        return ""
    if code == "STAR":
        return UNRESOLVED_BLANK_GLYPH
    return LETTERS[code]["letter"]


def board_to_display_df(board: np.ndarray) -> pd.DataFrame:
    """Whole-board convenience wrapper around cell_to_display()."""
    display = [[cell_to_display(board[r][c]) for c in range(15)] for r in range(15)]
    return pd.DataFrame(display)


class CellParseError(ValueError):
    """Raised for a single cell that can't be parsed; carries its position."""

    def __init__(self, row: int, col: int, message: str):
        self.row = row
        self.col = col
        super().__init__(f"row {row}, col {col}: {message}")


def parse_cell(text: str, row: int, col: int) -> str:
    """
    Parses one edited grid cell back into an internal letter code.
    Returns "" for an empty square. Raises CellParseError for anything
    invalid, including an unresolved "*" placeholder -- callers should
    collect these and block confirmation until there are none left.
    """
    text = text.strip()

    if text == "":
        return ""

    if text == UNRESOLVED_BLANK_GLYPH:
        raise CellParseError(row, col, "blank tile still needs a letter -- type the letter it stands in for")

    letter = text.upper()
    if letter not in CYRILLIC_TO_CODE:
        raise CellParseError(row, col, f"'{text}' isn't a recognized letter")

    return CYRILLIC_TO_CODE[letter]


def parse_display_df(df: pd.DataFrame) -> tuple[np.ndarray, list[CellParseError]]:
    """
    Parses the whole edited grid back to (board, errors).
    If errors is non-empty, the board returned is best-effort and the
    caller should show the errors and refuse to proceed rather than
    use it.
    """
    board = np.full((15, 15), "", dtype="<U4")
    errors: list[CellParseError] = []

    values = df.values
    for r in range(15):
        for c in range(15):
            try:
                board[r][c] = parse_cell(str(values[r][c]), r, c)
            except CellParseError as e:
                errors.append(e)

    return board, errors
