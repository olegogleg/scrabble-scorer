"""
Saves and restores the entire GameState to/from a JSON file on disk.

Why this exists: Streamlit's st.session_state normally survives a
browser tab reload IF the same browser reconnects to the same
still-running server session -- which works for a quick reload in the
same tab most of the time, but is not guaranteed (long idle time,
browser/tab closed and reopened, or the server process itself
restarting all lose it). Writing a copy to disk after every
significant action means the Setup screen can offer a genuine
"Resume previous game" option regardless of why session_state was
lost, as long as the underlying disk still has the file (true for a
local `streamlit run`; NOT guaranteed if a cloud host redeploys/restarts
the whole app container, since that wipes its filesystem too).

turn_start_time is stored as an absolute unix timestamp, so resuming
mid-timer computes the correct remaining time automatically -- no
special-casing needed.
"""

import json
import os

import numpy as np

from scrabble.game_state import GameState, Player, Phase

AUTOSAVE_PATH = "scrabble_autosave.json"


def autosave_exists(path: str = AUTOSAVE_PATH) -> bool:
    return os.path.exists(path)


def delete_autosave(path: str = AUTOSAVE_PATH) -> None:
    if os.path.exists(path):
        os.remove(path)


def save_game(game: GameState, path: str = AUTOSAVE_PATH) -> None:
    data = {
        "players": [
            {"name": p.name, "score": p.score, "top_word": p.top_word, "top_word_points": p.top_word_points}
            for p in game.players
        ],
        "current_idx": game.current_idx,
        "turn_duration_sec": game.turn_duration_sec,
        "phase": game.phase.name,
        "board": game.board.tolist(),
        "pending_board": game.pending_board.tolist() if game.pending_board is not None else None,
        "photo_attempt": game.photo_attempt,
        "turn_start_time": game.turn_start_time,
        "turn_number": game.turn_number,
        "last_turn_points": game.last_turn_points,
        "last_turn_breakdown": game.last_turn_breakdown,
        "turn_history": game.turn_history,
        "rack_size": game.rack_size,
        "sound_choice": game.sound_choice,
        "sound_repeat": game.sound_repeat,
        "sound_repeat_interval_sec": game.sound_repeat_interval_sec,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def load_game(path: str = AUTOSAVE_PATH) -> GameState:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    players = [Player(**p) for p in data["players"]]
    board = np.array(data["board"], dtype="<U4")
    pending_board = (
        np.array(data["pending_board"], dtype="<U4") if data["pending_board"] is not None else None
    )

    saved_phase_name = data["phase"]
    if saved_phase_name == "CAPTURE_PHOTO":  # removed phase from an older version of this app
        saved_phase_name = "TIMER_RUNNING"

    return GameState(
        players=players,
        current_idx=data["current_idx"],
        turn_duration_sec=data["turn_duration_sec"],
        phase=Phase[saved_phase_name],
        board=board,
        pending_board=pending_board,
        photo_attempt=data["photo_attempt"],
        turn_start_time=data["turn_start_time"],
        turn_number=data["turn_number"],
        last_turn_points=data["last_turn_points"],
        last_turn_breakdown=data["last_turn_breakdown"],
        turn_history=data["turn_history"],
        rack_size=data.get("rack_size", 7),
        sound_choice=data["sound_choice"],
        sound_repeat=data["sound_repeat"],
        sound_repeat_interval_sec=data["sound_repeat_interval_sec"],
    )
