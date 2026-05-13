from fastapi import APIRouter

from ..db import get_db_connection
from ..schemas import HistoryRequest, ProfileUpdate

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
