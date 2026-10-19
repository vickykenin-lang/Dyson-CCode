"""Dyson's spoken replies through Amazon Polly in Sydney (D-024). One client (polly), one call
(synthesize_speech), one voice: Kajal, neural, which speaks Hindi, Hinglish and Indian English.

Polly gets only what Dyson is about to say, and never a personal identifier: phone numbers, emails,
account numbers, names and addresses are replaced by "screen par dekhiye" before the text leaves
Layer A (D-017). Nothing is stored; the audio goes straight back to the Founder's app.
"""

import re
import time
from collections.abc import Callable, Iterable
from typing import Any

from dyson_intelligence.redaction import Redaction

REGION = "ap-southeast-2"
VOICE = "Kajal"
MAX_CHARS = 2_500  # a reply longer than this is cut; the full text stays on screen
CLIENT_MAX_AGE_S = 600  # the host refreshes short-lived role credentials
_PLACEHOLDER = re.compile(r"\[[A-Z]+_\d+\]")


def for_speech(text: str, personal: Iterable[tuple[str, str]] = ()) -> str:
    """The reply as Polly may hear it: identifiers replaced, markup and extra space gone."""
    hidden = Redaction(personal).text(text)
    spoken = _PLACEHOLDER.sub("screen par dekhiye", hidden)
    return " ".join(spoken.split())[:MAX_CHARS]


class PollySpeech:
    def __init__(
        self,
        personal: Callable[[], Iterable[tuple[str, str]]] = tuple,
        client: Any = None,
    ):
        self._personal = personal
        self._fixed, self._client, self._made = client is not None, client, 0.0

    def _fresh_client(self) -> Any:
        if not self._fixed and time.monotonic() - self._made > CLIENT_MAX_AGE_S:
            import boto3

            self._client = boto3.session.Session().client("polly", region_name=REGION)
            self._made = time.monotonic()
        return self._client

    def speak(self, text: str) -> bytes:
        spoken = for_speech(text, self._personal())
        if not spoken:
            return b""
        out = self._fresh_client().synthesize_speech(
            Text=spoken,
            VoiceId=VOICE,
            Engine="neural",
            LanguageCode="hi-IN",  # Kajal reads Devanagari, romanised Hindi and English alike
            OutputFormat="mp3",
        )
        return out["AudioStream"].read()
