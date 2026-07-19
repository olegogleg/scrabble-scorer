"""
Scrabble game runner. Run with:  streamlit run app.py

Two devices can now share one game: open this same URL on both, pick
"Main screen" on one (timer, scoreboard, board confirmation, everything
except the camera) and "Camera only" on the other (just takes the photo
each turn). Both stay in sync via the same autosave file on disk --
whichever device made the most recent move, the other one picks it up
within a couple of seconds automatically.
"""

import time

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from scrabble.game_state import GameState, Player, Phase, advance_to_next_player, ALL_TILES_BONUS_POINTS
from scrabble.board_reader import read_board_from_image, merge_with_history, build_score_baseline
from scrabble.board_display import board_to_display_df, parse_display_df, UNRESOLVED_BLANK_GLYPH
from scrabble.scorer import calculate_turn_score, format_breakdown
from scrabble.sound import render_timer_sound_widget, SOUND_OPTIONS
from scrabble.persistence import save_game, load_game, autosave_exists, delete_autosave

st.set_page_config(page_title="Scrabble Scorer", layout="centered")

def _persist(game: GameState) -> None:
    """Write the current game to disk so the other device (and a reload) can pick it up."""
    save_game(game)


# ---------------------------------------------------------------------------
# Device role: chosen once per browser/device, kept in THIS session only
# (never written to the shared save file -- it's a property of the
# device, not of the game).
# ---------------------------------------------------------------------------
def screen_choose_role():
    st.title("Scrabble Scorer")
    st.write("How will you use this device?")
    c1, c2 = st.columns(2)
    if c1.button("Main screen", use_container_width=True, type="primary"):
        st.session_state.device_role = "control"
        st.rerun()
    if c2.button("Camera only", use_container_width=True):
        st.session_state.device_role = "camera"
        st.rerun()
    st.caption(
        "Main screen: timer, scoreboard, confirming the board, everything except "
        "the photo. Camera only: just takes the picture each turn -- use this on "
        "the phone if you're playing with two devices."
    )


def render_switch_role_button():
    if st.button("Switch this device's role"):
        st.session_state.device_role = None
        st.rerun()


# ---------------------------------------------------------------------------
# Session bootstrap + cross-device sync
# ---------------------------------------------------------------------------
if "device_role" not in st.session_state:
    st.session_state.device_role = None
if "game" not in st.session_state:
    st.session_state.game = None

game: GameState | None = st.session_state.game

# If we already have a local game in memory, check whether the OTHER
# device has moved things forward (different phase or turn number on
# disk) -- if so, adopt the disk copy. If nothing changed, keep using
# our own in-memory copy so we don't disturb any in-progress typing.
if game is not None and autosave_exists():
    disk_game = load_game()
    if (disk_game.turn_number, disk_game.phase.value) != (game.turn_number, game.phase.value):
        game = disk_game
        st.session_state.game = game


# ---------------------------------------------------------------------------
# Always-visible sidebar: scoreboard + top words + turn history + end game
# (control device only -- the camera device's screen stays minimal)
# ---------------------------------------------------------------------------
def render_sidebar(game: GameState) -> None:
    with st.sidebar:
        st.header("Scoreboard")
        rows = []
        for i, p in enumerate(game.players):
            marker = "\u2192 " if i == game.current_idx else ""
            top_word = f"{p.top_word} ({p.top_word_points})" if p.top_word else "\u2014"
            rows.append({"Player": f"{marker}{p.name}", "Score": p.score, "Top word": top_word})
        st.table(pd.DataFrame(rows).set_index("Player"))
        st.caption(f"Turn #{game.turn_number + 1}")

        with st.expander("Turn history"):
            if not game.turn_history:
                st.caption("No turns played yet.")
            else:
                history_rows = [
                    {
                        "Turn": h["turn_number"] + 1,
                        "Player": h["player_name"],
                        "Points": h["points"],
                        "Bonus": f"+{h['bonus_points']}" if h.get("bonus_points") else "",
                    }
                    for h in game.turn_history
                ]
                st.dataframe(pd.DataFrame(history_rows), use_container_width=True, hide_index=True)

                st.divider()
                st.caption("View words from a specific turn")
                labels = [f"Turn {h['turn_number'] + 1} \u2014 {h['player_name']}" for h in game.turn_history]
                selected = st.selectbox(
                    "Select a turn", options=range(len(labels)),
                    format_func=lambda i: labels[i], key="turn_history_select",
                )
                entry = game.turn_history[selected]
                if entry["skipped"]:
                    st.caption("Turn was skipped -- no words played.")
                elif not entry["words"]:
                    st.caption("No words recorded for this turn.")
                else:
                    for w in entry["words"]:
                        st.write(f"{w['word']} \u2014 {w['points']} pts")
                if entry.get("bonus_points"):
                    st.write(f"Bonus (used all {game.rack_size} letters) \u2014 +{entry['bonus_points']} pts")

        st.divider()
        if not st.session_state.get("confirm_end_game", False):
            if st.button("End game", use_container_width=True):
                st.session_state["confirm_end_game"] = True
                st.rerun()
        else:
            st.warning("End the game now? This can't be undone.")
            c1, c2 = st.columns(2)
            if c1.button("Yes, end it", type="primary", use_container_width=True):
                game.phase = Phase.GAME_OVER
                _persist(game)
                st.session_state["confirm_end_game"] = False
                st.rerun()
            if c2.button("Cancel", use_container_width=True):
                st.session_state["confirm_end_game"] = False
                st.rerun()

        st.divider()
        render_switch_role_button()


