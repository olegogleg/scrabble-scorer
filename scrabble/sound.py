"""
Plays a short sound in the browser when the turn timer runs out.
Uses the Web Audio oscillator API to synthesize a tone -- no audio
files to bundle or host.

Caveat worth knowing: some mobile browsers (especially iOS Safari)
only allow audio to start after a direct user tap on that page, and
that permission can be somewhat unreliable inside embedded iframes
(which is how Streamlit renders custom HTML components). If the sound
doesn't play reliably on a particular phone, that's a browser autoplay
restriction, not a bug in this code -- tapping the "End turn" button
right when the reminder should fire is the most reliable trigger.
"""

import streamlit.components.v1 as components

SOUND_OPTIONS = {
    "none": "No sound",
    "beep": "Beep",
    "chime": "Chime",
    "alarm": "Alarm (fast triple beep)",
}


def play_timer_sound(choice: str, nonce: str) -> None:
    """
    Injects a tiny HTML component that plays the chosen sound once.
    `nonce` should be different every time you want the sound to
    actually re-trigger (e.g. the current integer second of overtime) --
    if the injected HTML is byte-for-byte identical to the previous
    call, the browser may not re-run the script.
    """
    if choice == "none" or choice not in SOUND_OPTIONS:
        return

    html = f"""
    <script>
    (function() {{
      try {{
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        function beep(freq, duration, delay) {{
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
        const sound = "{choice}";
        if (sound === "beep") {{
          beep(880, 0.4, 0);
        }} else if (sound === "chime") {{
          beep(660, 0.22, 0);
          beep(880, 0.28, 0.22);
        }} else if (sound === "alarm") {{
          beep(1000, 0.12, 0);
          beep(1000, 0.12, 0.2);
          beep(1000, 0.12, 0.4);
        }}
      }} catch (e) {{ /* audio blocked by the browser -- fail silently */ }}
    }})();
    </script>
    <!-- nonce: {nonce} -->
    """
    components.html(html, height=0)
