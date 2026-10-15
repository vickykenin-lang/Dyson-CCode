"""Voice is a slot only until gate 5 picks the vendor and the Hindi / Hinglish thresholds.

Whatever vendor fills it must return how sure it is. A transcript it is unsure of is shown to the
Founder to confirm and is never sent on its own (LA-APP-07). Voice and text then travel the same
way, into the same thread, so they share one history and one memory (LA-APP-03).
"""

from typing import Protocol

from dyson_contracts.common import Contract


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