# ---------------------------------------------------------------------------
# SETUP (control device only)
# ---------------------------------------------------------------------------
def screen_setup():
    st.title("Scrabble Scorer")

    if autosave_exists():
        st.info("A previous game was found on this device.")
        c1, c2 = st.columns(2)
        if c1.button("Resume previous game", type="primary", use_container_width=True):
            st.session_state.game = load_game()
            st.rerun()
        if c2.button("Discard it and start fresh", use_container_width=True):
            delete_autosave()
            st.rerun()
        st.divider()

    st.subheader("Game setup")

    # Number of players lives OUTSIDE the form below so the name fields
    # update immediately as you change it, instead of waiting for a submit.
    n = st.number_input("Number of players", min_value=2, max_value=4, value=2, step=1)

    with st.form("setup_form"):
        names = []
        for i in range(n):
            names.append(st.text_input(f"Player {i + 1} name", value=f"Player {i + 1}", key=f"name_{i}"))

        starter = st.selectbox("Who goes first?", names)
        duration = st.number_input("Turn timer (seconds)", min_value=10, value=180, step=10)
        rack_size = st.number_input(
            f"Letters per turn (for the +{ALL_TILES_BONUS_POINTS}-point all-letters bonus)",
            min_value=2, max_value=12, value=7, step=1,
        )

        st.subheader("Timer sound")
        sound_choice = st.selectbox(
            "Sound when time is up",
            options=list(SOUND_OPTIONS.keys()),
            format_func=lambda k: SOUND_OPTIONS[k],
            index=list(SOUND_OPTIONS.keys()).index("alarm"),
        )
        sound_repeat = st.checkbox("Repeat the sound until I end the turn", value=True)
        sound_repeat_interval = st.number_input(
            "Repeat every how many seconds (if repeating)", min_value=2, value=3, step=1
        )

        submitted = st.form_submit_button("Start game", type="primary")

    if submitted:
        if len(set(names)) != len(names):
            st.error("Player names must be unique.")
            return
        new_game = GameState(
            players=[Player(name=nm) for nm in names],
            current_idx=names.index(starter),
            turn_duration_sec=int(duration),
            rack_size=int(rack_size),
            sound_choice=sound_choice,
            sound_repeat=sound_repeat,
            sound_repeat_interval_sec=int(sound_repeat_interval),
        )
        st.session_state.game = new_game
        _persist(new_game)
        st.rerun()


# ---------------------------------------------------------------------------
# TURN START (control device)
# ---------------------------------------------------------------------------
def screen_turn_start(game: GameState):
    st_autorefresh(interval=2000, key="turn_start_tick")
    player = game.current_player()
    st.title(f"{player.name}'s turn")
    st.caption(f"Turn timer: {game.turn_duration_sec}s (soft limit - it won't cut you off)")

    col1, col2 = st.columns(2)
    if col1.button("Start turn", type="primary", use_container_width=True):
        game.turn_start_time = time.time()
        game.phase = Phase.TIMER_RUNNING
        _persist(game)
        st.rerun()
    if col2.button("Skip turn (0 points)", use_container_width=True):
        game.turn_history.append({
            "turn_number": game.turn_number,
            "player_name": player.name,
            "word_points": 0,
            "bonus_points": 0,
            "points": 0,
            "words": [],
            "skipped": True,
        })
        advance_to_next_player(game)
        _persist(game)
        st.rerun()


