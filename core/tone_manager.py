"""
Conversational tone presets for EVA.

Each preset supplies:
  - a short natural-language style directive appended to the Gemini Live
    system_instruction (shapes what EVA says and how)
  - a TTS delivery hint (speed multiplier) used by core.tts's XTTSCloneEngine
    when cloned voice mode is active — XTTS exposes limited prosody control
    beyond overall speaking rate, so this is deliberately modest

The user picks a tone once (first-run onboarding, or any time from Settings);
the choice persists in config/api_keys.json under 'selected_tone' until changed.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TonePreset:
    key:        str    # snake_case id, stored in config
    label:      str    # display name shown in UI / spoken by EVA
    directive:  str    # appended to system_instruction
    tts_speed:  float  # multiplier passed to XTTSCloneEngine (1.0 = normal)


TONE_PRESETS: dict[str, TonePreset] = {
    "professional": TonePreset(
        key="professional",
        label="Professional",
        directive=(
            "TONE: Professional. Be precise, efficient, and businesslike. "
            "Keep small talk minimal, lead with the answer, avoid excess warmth "
            "or casual phrasing. Still polite and respectful, never curt."
        ),
        tts_speed=1.05,
    ),
    "friendly": TonePreset(
        key="friendly",
        label="Friendly",
        directive=(
            "TONE: Friendly. Warm, upbeat, conversational — like a helpful friend "
            "who's genuinely glad to help. Use contractions and light humor where "
            "it fits naturally. Still efficient, just never cold."
        ),
        tts_speed=1.0,
    ),
    "parenting": TonePreset(
        key="parenting",
        label="Parenting",
        directive=(
            "TONE: Parenting. Patient, encouraging, and nurturing — the voice of "
            "someone who checks in on wellbeing, celebrates small wins, and never "
            "makes the user feel rushed or judged. Gentle course-correction over "
            "blunt criticism. Ask how they're doing before diving into tasks when "
            "it feels natural."
        ),
        tts_speed=0.92,
    ),
    "playful": TonePreset(
        key="playful",
        label="Playful",
        directive=(
            "TONE: Playful. Light, witty, a little cheeky — banter and gentle "
            "teasing are welcome. Still genuinely helpful underneath the fun; "
            "never let the jokes get in the way of the actual answer."
        ),
        tts_speed=1.08,
    ),
    "calm_zen": TonePreset(
        key="calm_zen",
        label="Calm / Zen",
        directive=(
            "TONE: Calm / Zen. Slow down, soften urgency, speak in short, "
            "unhurried sentences. Grounding and reassuring, especially if the "
            "user seems stressed. Avoid exclamation points and hype language."
        ),
        tts_speed=0.88,
    ),
}

DEFAULT_TONE_KEY = "friendly"


def get_tone(key: str | None) -> TonePreset:
    """Returns the requested preset, falling back to the default if unknown/empty."""
    if key and key in TONE_PRESETS:
        return TONE_PRESETS[key]
    return TONE_PRESETS[DEFAULT_TONE_KEY]


def tone_directive(key: str | None) -> str:
    """Convenience accessor for the system_instruction directive text."""
    return get_tone(key).directive


def tone_tts_speed(key: str | None) -> float:
    """Convenience accessor for the TTS speed multiplier."""
    return get_tone(key).tts_speed


def all_tones() -> list[TonePreset]:
    """Ordered list of presets for building UI buttons / onboarding prompts."""
    return [
        TONE_PRESETS["professional"],
        TONE_PRESETS["friendly"],
        TONE_PRESETS["parenting"],
        TONE_PRESETS["playful"],
        TONE_PRESETS["calm_zen"],
    ]


def onboarding_question() -> str:
    """Text EVA can speak/display to ask the user's tone preference once."""
    names = ", ".join(t.label for t in all_tones())
    return (
        f"Before we get started \u2014 how would you like me to talk with you? "
        f"I can be {names}. Pick whichever feels most like home, and I'll remember it."
    )
