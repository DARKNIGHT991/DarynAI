import bcrypt
from fastapi import APIRouter
import requests

from ..config import GOOGLE_CLIENT_ID
from ..db import get_db_connection
from ..schemas import GoogleLogin, UserLogin, UserRegister
from ..services.auth_validation import normalize_email, validate_email, validate_login_password, validate_password, validate_username

router = APIRouter()


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _upsert_google_user(email: str, username: str, google_sub: str) -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT username FROM users WHERE email = %s",
        (email,)
    )
    row = cursor.fetchone()

    if row:
        conn.close()
        return {"status": "success", "username": row[0], "email": email}

    password_hash = _hash_password(f"google:{google_sub}")
    cursor.execute(
        "INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s)",
        (username, email, password_hash)
    )
    conn.commit()
    conn.close()
    return {"status": "success", "username": username, "email": email}


@router.get("/auth/config")
def auth_config():
    return {
        "status": "success",
        "google_client_id": GOOGLE_CLIENT_ID,
        "google_enabled": bool(GOOGLE_CLIENT_ID),
    }


@router.post("/register")
def register(user: UserRegister):
    username = user.username.strip()
    email = normalize_email(user.email)

    validation_error = (
        validate_username(username)
        or validate_email(email)
        or validate_password(user.password)
    )
    if validation_error:
        return {"status": "error", "message": validation_error}

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT email FROM users WHERE email = %s",
            (email,)
        )
        if cursor.fetchone():
            conn.close()
            return {"status": "error", "message": "Email уже зарегистрирован"}

        cursor.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s)",
            (username, email, _hash_password(user.password))
        )
        conn.commit()
        conn.close()
        return {"status": "success", "username": username, "email": email}
    except Exception as e:
        return {"status": "error", "message": f"Ошибка БД: {e}"}


@router.post("/login")
def login(user: UserLogin):
    email = normalize_email(user.email)
    validation_error = validate_email(email) or validate_login_password(user.password)
    if validation_error:
        return {"status": "error", "message": validation_error}

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT username, password_hash FROM users WHERE email = %s",
            (email,)
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            return {"status": "error", "message": "Email не найден"}
        if bcrypt.checkpw(user.password.encode("utf-8"), row[1].encode("utf-8")):
            return {"status": "success", "username": row[0], "email": email}
        return {"status": "error", "message": "Неверный пароль"}
    except Exception as e:
        return {"status": "error", "message": f"Ошибка БД: {e}"}


@router.post("/auth/google")
def google_login(req: GoogleLogin):
    if not GOOGLE_CLIENT_ID:
        return {"status": "error", "message": "Google вход не настроен"}
    if not req.credential:
        return {"status": "error", "message": "Google credential отсутствует"}

    try:
        google_res = requests.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": req.credential},
            timeout=10,
        )
        if google_res.status_code != 200:
            return {"status": "error", "message": "Недействительный Google токен"}

        payload = google_res.json()
        if payload.get("aud") != GOOGLE_CLIENT_ID:
            return {"status": "error", "message": "Google токен выпущен для другого клиента"}
        if payload.get("email_verified") not in (True, "true", "True", "1"):
            return {"status": "error", "message": "Google email не подтверждён"}

        email = normalize_email(payload.get("email", ""))
        email_error = validate_email(email)
        if email_error:
            return {"status": "error", "message": email_error}

        username = (payload.get("name") or email.split("@")[0]).strip()[:80]
        if validate_username(username):
            username = email.split("@")[0][:80]

        return _upsert_google_user(email, username, str(payload.get("sub", "")))
    except Exception as e:
        return {"status": "error", "message": f"Ошибка Google входа: {e}"}
