from fastapi import APIRouter

from ..db import get_db_connection
from ..schemas import HistoryRequest, ProfileUpdate
from ..services.memory import clear_user_memories, get_user_id, get_user_memories

router = APIRouter()

@router.post("/history")
def get_history(req: HistoryRequest):
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT role, content FROM messages WHERE email = %s ORDER BY id ASC",
            (req.email,)
        )
        rows = cursor.fetchall()
        conn.close()
        return {
            "status":  "success",
            "history": [{"role": r[0], "content": r[1]} for r in rows]
        }
    except:
        return {"status": "success", "history": []}


@router.post("/update_profile")
def update_profile(req: ProfileUpdate):
    if req.email == "guest":
        return {"status": "error", "message": "Гости не могут менять профиль."}
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET username = %s WHERE email = %s",
            (req.new_username, req.email)
        )
        conn.commit()
        conn.close()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/clear_history")
def clear_user_history(req: HistoryRequest):
    if req.email == "guest":
        return {"status": "success"}
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM messages WHERE email = %s",
            (req.email,)
        )
        conn.commit()
        conn.close()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/memory")
def get_memory(email: str):
    if email == "guest":
        return {"status": "success", "memory": []}
    try:
        return {"status": "success", "memory": get_user_memories(email)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/memory/clear")
def clear_memory(req: HistoryRequest):
    if req.email == "guest":
        return {"status": "success"}
    try:
        clear_user_memories(req.email)
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/profile/preferences")
def get_profile_memory(email: str):
    if email == "guest":
        return {"status": "success", "profile": {"preferences": "", "language": ""}}
    try:
        user_id = get_user_id(email)
        if not user_id:
            return {"status": "success", "profile": {"preferences": "", "language": ""}}
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''SELECT "key", value
               FROM user_memory
               WHERE user_id = %s AND "key" IN (%s, %s)''',
            (user_id, "preferences", "preferred_language"),
        )
        rows = cursor.fetchall()
        conn.close()
        data = {k: v for k, v in rows}
        return {
            "status": "success",
            "profile": {
                "preferences": data.get("preferences", ""),
                "language": data.get("preferred_language", ""),
            },
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/profile/preferences")
def save_profile_memory(req: dict):
    email = (req.get("email") or "").strip()
    if email == "guest" or not email:
        return {"status": "error", "message": "Гости не могут сохранять профиль."}
    preferences = (req.get("preferences") or "").strip()[:500]
    language = (req.get("language") or "").strip()[:40]
    try:
        user_id = get_user_id(email)
        if not user_id:
            return {"status": "error", "message": "Пользователь не найден."}
        conn = get_db_connection()
        cursor = conn.cursor()
        if preferences:
            cursor.execute(
                '''INSERT INTO user_memory (user_id, "key", value)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (user_id, "key")
                   DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP''',
                (user_id, "preferences", preferences),
            )
        if language:
            cursor.execute(
                '''INSERT INTO user_memory (user_id, "key", value)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (user_id, "key")
                   DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP''',
                (user_id, "preferred_language", language),
            )
        conn.commit()
        conn.close()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
