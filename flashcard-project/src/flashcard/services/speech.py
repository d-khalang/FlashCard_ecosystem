"""
Text to speech. `SpeechProvider` is what the app layer depends on; `EdgeSpeechProvider` is the
current one. edge-tts is an unofficial client of the Edge browser's read-aloud service, so it has no
SLA and callers must treat every failure as normal. Its voices are Microsoft's neural voices, so a
move to Azure Speech should mostly be a new provider class with this same voice table.
"""
import asyncio
import random
from typing import Protocol

import edge_tts

# Parallel requests per process: everything leaves from one IP, and bursts risk being blocked.
MAX_PARALLEL_REQUESTS = 3

# Every language in LANGUAGE_DATA. A clip uses one of its language's voices, at random.
VOICES: dict[str, tuple[str, ...]] = {
    "it": ("it-IT-ElsaNeural", "it-IT-IsabellaNeural", "it-IT-GiuseppeMultilingualNeural"),
    "en": ("en-US-JennyNeural", "en-US-GuyNeural", "en-GB-SoniaNeural"),
    "es": ("es-ES-ElviraNeural", "es-ES-AlvaroNeural"),
    "fr": ("fr-FR-DeniseNeural", "fr-FR-HenriNeural"),
    "de": ("de-DE-KatjaNeural", "de-DE-ConradNeural"),
    "pt": ("pt-BR-FranciscaNeural", "pt-BR-AntonioNeural"),
    "ru": ("ru-RU-SvetlanaNeural", "ru-RU-DmitryNeural"),
    "zh": ("zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural"),
    "ja": ("ja-JP-NanamiNeural", "ja-JP-KeitaNeural"),
    "ko": ("ko-KR-SunHiNeural", "ko-KR-InJoonNeural"),
    "ar": ("ar-SA-ZariyahNeural", "ar-SA-HamedNeural"),
    "hi": ("hi-IN-SwaraNeural", "hi-IN-MadhurNeural"),
    "fa": ("fa-IR-DilaraNeural", "fa-IR-FaridNeural"),
    "tr": ("tr-TR-EmelNeural", "tr-TR-AhmetNeural"),
    "nl": ("nl-NL-ColetteNeural", "nl-NL-MaartenNeural"),
    "pl": ("pl-PL-ZofiaNeural", "pl-PL-MarekNeural"),
    "vi": ("vi-VN-HoaiMyNeural", "vi-VN-NamMinhNeural"),
    "id": ("id-ID-GadisNeural", "id-ID-ArdiNeural"),
    "sv": ("sv-SE-SofieNeural", "sv-SE-MattiasNeural"),
}


def random_voice(language_code: str) -> str:
    """One of the voices of a language in VOICES."""
    return random.choice(VOICES[language_code])


class SpeechProvider(Protocol):
    async def synthesize(self, text: str, voice: str) -> bytes:
        """The text as MP3. Raises on any failure."""
        ...


class EdgeSpeechProvider:
    def __init__(self) -> None:
        self._slots = asyncio.Semaphore(MAX_PARALLEL_REQUESTS)

    async def synthesize(self, text: str, voice: str) -> bytes:
        async with self._slots:
            try:
                return await self._once(text, voice)
            except edge_tts.exceptions.NoAudioReceived:
                # Seen now and then on text that works a moment later.
                return await self._once(text, voice)

    @staticmethod
    async def _once(text: str, voice: str) -> bytes:
        audio = bytearray()
        async for chunk in edge_tts.Communicate(text, voice).stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
        if not audio:
            raise edge_tts.exceptions.NoAudioReceived("Empty audio")
        return bytes(audio)