# ---------------------------------------------------------------------------
# Shared: the uploader that ends a turn the moment a photo comes in.
# Used by both the control device's rich timer screen and the camera
# device's lean one.
# ---------------------------------------------------------------------------
def _render_end_turn_photo_widget(game: GameState) -> None:
    st.caption(
        "Taking or choosing a picture ends your turn automatically -- no separate button needed. "
        "Choose \"Take Photo\" to use your phone's actual camera app (zoom, flash, etc.) "
        "instead of an in-page preview."
    )
    photo = st.file_uploader(
        "Take or choose a picture of the board",
        type=["jpg", "jpeg", "png", "heic", "heif"],
        accept_multiple_files=False,
        key=f"camera_{game.turn_number}_{game.photo_attempt}",
    )

    if photo is not None:
        with st.spinner("Reading the board..."):
            fresh_board = read_board_from_image(photo)

        # Trust the previously confirmed board for squares that were
        # already occupied; only take fresh OCR for newly-placed tiles.
        game.pending_board = merge_with_history(game.board, fresh_board)
        game.phase = Phase.CONFIRM_BOARD
        _persist(game)
        st.rerun()


# ---------------------------------------------------------------------------
# TIMER RUNNING (control device; soft reminder - never forces the phase
# change on its own; uploading a photo is what ends the turn)
# ---------------------------------------------------------------------------
def screen_timer_running(game: GameState):
    st_autorefresh(interval=1000, key="timer_tick")

    player = game.current_player()
    st.title(f"{player.name}'s turn")

    elapsed = time.time() - game.turn_start_time
    remaining = game.turn_duration_sec - elapsed

    if remaining > 0:
        mins, secs = divmod(int(remaining), 60)
        st.metric("Time left", f"{mins:02d}:{secs:02d}")
    else:
        overtime = int(-remaining)
        mins, secs = divmod(overtime, 60)
        st.error(f"Time's up! ({mins:02d}:{secs:02d} over) - take your photo whenever you're ready.")

    target_end_timestamp = game.turn_start_time + game.turn_duration_sec
    render_timer_sound_widget(
        target_end_timestamp, game.sound_choice, game.sound_repeat, game.sound_repeat_interval_sec
    )

    st.divider()
    _render_end_turn_photo_widget(game)


# ---------------------------------------------------------------------------
# CONFIRM BOARD (control device; editable grid; blanks resolved here too;
# retake option)
# ---------------------------------------------------------------------------
def screen_confirm_board(game: GameState):
    st.title("Confirm the board")
    st.caption(
        f"Fix any misread letters if needed. A tile marked {UNRESOLVED_BLANK_GLYPH} was "
        "detected as a blank -- type the letter it's being used as. Once you type it, "
        "that tile counts as a normal letter of that kind from now on."
    )

    df = board_to_display_df(game.pending_board)
    edited = st.data_editor(df, key=f"board_editor_{game.turn_number}_{game.photo_attempt}", use_container_width=True)

    col1, col2 = st.columns(2)
    if col1.button("Confirm board", type="primary", use_container_width=True):
        final_board, errors = parse_display_df(edited)

        if errors:
            st.error(
                "Please fix these before continuing:\n"
                + "\n".join(f"- {e}" for e in errors)
            )
            return

        game.pending_board = final_board
        game.phase = Phase.SCORING_DONE
        _persist(game)
        st.rerun()

    if col2.button("Retake photo", use_container_width=True):
        game.pending_board = None
        game.phase = Phase.TIMER_RUNNING
        game.photo_attempt += 1
        _persist(game)
        st.rerun()


# ---------------------------------------------------------------------------
# SCORING DONE (control device)
# ---------------------------------------------------------------------------
def screen_scoring_done(game: GameState):
    st_autorefresh(interval=2000, key="scoring_done_tick")
    player = game.current_player()

    if "_scored" not in st.session_state:
        baseline = build_score_baseline(game.board, game.pending_board)
        word_points, word_records, tiles_placed = calculate_turn_score(baseline, game.pending_board)
        bonus_points = ALL_TILES_BONUS_POINTS if tiles_placed == game.rack_size else 0
        total_points = word_points + bonus_points

        game.last_turn_points = total_points
        game.last_turn_breakdown = format_breakdown(word_records)
        st.session_state["_scored"] = True
        st.session_state["_scored_words"] = word_records
        st.session_state["_scored_word_points"] = word_points
        st.session_state["_scored_bonus_points"] = bonus_points

    word_records = st.session_state.get("_scored_words", [])
    word_points = st.session_state.get("_scored_word_points", 0)
    bonus_points = st.session_state.get("_scored_bonus_points", 0)

    st.title("Turn result")
    st.success(f"{player.name} scored {game.last_turn_points} points")
    st.write(game.last_turn_breakdown)
    if bonus_points:
        st.info(f"Bonus! Used all {game.rack_size} letters this turn: +{bonus_points} points")

    if st.button("Next turn", type="primary"):
        player.score += game.last_turn_points
        game.board = game.pending_board  # saves both corrections and new tiles

        game.turn_history.append({
            "turn_number": game.turn_number,
            "player_name": player.name,
            "word_points": word_points,
            "bonus_points": bonus_points,
            "points": game.last_turn_points,
            "words": word_records,
            "skipped": False,
        })

        if word_records:
            best_this_turn = max(word_records, key=lambda w: w["points"])
            if best_this_turn["points"] > player.top_word_points:
                player.top_word = best_this_turn["word"]
                player.top_word_points = best_this_turn["points"]

        game.last_turn_breakdown = ""
        del st.session_state["_scored"]
        del st.session_state["_scored_words"]
        del st.session_state["_scored_word_points"]
        del st.session_state["_scored_bonus_points"]
        advance_to_next_player(game)
        _persist(game)
        st.rerun()


