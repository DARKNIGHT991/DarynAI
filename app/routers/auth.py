import bcrypt
from fastapi import APIRouter

from ..db import get_db_connection
from ..schemas import UserLogin, UserRegister

router = APIRouter()

@router.post("/register")
def register(user: UserRegister):
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT email FROM users WHERE email = %s",
            (user.email,)
        )
        if cursor.fetchone():
            conn.close()
            return {"status": "error", "message": "Email уже зарегистрирован"}

        hashed = bcrypt.hashpw(
            user.password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

        cursor.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s)",
            (user.username, user.email, hashed)
        )
        conn.commit()
        conn.close()
        return {"status": "success", "username": user.username, "email": user.email}
    except Exception as e:
        return {"status": "error", "message": f"Ошибка БД: {e}"}


@router.post("/login")
def login(user: UserLogin):
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT username, password_hash FROM users WHERE email = %s",
            (user.email,)
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            return {"status": "error", "message": "Email не найден"}
        if bcrypt.checkpw(user.password.encode("utf-8"), row[1].encode("utf-8")):
            return {"status": "success", "username": row[0], "email": user.email}
        return {"status": "error", "message": "Неверный пароль"}
    except Exception as e:
        return {"status": "error", "message": f"Ошибка БД: {e}"}
