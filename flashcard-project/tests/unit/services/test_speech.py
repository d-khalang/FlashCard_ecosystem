"""EdgeSpeechProvider with edge-tts itself faked: no test reaches the real service."""
import edge_tts
import pytest

from flashcard.services.speech import EdgeSpeechProvider


def _fake_communicate(monkeypatch, attempts: list):
    """Each call to Communicate plays the next entry: a list of audio chunks, or an error to raise."""
    calls = iter(attempts)

    class Fake:
        def __init__(self, text, voice):
            self.step = next(calls)

        async def stream(self):
            if isinstance(self.step, Exception):
                raise self.step
            yield {"type": "WordBoundary"}
            for data in self.step:
                yield {"type": "audio", "data": data}

    monkeypatch.setattr(edge_tts, "Communicate", Fake)


async def test_joins_the_audio_chunks(monkeypatch):
    _fake_communicate(monkeypatch, [[b"ab", b"cd"]])

    assert await EdgeSpeechProvider().synthesize("mare", "it-IT-ElsaNeural") == b"abcd"


async def test_tries_again_once_when_no_audio_comes(monkeypatch):
    _fake_communicate(monkeypatch, [edge_tts.exceptions.NoAudioReceived("none"), [b"ok"]])

    assert await EdgeSpeechProvider().synthesize("mare", "it-IT-ElsaNeural") == b"ok"


async def test_gives_up_after_the_second_try(monkeypatch):
    _fake_communicate(monkeypatch, [[], []])

    with pytest.raises(edge_tts.exceptions.NoAudioReceived):
        await EdgeSpeechProvider().synthesize("mare", "it-IT-ElsaNeural")


async def test_other_failures_are_not_retried(monkeypatch):
    _fake_communicate(monkeypatch, [ConnectionError("403")])

    with pytest.raises(ConnectionError):
        await EdgeSpeechProvider().synthesize("mare", "it-IT-ElsaNeural")