# ---------------------------------------------------------------------------
# GAME OVER (control device)
# ---------------------------------------------------------------------------
def screen_game_over(game: GameState):
    st_autorefresh(interval=2000, key="game_over_tick")
    st.title("Game over")

    max_score = max(p.score for p in game.players)
    winners = [p for p in game.players if p.score == max_score]

    if len(winners) == 1:
        st.success(f"{winners[0].name} wins with {max_score} points!")
    else:
        names = ", ".join(w.name for w in winners)
        st.success(f"It's a tie between {names} at {max_score} points each!")

    rows = [
        {
            "Player": p.name,
            "Score": p.score,
            "Top word": f"{p.top_word} ({p.top_word_points})" if p.top_word else "\u2014",
        }
        for p in sorted(game.players, key=lambda p: -p.score)
    ]
    st.table(pd.DataFrame(rows).set_index("Player"))

    if st.button("Start a new game", type="primary"):
        delete_autosave()
        st.session_state.game = None
        st.rerun()


# ---------------------------------------------------------------------------
# CAMERA-DEVICE waiting screen (shown whenever it's NOT the camera's turn
# to act -- i.e. every phase except TIMER_RUNNING)
# ---------------------------------------------------------------------------
def screen_camera_waiting(game: GameState | None):
    st.title("Scrabble Camera")
    st_autorefresh(interval=1500, key="camera_wait_tick")

    if game is None:
        st.info("Waiting for a game to be started on the main screen...")
        render_switch_role_button()
        return

    player = game.current_player()
    if game.phase == Phase.TURN_START:
        st.info(f"Waiting for {player.name} to start their turn.")
    elif game.phase == Phase.CONFIRM_BOARD:
        st.info("Photo received -- being confirmed on the main screen now.")
    elif game.phase == Phase.SCORING_DONE:
        st.info("Scoring this turn on the main screen.")
    elif game.phase == Phase.GAME_OVER:
        st.success("Game over! Check the main screen for the winner.")
    else:
        st.info("Waiting...")

    render_switch_role_button()


# ---------------------------------------------------------------------------
# CAMERA-DEVICE active screen -- shown during TIMER_RUNNING, since taking
# the photo (which ends the turn) is this device's job. Lean version of
# the control device's timer screen: just the countdown and the uploader.
# ---------------------------------------------------------------------------
def screen_camera_turn_active(game: GameState):
    st_autorefresh(interval=1000, key="camera_timer_tick")

    player = game.current_player()
    st.title(f"{player.name}'s turn")

    elapsed = time.time() - game.turn_start_time
    remaining = game.turn_duration_sec - elapsed
    if remaining > 0:
        mins, secs = divmod(int(remaining), 60)
        st.metric("Time left", f"{mins:02d}:{secs:02d}")
    else:
        overtime = int(-remaining)
        mins, secs = divmod(overtime, 60)
        st.warning(f"Time's up! ({mins:02d}:{secs:02d} over) - take the photo whenever ready.")

    _render_end_turn_photo_widget(game)
    render_switch_role_button()


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
if st.session_state.device_role is None:
    screen_choose_role()
elif st.session_state.device_role == "control":
    if game is None:
        screen_setup()
    else:
        render_sidebar(game)
        {
            Phase.TURN_START: screen_turn_start,
            Phase.TIMER_RUNNING: screen_timer_running,
            Phase.CONFIRM_BOARD: screen_confirm_board,
            Phase.SCORING_DONE: screen_scoring_done,
            Phase.GAME_OVER: screen_game_over,
        }[game.phase](game)
else:  # camera role
    if game is None:
        if autosave_exists():
            # A game may already be under way (started on the control
            # device) -- adopt it directly, no prompt needed here.
            st.session_state.game = load_game()
            st.rerun()
        else:
            screen_camera_waiting(None)
    elif game.phase == Phase.TIMER_RUNNING:
        screen_camera_turn_active(game)
    else:
        screen_camera_waiting(game)
