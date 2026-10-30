"""Speech-to-text behind one interface: Groq Whisper first, optional fallback (spec 13)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from codebuddy.config import Settings
from codebuddy.stt.normalize import VOCAB_PROMPT, normalize_transcript

log = logging.getLogger("codebuddy.stt")


class TranscriptionError(Exception):
    pass


@dataclass(frozen=True)
class Transcript:
    text: str
    provider: str


class Transcriber(Protocol):
    name: str

    async def transcribe(self, audio: bytes, filename: str) -> str: ...


class GroqTranscriber:
    """Groq's hosted Whisper. Batch API: one call per utterance. Reads GROQ_API_KEY."""

    name = "groq"

    def __init__(self, model: str, language: str | None, client=None):
        from groq import AsyncGroq

        self._client = client or AsyncGroq()
        self._model, self._language = model, language

    async def transcribe(self, audio: bytes, filename: str) -> str:
        result = await self._client.audio.transcriptions.create(
            model=self._model,
            file=(filename, audio),
            prompt=VOCAB_PROMPT,
            language=self._language,
        )
        return result.text


class OpenAITranscriber:
    """OpenAI transcription, used only as a fallback. Reads OPENAI_API_KEY."""

    name = "openai"

    def __init__(self, model: str, language: str | None, client=None):
        from openai import AsyncOpenAI

        self._client = client or AsyncOpenAI()
        self._model, self._language = model, language

    async def transcribe(self, audio: bytes, filename: str) -> str:
        result = await self._client.audio.transcriptions.create(
            model=self._model,
            file=(filename, audio),
            prompt=VOCAB_PROMPT,
            language=self._language,
        )
        return result.text


class SpeechToText:
    """Tries each transcriber in order and cleans up the text."""

    def __init__(self, transcribers: list[Transcriber]):
        if not transcribers:
            raise ValueError("at least one transcriber is required")
        self._transcribers = transcribers

    async def transcribe(self, audio: bytes, filename: str = "speech.wav") -> Transcript:
        errors: list[str] = []
        for t in self._transcribers:
            try:
                text = await t.transcribe(audio, filename)
            except Exception as exc:
                log.warning("transcriber %s failed: %s", t.name, exc)
                errors.append(f"{t.name}: {exc}")
                continue
            return Transcript(normalize_transcript(text), t.name)
        raise TranscriptionError("; ".join(errors))


def build_speech_to_text(settings: Settings) -> SpeechToText | None:
    """None when no provider is configured, so the API can answer 503 clearly."""
    import os

    transcribers: list[Transcriber] = []
    if os.getenv("GROQ_API_KEY"):
        transcribers.append(GroqTranscriber(settings.stt_model, settings.stt_language))
    if settings.stt_fallback_model and os.getenv("OPENAI_API_KEY"):
        transcribers.append(OpenAITranscriber(settings.stt_fallback_model, settings.stt_language))
    return SpeechToText(transcribers) if transcribers else None
