from __future__ import annotations

from fastapi import APIRouter, Request

from schemas.health import HealthResponse
from schemas.meta import ModelsResponse, Speaker, SpeakersResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=request.app.state.config.version,
        dependencies={
            "ffmpeg": request.app.state.ffmpeg.available(),
            "mlx_whisper": request.app.state.whisper.available(),
            "ollama": request.app.state.ollama.ping(),
            "tts": request.app.state.tts.ping(),
        },
    )


@router.get("/models", response_model=ModelsResponse)
def models(request: Request) -> ModelsResponse:
    return ModelsResponse(
        **{
            "default": request.app.state.config.default_translate_model,
            "models": request.app.state.ollama.list_models(),
        }
    )


@router.get("/speakers", response_model=SpeakersResponse)
def speakers(request: Request) -> SpeakersResponse:
    config = request.app.state.config
    return SpeakersResponse(
        **{
            "default": Speaker(
                speakerId=config.default_speaker_id,
                name=config.default_speaker_name,
                styleId=config.default_style_id,
            ),
            "speakers": request.app.state.tts.list_speakers(),
        }
    )


@router.post("/shutdown")
def shutdown(request: Request) -> dict:
    server = getattr(request.app.state, "server", None)
    if server is not None:
        server.should_exit = True
    return {}
