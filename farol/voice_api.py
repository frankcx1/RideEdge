"""Bounded local speech endpoints; audio and transcripts are not logged or cached."""
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from farol import voice
from farol.dashboard import ROOT
from fastapi.responses import FileResponse

router = APIRouter()
NO_STORE = {"Cache-Control": "no-store"}


class SpeechText(BaseModel):
    text: str = Field(min_length=1, max_length=700)


@router.get("/voice.js")
def voice_javascript():
    return FileResponse(ROOT / "farol" / "static" / "voice.js", media_type="text/javascript")


@router.get("/api/voice/status")
def voice_status(response: Response):
    response.headers.update(NO_STORE)
    return voice.status()


@router.post("/api/voice/transcribe")
async def voice_transcribe(request: Request, response: Response):
    if request.headers.get("content-type", "").split(";")[0].lower() not in {
        "audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav", "audio/x-wav",
    }:
        raise HTTPException(415, "Unsupported recording type.", headers=NO_STORE)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > voice.MAX_AUDIO_BYTES:
            raise HTTPException(413, "Recording is too large. Try a shorter phrase.", headers=NO_STORE)
        body.extend(chunk)
    try:
        result = await run_in_threadpool(voice.transcribe, bytes(body))
        response.headers.update(NO_STORE)
        return result
    except voice.VoiceError as error:
        raise HTTPException(error.status, str(error), headers=NO_STORE) from error


@router.post("/api/voice/speak")
def voice_speak(body: SpeechText):
    try:
        audio, _ = voice.speak(body.text)
        return Response(audio, media_type="audio/wav", headers=NO_STORE)
    except voice.VoiceError as error:
        raise HTTPException(error.status, str(error), headers=NO_STORE) from error
