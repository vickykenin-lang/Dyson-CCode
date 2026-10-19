import io
import math
import wave

import numpy as np
import pytest
from fastapi.testclient import TestClient

from dyson_voice.app import create_app
from dyson_voice.listen import BadAudio, Listener, read_wav


def wav(seconds=1.0, rate=16_000, channels=1, loud=True) -> bytes:
    n = int(seconds * rate)
    t = np.arange(n) / rate
    samples = (0.3 * np.sin(2 * np.pi * 220 * t) if loud else np.zeros(n)) * 32767
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.repeat(samples.astype(np.int16), channels).tobytes())
    return buf.getvalue()


def sure(p):  # a stand-in model that hears "T0 par 7 aur 8 jod do" with probability p per token
    return lambda samples: ("टी ज़ीरो पर सात  और आठ जोड़ दो", [math.log(p)] * 7)


def test_only_16k_mono_wav_up_to_30_seconds_is_heard():  # D-024
    assert len(read_wav(wav(1.0))) == 16_000
    for bad in (wav(1.0, rate=44_100), wav(1.0, channels=2), wav(31), b"not audio"):
        with pytest.raises(BadAudio):
            read_wav(bad)


def test_a_confident_transcript_is_marked_sure_and_tidied():
    heard = Listener(sure(0.97)).hear(wav())
    assert heard.text == "टी ज़ीरो पर सात और आठ जोड़ दो" and not heard.uncertain
    assert heard.confidence == pytest.approx(0.97, abs=1e-3)


def test_an_unsure_transcript_goes_to_the_founder_to_confirm():  # LA-APP-07
    assert Listener(sure(0.55)).hear(wav()).uncertain
    mixed = Listener(lambda s: ("send fifty thousand", [math.log(0.99), math.log(0.4), 0.0]))
    assert mixed.hear(wav()).uncertain  # one doubtful word is enough


def test_silence_is_never_turned_into_a_command():
    heard = Listener(sure(0.99)).hear(wav(loud=False))
    assert heard.text == "" and heard.uncertain


def test_the_service_takes_wav_only_and_keeps_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = TestClient(create_app(Listener(sure(0.97))))
    assert client.get("/health").json() == {"ok": True}
    ok = client.post("/transcribe", content=wav(), headers={"content-type": "audio/wav"})
    assert (
        ok.status_code == 200 and ok.json()["text"].startswith("टी") and not ok.json()["uncertain"]
    )
    assert (
        client.post("/transcribe", content=b"x", headers={"content-type": "audio/webm"}).status_code
        == 415
    )
    assert (
        client.post("/transcribe", content=b"x", headers={"content-type": "audio/wav"}).status_code
        == 422
    )
    assert list(tmp_path.iterdir()) == []  # nothing written
    paths = {r.path for r in client.app.routes}
    assert paths == {"/health", "/transcribe"}  # no way to read back what was heard
