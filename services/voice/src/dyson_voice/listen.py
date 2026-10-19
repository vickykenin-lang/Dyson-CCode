"""Hearing the Founder on Dyson's own server (D-024).

The audio arrives as 16 kHz mono 16-bit WAV, is turned into text in memory and is then gone: it is
never written to disk, logged or sent anywhere (D-017). The model is AI4Bharat's IndicConformer for
Hindi (MIT), which also writes English words in Devanagari; B reads both.

How sure the model is comes from its own token probabilities. A transcript it is unsure of is
marked so: the app shows it to the Founder to confirm and never acts on it alone (LA-APP-07).
"""

import io
import math
import wave
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

RATE = 16_000
MAX_SECONDS = 30
# Below these the transcript goes to the Founder to confirm. Set conservatively; the benchmark on
# the Founder's own recordings sets the final values (D-024, LA-PERF-02).
MIN_TOKEN_P = 0.60
MIN_MEAN_P = 0.85
MODEL_REPO = "OpenVoiceOS/ai4bharat-indicconformer-hi-onnx"


class BadAudio(ValueError):
    pass


@dataclass(frozen=True)
class Heard:
    text: str
    uncertain: bool
    confidence: float  # mean token probability, 0 to 1
    seconds: float


def read_wav(data: bytes) -> np.ndarray:
    """16 kHz mono 16-bit PCM WAV, at most 30 seconds, as float32 samples in [-1, 1]."""
    try:
        with wave.open(io.BytesIO(data)) as w:
            if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (1, 2, RATE):
                raise BadAudio("send 16 kHz mono 16-bit WAV")
            if w.getnframes() > RATE * MAX_SECONDS:
                raise BadAudio(f"at most {MAX_SECONDS} seconds at a time")
            frames = w.readframes(w.getnframes())
    except (wave.Error, EOFError) as exc:
        raise BadAudio("not a WAV file") from exc
    return np.frombuffer(frames, np.int16).astype(np.float32) / 32768


# A recognizer returns the text and the log probability of each token it chose.
Recognize = Callable[[np.ndarray], tuple[str, Sequence[float]]]


class Listener:
    def __init__(self, recognize: Recognize):
        self._recognize = recognize

    def hear(self, wav: bytes) -> Heard:
        samples = read_wav(wav)
        seconds = len(samples) / RATE
        if seconds < 0.2 or float(np.abs(samples).max(initial=0)) < 0.01:
            return Heard("", True, 0.0, seconds)  # silence: nothing to act on
        text, logprobs = self._recognize(samples)
        text = " ".join(text.split())
        probs = [math.exp(lp) for lp in logprobs]
        mean = sum(probs) / len(probs) if probs else 0.0
        unsure = not text or not probs or min(probs) < MIN_TOKEN_P or mean < MIN_MEAN_P
        return Heard(text, unsure, round(mean, 3), round(seconds, 2))


def model_listener(model_dir: str) -> Listener:
    """IndicConformer (int8) from the files baked into the voice image."""
    import onnx_asr

    model = onnx_asr.load_model(MODEL_REPO, model_dir, quantization="int8").with_timestamps()

    def recognize(samples: np.ndarray) -> tuple[str, Sequence[float]]:
        r = model.recognize(samples, sample_rate=RATE)
        return r.text, list(r.logprobs or [])

    return Listener(recognize)
