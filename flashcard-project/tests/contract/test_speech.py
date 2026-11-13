"""Every voice the bot can pick still speaks, through the bot's own edge-tts client."""
from __future__ import annotations

import pytest

from flashcard.services.speech import VOICES, EdgeSpeechProvider

SAMPLES = {"it": "andare", "en": "wander", "es": "caminar", "fr": "marcher"}
CASES = [(language, voice) for language, voices in VOICES.items() for voice in voices]


def _is_mp3(audio: bytes) -> bool:
    # An ID3 tag, or an MPEG audio frame header (11 sync bits).
    return audio[:3] == b"ID3" or (audio[0] == 0xFF and audio[1] & 0xE0 == 0xE0)


@pytest.mark.parametrize("language, voice", CASES, ids=[voice for _, voice in CASES])
async def test_the_voice_returns_mp3(language, voice):
    audio = await EdgeSpeechProvider().synthesize(SAMPLES.get(language, "hello"), voice)

    assert len(audio) > 1000, f"{voice} returned {len(audio)} bytes"
    assert _is_mp3(audio), f"{voice} did not return MP3"
