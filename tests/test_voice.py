"""Resource limits, local-only inference and transient speech files."""
import io
import json
from pathlib import Path
from types import SimpleNamespace
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from farol import voice
from farol.voice_api import router


def wav(seconds=1):
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\0\0" * int(seconds * 16000))
    return output.getvalue()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.mark.parametrize("data,status", [(b"", 413), (b"bad audio", 400),
    (wav(.1), 400), (wav(31), 413), (b"x" * (voice.MAX_AUDIO_BYTES + 1), 413)],
    ids=["empty", "invalid", "short", "long", "oversize"])
def test_decode_rejects_invalid_and_unbounded_audio(data, status):
    pytest.importorskip("av")
    with pytest.raises(voice.VoiceError) as error:
        voice.decode_audio(data)
    assert error.value.status == status


def test_decode_mono_float_for_cpu():
    pytest.importorskip("av")
    audio = voice.decode_audio(wav())
    assert audio.shape == (16000,)
    assert str(audio.dtype) == "float32"


def test_missing_model_never_downloads(monkeypatch):
    hub = pytest.importorskip("huggingface_hub")
    monkeypatch.setattr(hub, "try_to_load_from_cache", lambda *a, **k: None)
    monkeypatch.setattr(hub, "snapshot_download", lambda *a, **k: pytest.fail("network download"))
    with pytest.raises(voice.VoiceError, match="not installed"):
        voice.model_path()
    assert voice.status()["transcription_available"] is False


def test_transcription_is_cpu_only_and_filters_unclear_speech(monkeypatch):
    whisper = pytest.importorskip("faster_whisper")
    calls = {}
    class Model:
        def __init__(self, path, **kwargs):
            calls.update(path=path, **kwargs)
        def transcribe(self, audio, **kwargs):
            assert kwargs["vad_filter"] is True
            return iter([SimpleNamespace(text="Bellevue", no_speech_prob=.1, avg_logprob=-.3),
                         SimpleNamespace(text="hallucination", no_speech_prob=.9, avg_logprob=-2)]), None
    monkeypatch.setattr(voice, "_model", None)
    monkeypatch.setattr(voice, "_model_name", None)
    monkeypatch.setattr(voice, "model_path", lambda: "cached-model")
    monkeypatch.setattr(whisper, "WhisperModel", Model)
    result = voice.transcribe(wav())
    assert result["text"] == "Bellevue"
    assert result["cloud_speech"] is False
    assert calls["device"] == "cpu"
    assert calls["local_files_only"] is True
    assert calls["compute_type"] == "int8"


def test_silence_and_inference_failure_release_lock(monkeypatch):
    monkeypatch.setattr(voice, "decode_audio", lambda data: [0] * 16000)
    monkeypatch.setattr(voice, "_model_name", voice.model_name())
    monkeypatch.setattr(voice, "_model", SimpleNamespace(transcribe=lambda *a, **k: ([], None)))
    with pytest.raises(voice.VoiceError) as error:
        voice.transcribe(b"audio")
    assert error.value.status == 422
    def fail(*a, **k):
        raise RuntimeError("private backend error")
    monkeypatch.setattr(voice, "_model", SimpleNamespace(transcribe=fail))
    with pytest.raises(voice.VoiceError) as error:
        voice.transcribe(b"audio")
    assert error.value.status == 503
    assert "private" not in str(error.value)
    assert not voice._transcribe_lock.locked()


def test_busy_transcription_is_bounded():
    with voice._transcribe_lock:
        with pytest.raises(voice.VoiceError) as error:
            voice.transcribe(b"audio")
    assert error.value.status == 429


def test_api_bounds_upload_before_inference(client, monkeypatch):
    monkeypatch.setattr(voice, "transcribe", lambda data: pytest.fail("must not invoke model"))
    assert client.post("/api/voice/transcribe", content=b"x", headers={"content-type":"text/plain"}).status_code == 415
    reply = client.post("/api/voice/transcribe", content=b"x" * (voice.MAX_AUDIO_BYTES + 1),
                        headers={"content-type":"audio/webm;codecs=opus"})
    assert reply.status_code == 413
    assert reply.headers["cache-control"] == "no-store"


def test_api_stream_limit_without_content_length(client, monkeypatch):
    monkeypatch.setattr(voice, "transcribe", lambda data: pytest.fail("must not invoke model"))
    reply = client.post("/api/voice/transcribe", content=iter([b"x" * 1048576] * 3),
                        headers={"content-type":"audio/webm"})
    assert reply.status_code == 413


def test_api_success_and_expected_errors(client, monkeypatch):
    monkeypatch.setattr(voice, "transcribe", lambda data: {"text":"Bellevue"})
    reply = client.post("/api/voice/transcribe", content=b"audio", headers={"content-type":"audio/webm;codecs=opus"})
    assert reply.json()["text"] == "Bellevue"
    assert reply.headers["cache-control"] == "no-store"
    def busy(data):
        raise voice.VoiceError("Busy", 429)
    monkeypatch.setattr(voice, "transcribe", busy)
    assert client.post("/api/voice/transcribe", content=b"audio", headers={"content-type":"audio/wav"}).status_code == 429
    monkeypatch.setattr(voice, "speak", lambda text: (b"RIFF", "local voice"))
    reply = client.post("/api/voice/speak", json={"text":"Your recommendation"})
    assert reply.content == b"RIFF"
    assert reply.headers["content-type"] == "audio/wav"
    assert reply.headers["cache-control"] == "no-store"
    assert client.post("/api/voice/speak", json={"text":"x" * 701}).status_code == 422


@pytest.mark.skipif(voice.os.name != "nt", reason="Windows installed speech")
@pytest.mark.parametrize("fails", [False, True])
def test_speech_text_is_data_and_tempfiles_are_removed(monkeypatch, fails):
    text = 'Near Bellevue; $(Write-Output nope) `literal` "quoted"'
    folders = []
    def run(args, **kwargs):
        assert text not in " ".join(args)
        source = Path(args[args.index("-InputFile") + 1])
        target = Path(args[args.index("-OutputFile") + 1])
        folders.append(source.parent)
        assert json.loads(source.read_text(encoding="utf-8"))["text"] == text
        assert kwargs["timeout"] == 30
        target.write_bytes(b"RIFF")
        return SimpleNamespace(returncode=int(fails), stdout="Local voice")
    monkeypatch.setattr(voice.subprocess, "run", run)
    if fails:
        with pytest.raises(voice.VoiceError):
            voice.speak(text)
    else:
        assert voice.speak(text) == (b"RIFF", "Local voice")
    assert all(not path.exists() for path in folders)
    assert not voice._speak_lock.locked()
