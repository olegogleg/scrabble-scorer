"""
Glue between Streamlit's st.camera_input() and your board_extraction logic,
plus two functions that reconcile "the board before this turn" with
"the board after this turn's photo and edits" -- used at two different
points for two different reasons.
"""

import cv2 as cv
import numpy as np

from scrabble.board_extraction import extract_board_from_image, DEFAULT_TEMPLATES_DIR


def read_board_from_image(photo) -> np.ndarray:
    """
    Runs OCR on the ENTIRE board in the photo. app.py only trusts this
    result for squares that were empty on the previously confirmed
    board -- see merge_with_history().
    """
    file_bytes = np.frombuffer(photo.getvalue(), dtype=np.uint8)
    img = cv.imdecode(file_bytes, cv.IMREAD_COLOR)
    return extract_board_from_image(img, DEFAULT_TEMPLATES_DIR)


def merge_with_history(old_board: np.ndarray, freshly_extracted: np.ndarray) -> np.ndarray:
    """
    Used right after taking a photo, BEFORE the player edits anything.
    Keeps old_board's value for every square that was already occupied
    (so a confirmed tile never gets silently re-guessed by OCR), and
    only takes freshly_extracted's value for squares that were empty
    (the tiles placed this turn).
    """
    merged = old_board.copy()
    newly_empty = old_board == ""
    merged[newly_empty] = freshly_extracted[newly_empty]
    return merged


def build_score_baseline(old_board: np.ndarray, final_board: np.ndarray) -> np.ndarray:
    """
    Used right before scoring, AFTER the player has confirmed their
    edits. Squares that were already occupied before this turn should
    never be scored as "new" even if the player corrected a misread
    letter on one of them -- that correction is a history fix, not a
    move. This builds the board that calculate_turn_score() should
    treat as "before this turn": old_board's occupied squares get
    final_board's (corrected) value baked in, so the before/after diff
    shows no change there. Squares that were empty before stay empty
    here, so genuinely new tiles (including resolved blanks) still show
    up correctly as new in the diff.
    """
    baseline = old_board.copy()
    was_occupied = old_board != ""
    baseline[was_occupied] = final_board[was_occupied]
    return baseline
