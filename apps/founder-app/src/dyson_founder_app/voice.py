"""Voice: the Founder speaks, Dyson listens on its own server and answers aloud (D-024).

Whatever fills the slot must return how sure it is. A transcript it is unsure of is shown to the
Founder to confirm and is never sent on its own (LA-APP-07). Voice and text then travel the same
way, into the same thread, so they share one history and one memory (LA-APP-03).
"""

from typing import Protocol

import httpx

from dyson_contracts.common import Contract

WAV = ("audio/wav", "audio/x-wav", "audio/wave")


class Transcript(Contract):
    text: str
    uncertain: bool


class VoiceUnavailable(Exception):
    pass


class VoicePort(Protocol):
    def transcribe(self, audio: bytes, content_type: str) -> Transcript: ...


class NoVoice:
    def transcribe(self, audio: bytes, content_type: str) -> Transcript:
        raise VoiceUnavailable("voice is not connected yet")


class RemoteVoice:
    """The voice container on its own network (D-024): WAV in, the text and how sure out.
    Nothing is kept on either side."""

    def __init__(self, url: str, http: httpx.Client | None = None):
        self._url = url.rstrip("/")
        self._http = http or httpx.Client(timeout=30)

    def transcribe(self, audio: bytes, content_type: str) -> Transcript:
        if content_type.split(";")[0].strip() not in WAV:
            raise VoiceUnavailable("use the microphone button to record")
        try:
            r = self._http.post(
                f"{self._url}/transcribe", content=audio, headers={"content-type": "audio/wav"}
            )
        except httpx.HTTPError:
            raise VoiceUnavailable("voice is not reachable right now") from None
        if r.status_code != 200:
            raise VoiceUnavailable("that recording could not be heard; please try again")
        d = r.json()
        return Transcript(text=d["text"], uncertain=bool(d["uncertain"]))


class SpeechUnavailable(Exception):
    pass


class SpeechPort(Protocol):
    def speak(self, text: str) -> bytes: ...  # MP3


class NoSpeech:
    def speak(self, text: str) -> bytes:
        raise SpeechUnavailable("spoken replies are not connected")
