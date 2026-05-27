"""Speech-to-text via OpenAI Whisper API for daycare observation notes."""

import logging
import os

logger = logging.getLogger(__name__)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

try:
    import requests

    _REQUESTS_AVAILABLE = True
except ImportError:
    _REQUESTS_AVAILABLE = False
    logger.warning("requests not available — transcription disabled")

# Reject audio payloads larger than 25 MB (OpenAI API limit)
_MAX_AUDIO_BYTES = 25 * 1024 * 1024
# Supported MIME types for Whisper
_SUPPORTED_FORMATS = {"audio/ogg", "audio/mp3", "audio/mpeg", "audio/wav", "audio/webm"}


def transcribe_audio(audio_data: bytes, filename: str = "voice.ogg") -> str | None:
    """Transcribe an Ogg/Opus voice note via the OpenAI Whisper API.

    Args:
        audio_data: Raw audio bytes (max 25 MB).
        filename: Hint for the MIME type; must end with a supported extension
                  (.ogg, .mp3, .wav, .webm).

    Returns:
        The transcribed text string, or None if transcription could not be performed.
    """
    if not _REQUESTS_AVAILABLE:
        logger.warning("requests library not installed — cannot transcribe")
        return None
    if not OPENAI_API_KEY or OPENAI_API_KEY == "placeholder":
        logger.warning("OPENAI_API_KEY not set — skipping transcription")
        return None
    if not audio_data:
        logger.warning("Empty audio data — nothing to transcribe")
        return None
    if len(audio_data) > _MAX_AUDIO_BYTES:
        logger.warning(
            "Audio data too large (%d bytes, max %d) — refusing to send",
            len(audio_data),
            _MAX_AUDIO_BYTES,
        )
        return None

    # Derive MIME type from filename extension
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "ogg"
    mime_map = {"ogg": "audio/ogg", "mp3": "audio/mpeg", "wav": "audio/wav", "webm": "audio/webm"}
    mime_type = mime_map.get(ext, "audio/ogg")

    try:
        r = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            files={"file": (filename, audio_data, mime_type)},
            data={"model": "whisper-1", "language": "en"},
            timeout=30,
        )
        if r.status_code == 200:
            return r.json().get("text", "").strip()
        if r.status_code == 401:
            logger.warning("Whisper API authentication failed — check OPENAI_API_KEY")
        elif r.status_code == 413:
            logger.warning("Whisper API rejected audio: file too large")
        else:
            logger.warning("Whisper API error %d: %.200s", r.status_code, r.text)
        return None
    except requests.ConnectionError:
        logger.warning("Whisper API connection failed — network or DNS issue")
        return None
    except requests.Timeout:
        logger.warning("Whisper API timed out after 30 s")
        return None
    except Exception:
        logger.warning("Whisper API call failed", exc_info=True)
        return None
