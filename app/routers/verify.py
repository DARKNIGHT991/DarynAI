"""
app/routers/verify.py
Эндпоинт для верификации подписанных ответов Daryn AI.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from ..services.signing import verify_response

router = APIRouter()


class VerifyRequest(BaseModel):
    text: str
    signature: str
    timestamp: str


@router.post("/verify")
def verify_ai_response(req: VerifyRequest):
    """
    Проверяет что ответ AI не был изменён после генерации.
    Принимает: текст ответа, подпись, временную метку.
    Возвращает: valid: true/false
    """
    is_valid = verify_response(req.text, req.signature, req.timestamp)
    return {
        "status": "success",
        "valid": is_valid,
        "message": (
            "Ответ подлинный — не изменён после генерации."
            if is_valid else
            "Подпись не совпадает — ответ был изменён или повреждён."
        )
    }
