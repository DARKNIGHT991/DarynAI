import re

EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")
PASSWORD_MIN_LENGTH = 8


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def validate_email(email: str) -> str | None:
    normalized = normalize_email(email)
    if not normalized:
        return "Email обязателен"
    if len(normalized) > 255:
        return "Email слишком длинный"
    if not EMAIL_RE.fullmatch(normalized):
        return "Введите корректный email"
    return None


def validate_login_password(password: str) -> str | None:
    if not password:
        return "Пароль обязателен"
    if len(password) > 128:
        return "Пароль слишком длинный"
    return None


def validate_password(password: str) -> str | None:
    if not password:
        return "Пароль обязателен"
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"Пароль должен быть не короче {PASSWORD_MIN_LENGTH} символов"
    if len(password) > 128:
        return "Пароль слишком длинный"
    if not re.search(r"[A-Za-z]", password):
        return "Пароль должен содержать хотя бы одну букву"
    if not re.search(r"\d", password):
        return "Пароль должен содержать хотя бы одну цифру"
    return None


def validate_username(username: str) -> str | None:
    name = (username or "").strip()
    if not name:
        return "Имя обязательно"
    if len(name) < 2:
        return "Имя должно быть не короче 2 символов"
    if len(name) > 80:
        return "Имя слишком длинное"
    return None
