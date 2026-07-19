"""
Plays a sound in the browser when the turn timer runs out.

WHY THIS ISN'T THE SIMPLE VERSION: the first version of this file
re-injected a fresh HTML component every second via components.html(),
triggering the browser's audio API from Python-driven reruns. That
worked on some browsers but never worked on Safari (desktop or iOS),
because Safari only allows audio to start as the DIRECT result of a
real tap -- and a component re-injected by a background timer never
counts as one, no matter how it's triggered.

This version fixes that by rendering ONE persistent HTML/JS widget for
the whole turn (not re-created every second), with a visible "Enable
timer sound" button. Tapping it once creates and unlocks the browser's
AudioContext -- a genuine user gesture, which Safari accepts. From then
on, that same already-unlocked AudioContext can be used again by a
plain JavaScript timer running inside the SAME widget, entirely
independent of Streamlit's Python-side reruns. That's the standard,
supported way to get repeating audio past Safari's restrictions.

For the iframe (and its unlocked AudioContext) to survive across
Streamlit's autorefresh-driven reruns, the HTML given to
components.html() must be byte-identical between reruns of the same
turn -- Streamlit only recreates the iframe when its content changes.
That's why the countdown math happens in JavaScript using an absolute
end timestamp, not in Python re-rendering the widget with a
recalculated "seconds remaining" each tick.
"""

import streamlit.components.v1 as components

SOUND_OPTIONS = {
    "none": "No sound",
    "beep": "Beep",
    "chime": "Chime",
    "alarm": "Alarm (fast triple beep)",
}


def render_timer_sound_widget(
    target_end_timestamp: float,
    sound_choice: str,
    repeat: bool,
    repeat_interval_sec: int,
) -> None:
    """
    Renders the persistent sound widget for the current turn. Call this
    on every rerun of the TIMER_RUNNING screen -- as long as the
    arguments don't change during the turn (they shouldn't), Streamlit
    will reuse the same iframe instead of recreating it, so the
    unlocked AudioContext and the JS-side timer both survive.
    """
    if sound_choice == "none" or sound_choice not in SOUND_OPTIONS:
        return

    target_ms = int(target_end_timestamp * 1000)
    repeat_js = "true" if repeat else "false"
    interval_ms = max(1, int(repeat_interval_sec)) * 1000

    html = f"""
    <div style="font-family: sans-serif; font-size: 13px;">
      <button id="enable-sound-btn" style="padding:6px 12px; cursor:pointer;">
        Tap to enable timer sound
      </button>
      <span id="sound-status" style="margin-left:8px; color:#888;"></span>
    </div>
    <script>
    (function() {{
      const targetTime = {target_ms};
      const soundChoice = "{sound_choice}";
      const repeat = {repeat_js};
      const intervalMs = {interval_ms};

      let ctx = null;
      let lastFiredKey = null;

      function beep(freq, duration, delay) {{
        if (!ctx) return;
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.frequency.value = freq;
        osc.connect(gain);
        gain.connect(ctx.destination);
        gain.gain.setValueAtTime(0.0001, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.3, ctx.currentTime + delay + 0.01);
        gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + delay + duration);
        osc.start(ctx.currentTime + delay);
        osc.stop(ctx.currentTime + delay + duration + 0.02);
      }}

      function playSound() {{
        if (soundChoice === "beep") {{
          beep(880, 0.4, 0);
        }} else if (soundChoice === "chime") {{
          beep(660, 0.22, 0);
          beep(880, 0.28, 0.22);
        }} else if (soundChoice === "alarm") {{
          beep(1000, 0.12, 0);
          beep(1000, 0.12, 0.2);
          beep(1000, 0.12, 0.4);
        }}
      }}

      const btn = document.getElementById('enable-sound-btn');
      btn.addEventListener('click', function() {{
        try {{
          ctx = new (window.AudioContext || window.webkitAudioContext)();
          beep(1, 0.01, 0);  // inaudible blip, unlocks audio on this real tap
          document.getElementById('sound-status').textContent = 'Sound enabled';
          btn.style.display = 'none';
        }} catch (e) {{
          document.getElementById('sound-status').textContent = 'Audio unavailable on this browser';
        }}
      }});

      setInterval(function() {{
        if (!ctx) return;  // not unlocked yet -- wait for the tap
        const now = Date.now();
        if (now < targetTime) return;
        const overtimeSec = Math.floor((now - targetTime) / 1000);

        if (!repeat) {{
          if (overtimeSec === 0 && lastFiredKey !== 'once') {{
            playSound();
            lastFiredKey = 'once';
          }}
          return;
        }}

        const intervalSec = Math.max(1, Math.round(intervalMs / 1000));
        const windowKey = Math.floor(overtimeSec / intervalSec);
        if (overtimeSec % intervalSec === 0 && lastFiredKey !== windowKey) {{
          playSound();
          lastFiredKey = windowKey;
        }}
      }}, 500);
    }})();
    </script>
    """
    components.html(html, height=40)
