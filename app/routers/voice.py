import os
import tempfile

from fastapi import APIRouter, File, UploadFile

from ..config import GROQ_API_KEY, client

router = APIRouter()

@router.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    if not GROQ_API_KEY:
        return {"status": "error", "message": "GROQ_API_KEY не найден"}

    tmp_path = None
    try:
        audio_bytes = await file.read()
        if len(audio_bytes) < 1000:
            return {"status": "error", "message": "Аудио слишком короткое или пустое"}

        content_type = file.content_type or "audio/webm"
        ext_map = {
            "audio/webm": ".webm",
            "audio/ogg":  ".ogg",
            "audio/mp4":  ".mp4",
            "audio/mpeg": ".mp3",
            "audio/wav":  ".wav",
        }
        ext = ext_map.get(content_type, ".webm")

        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        with open(tmp_path, "rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=(f"audio{ext}", audio_file, content_type),
                response_format="text",
                language=None,
            )

        text = (
            transcription.strip()
            if isinstance(transcription, str)
            else str(transcription)
        )
        return {"status": "success", "text": text}

    except Exception as e:
        return {"status": "error", "message": f"Ошибка распознавания: {e}"}
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except:
                pass
