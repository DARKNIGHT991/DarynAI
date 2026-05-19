import hashlib
import hmac

from fastapi import APIRouter
from pydantic import BaseModel

from ..config import RESPONSE_SIGNING_SECRET

router = APIRouter()


class SignRequest(BaseModel):
    text: str


class VerifyRequest(BaseModel):
    text: str
    signature: str


def _build_signature(text: str) -> str:
    return hmac.new(
        RESPONSE_SIGNING_SECRET.encode("utf-8"),
        text.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


@router.post("/verify/sign")
def sign_response(req: SignRequest):
    return {
        "status": "success",
        "signature": _build_signature(req.text),
        "algorithm": "HMAC-SHA256",
    }


@router.post("/verify/check")
def verify_response(req: VerifyRequest):
    expected = _build_signature(req.text)
    is_valid = hmac.compare_digest(expected, req.signature.strip().lower())
    return {
        "status": "success",
        "valid": is_valid,
        "algorithm": "HMAC-SHA256",
        "expected_signature": expected,
    }
