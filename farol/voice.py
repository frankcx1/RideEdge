"""Local CPU speech. No provider calls, GPU lease operations, or audio retention."""
from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time

from farol.dashboard import ROOT

MAX_AUDIO_BYTES = 2 * 1024 * 1024
MAX_AUDIO_SECONDS = 30
SAMPLE_RATE = 16000
_model = None
_model_name = None
_transcribe_lock = threading.Lock()
_speak_lock = threading.Lock()


class VoiceError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def model_name() -> str:
    name = os.getenv("FAROL_VOICE_MODEL", "base.en")
    if name not in {"tiny.en", "base.en", "small.en"}:
        raise VoiceError("Choose an installed English CPU speech model.", 503)
    return name


def model_path() -> str:
    from huggingface_hub import try_to_load_from_cache

    path = try_to_load_from_cache(f"Systran/faster-whisper-{model_name()}", "model.bin")
    if not isinstance(path, str):
        raise VoiceError("Local speech model is not installed. Typed input is still available.", 503)
    return str(Path(path).parent)


def status() -> dict:
    available = importlib.util.find_spec("faster_whisper") is not None
    detail = "Local speech package is not installed."
    if available:
        try:
            model_path()
            detail = "Audio is transcribed on workstation using the CPU."
        except (VoiceError, ImportError) as error:
            available, detail = False, str(error)
    return {"transcription_available": available, "model": os.getenv("FAROL_VOICE_MODEL", "base.en"),
            "device": "cpu", "speech_available": os.name == "nt",
            "speech_engine": "Windows installed voice" if os.name == "nt" else None,
            "cloud_speech": False, "audio_retained": False,
            "max_recording_seconds": 20, "detail": detail}


def decode_audio(data: bytes):
    """Bound decoded duration as well as upload size; don't decode unlimited silence."""
    import av
    import numpy as np

    if not data or len(data) > MAX_AUDIO_BYTES:
        raise VoiceError("Use a short recording of up to 20 seconds.", 413)
    chunks, size = [], 0
    try:
        with av.open(io.BytesIO(data)) as container:
            if not container.streams.audio:
                raise VoiceError("The recording contains no audio.")
            resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
            for frame in container.decode(audio=0):
                for output in resampler.resample(frame):
                    samples = output.to_ndarray().flatten()
                    size += len(samples)
                    if size > SAMPLE_RATE * MAX_AUDIO_SECONDS:
                        raise VoiceError("Recording is too long. Try a shorter phrase.", 413)
                    chunks.append(samples)
            for output in resampler.resample(None):
                samples = output.to_ndarray().flatten()
                size += len(samples)
                if size > SAMPLE_RATE * MAX_AUDIO_SECONDS:
                    raise VoiceError("Recording is too long. Try a shorter phrase.", 413)
                chunks.append(samples)
    except VoiceError:
        raise
    except Exception as error:
        raise VoiceError("Could not read this recording. Please try again.") from error
    if size < SAMPLE_RATE // 4:
        raise VoiceError("Recording was too short. Please try again.")
    return np.concatenate(chunks).astype("float32") / 32768.0


def transcribe(data: bytes) -> dict:
    global _model, _model_name
    if not _transcribe_lock.acquire(blocking=False):
        raise VoiceError("Another recording is being transcribed. Try again shortly.", 429)
    started = time.perf_counter()
    try:
        audio = decode_audio(data)
        name = model_name()
        if _model is None or _model_name != name:
            from faster_whisper import WhisperModel

            _model = WhisperModel(model_path(), device="cpu", compute_type="int8",
                                  cpu_threads=4, num_workers=1, local_files_only=True)
            _model_name = name
        segments, _ = _model.transcribe(audio, language="en", beam_size=5,
                                        vad_filter=True, condition_on_previous_text=False,
                                        initial_prompt="Seattle areas: Bellevue, Kirkland, Totem Lake, Rose Hill, Redmond, Capitol Hill, Sea-Tac.")
        text = " ".join(segment.text.strip() for segment in segments
                        if segment.no_speech_prob < 0.7 and segment.avg_logprob > -1.0).strip()
        if not text:
            raise VoiceError("I didn’t catch any clear speech. Please try again.", 422)
        return {"text": text, "model": f"faster-whisper-{name}", "device": "cpu",
                "duration_seconds": round(len(audio) / SAMPLE_RATE, 2),
                "transcription_seconds": round(time.perf_counter() - started, 3),
                "cloud_speech": False}
    except VoiceError:
        raise
    except Exception as error:
        raise VoiceError("Local transcription is unavailable. You can still type a location.", 503) from error
    finally:
        _transcribe_lock.release()


def speak(text: str) -> tuple[bytes, str]:
    if os.name != "nt":
        raise VoiceError("Local speech output is not configured on this computer.", 503)
    text = text.strip()
    if not text or len(text) > 700:
        raise VoiceError("Choose a short answer to read aloud.")
    if not _speak_lock.acquire(blocking=False):
        raise VoiceError("Speech is being prepared. Try again shortly.", 429)
    try:
        with tempfile.TemporaryDirectory(prefix="farol-voice-") as folder:
            input_path, output_path = Path(folder) / "input.json", Path(folder) / "speech.wav"
            input_path.write_text(json.dumps({"text": text}, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                                     "-File", str(ROOT / "beast" / "farol-speech.ps1"),
                                     "-InputFile", str(input_path), "-OutputFile", str(output_path)],
                                    capture_output=True, text=True, timeout=30, check=False,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode or not output_path.is_file():
                raise VoiceError("Local speech output is unavailable. The answer is still on screen.", 503)
            return output_path.read_bytes(), result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as error:
        raise VoiceError("Local speech output could not finish. Please try again.", 503) from error
    finally:
        _speak_lock.release()
