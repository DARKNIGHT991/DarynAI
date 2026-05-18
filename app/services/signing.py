"""
app/services/signing.py
Криптографическая подпись ответов Daryn AI (HMAC-SHA256).
"""

import hashlib
import hmac
import os
import time


SIGNING_KEY = os.getenv("SIGNING_KEY", "daryn-secret-change-me")


def sign_response(text: str) -> dict:
    """
    Подписывает текст ответа.
    Возвращает словарь с подписью и временной меткой.
    """
    ts = str(int(time.time()))
    payload = f"{text}|{ts}"
    signature = hmac.new(
        SIGNING_KEY.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return {"signature": signature, "timestamp": ts}


def verify_response(text: str, signature: str, timestamp: str) -> bool:
    """
    Проверяет подпись ответа.
    Возвращает True если ответ не был изменён.
    """
    payload = f"{text}|{timestamp}"
    expected = hmac.new(
        SIGNING_KEY.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
