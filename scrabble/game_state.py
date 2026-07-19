"""
Core data model for the Scrabble game session.
Everything here lives inside st.session_state.game for the duration of the browser session,
and is also written to disk (see persistence.py) so a reload can resume the game.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
import numpy as np

ALL_TILES_BONUS_POINTS = 15


class Phase(Enum):
    SETUP = auto()
    TURN_START = auto()
    TIMER_RUNNING = auto()
    CAPTURE_PHOTO = auto()
    CONFIRM_BOARD = auto()   # editing AND blank-resolution both happen here
    SCORING_DONE = auto()
    GAME_OVER = auto()


@dataclass
class Player:
    name: str
    score: int = 0
    top_word: str = ""         # highest-scoring single word this player has played
    top_word_points: int = 0


@dataclass
class GameState:
    players: list[Player]
    current_idx: int
    turn_duration_sec: int
    phase: Phase = Phase.TURN_START

    # 15x15 grid of letter codes ("" = empty square, "A".."YA" = a tile,
    # codes up to 4 chars like "SCH"/"HARD", or the sentinel "STAR" for a
    # freshly-detected blank tile that hasn't been resolved into a letter
    # yet). Board convention: row 0 = top, row 14 = bottom, col 0 = left,
    # i.e. board[row][col]. This array should never contain "STAR" once a
    # turn has been confirmed -- once resolved, a blank tile's square
    # just holds the plain letter code, identical to a normal tile.
    board: np.ndarray = field(default_factory=lambda: np.full((15, 15), "", dtype="<U4"))

    # Scratch space while a turn is being processed
    pending_board: np.ndarray | None = None
    photo_attempt: int = 0  # bumped each time a fresh camera widget is needed
    turn_start_time: float | None = None  # absolute unix timestamp -- survives a reload correctly
    turn_number: int = 0
    last_turn_points: int = 0
    last_turn_breakdown: str = ""

    # One entry per completed turn (including skipped ones), in order played.
    # Each entry: {"turn_number": int, "player_name": str, "word_points": int,
    #              "bonus_points": int, "points": int (word_points+bonus_points),
    #              "words": [{"word": str, "points": int}, ...], "skipped": bool}
    turn_history: list[dict] = field(default_factory=list)

    # How many tiles a full rack holds -- placing exactly this many new
    # tiles in one turn earns the ALL_TILES_BONUS_POINTS bonus.
    rack_size: int = 7

    # Timer sound settings, chosen once at setup
    sound_choice: str = "alarm"          # "none" / "beep" / "chime" / "alarm"
    sound_repeat: bool = True
    sound_repeat_interval_sec: int = 3

    def current_player(self) -> Player:
        return self.players[self.current_idx]


def advance_to_next_player(game: GameState) -> None:
    """Move to the next player and reset per-turn scratch state."""
    game.current_idx = (game.current_idx + 1) % len(game.players)
    game.turn_number += 1
    game.turn_start_time = None
    game.pending_board = None
    game.photo_attempt = 0
    game.phase = Phase.TURN_START
