"""
Scrabble game runner. Run with:  streamlit run app.py
"""

import time

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from scrabble.game_state import GameState, Player, Phase, advance_to_next_player, ALL_TILES_BONUS_POINTS
from scrabble.board_reader import read_board_from_image, merge_with_history, build_score_baseline
from scrabble.board_display import board_to_display_df, parse_display_df, UNRESOLVED_BLANK_GLYPH
from scrabble.scorer import calculate_turn_score, format_breakdown
from scrabble.sound import play_timer_sound, SOUND_OPTIONS
from scrabble.persistence import save_game, load_game, autosave_exists, delete_autosave

st.set_page_config(page_title="Scrabble Scorer", layout="centered")


def _persist(game: GameState) -> None:
    """Write the current game to disk so a reload can resume it."""
    save_game(game)


# ---------------------------------------------------------------------------
# Session bootstrap
# ---------------------------------------------------------------------------
if "game" not in st.session_state:
    st.session_state.game = None

game: GameState | None = st.session_state.game


# ---------------------------------------------------------------------------
# Always-visible sidebar: scoreboard + top words + turn history + end game
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


# ---------------------------------------------------------------------------
# SETUP
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

    n = st.number_input("Number of players", min_value=2, max_value=4, value=2, step=1)
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
    sound_repeat_interval = 3
    if sound_repeat:
        sound_repeat_interval = st.number_input(
            "Repeat every how many seconds", min_value=2, value=3, step=1
        )

    if st.button("Start game", type="primary"):
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
# TURN START
# ---------------------------------------------------------------------------
def screen_turn_start(game: GameState):
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
# TIMER RUNNING (soft reminder - never forces the phase change)
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
        st.error(f"Time's up! ({mins:02d}:{secs:02d} over) - finish whenever you're ready.")

        if game.sound_choice != "none":
            if not game.sound_repeat:
                if overtime == 0:
                    play_timer_sound(game.sound_choice, nonce="once")
            else:
                interval = max(1, game.sound_repeat_interval_sec)
                if overtime % interval == 0:
                    play_timer_sound(game.sound_choice, nonce=str(overtime))

    if st.button("End turn / take photo", type="primary", use_container_width=True):
        game.phase = Phase.CAPTURE_PHOTO
        game.photo_attempt += 1
        _persist(game)
        st.rerun()


# ---------------------------------------------------------------------------
# CAPTURE PHOTO
# ---------------------------------------------------------------------------
def screen_capture_photo(game: GameState):
    st.title("Photograph the board")
    photo = st.camera_input(
        "Take a picture of the current board",
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
# CONFIRM BOARD (editable grid; blanks resolved here too; retake option)
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
        game.phase = Phase.CAPTURE_PHOTO
        game.photo_attempt += 1
        _persist(game)
        st.rerun()


# ---------------------------------------------------------------------------
# SCORING DONE
# ---------------------------------------------------------------------------
def screen_scoring_done(game: GameState):
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
# GAME OVER
# ---------------------------------------------------------------------------
def screen_game_over(game: GameState):
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
# Router
# ---------------------------------------------------------------------------
if game is None:
    screen_setup()
else:
    render_sidebar(game)
    {
        Phase.TURN_START: screen_turn_start,
        Phase.TIMER_RUNNING: screen_timer_running,
        Phase.CAPTURE_PHOTO: screen_capture_photo,
        Phase.CONFIRM_BOARD: screen_confirm_board,
        Phase.SCORING_DONE: screen_scoring_done,
        Phase.GAME_OVER: screen_game_over,
    }[game.phase](game)
