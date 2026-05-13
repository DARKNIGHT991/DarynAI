from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ..db import get_db_connection
from ..schemas import ChatCreate, ChatDelete, ChatHistoryRequest, ChatRename

router = APIRouter()

@router.get("/chats")
def get_chats(email: str):
    if email == "guest":
        return {"status": "success", "chats": []}
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, title, created_at, updated_at
               FROM chats WHERE email = %s
               ORDER BY updated_at DESC""",
            (email,)
        )
        rows = cursor.fetchall()
        conn.close()
        return {
            "status": "success",
            "chats": [
                {
                    "id":         r[0],
                    "title":      r[1],
                    "created_at": str(r[2]),
                    "updated_at": str(r[3]),
                }
                for r in rows
            ],
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/chats/create")
def create_chat(req: ChatCreate):
    if req.email == "guest":
        return {"status": "error", "message": "Гости не могут создавать чаты"}
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO chats (email, title) VALUES (%s, %s) RETURNING id",
            (req.email, req.title)
        )
        chat_id = cursor.fetchone()[0]
        conn.commit()
        conn.close()
        return {"status": "success", "chat_id": chat_id}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/chats/rename")
def rename_chat(req: ChatRename):
    if req.email == "guest":
        return {"status": "error", "message": "Доступ запрещён"}
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE chats SET title = %s WHERE id = %s AND email = %s",
            (req.title, req.chat_id, req.email)
        )
        conn.commit()
        conn.close()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/chats/delete")
def delete_chat(req: ChatDelete):
    if req.email == "guest":
        return {"status": "error", "message": "Доступ запрещён"}
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM messages WHERE chat_id = %s AND email = %s",
            (req.chat_id, req.email)
        )
        cursor.execute(
            "DELETE FROM chats WHERE id = %s AND email = %s",
            (req.chat_id, req.email)
        )
        conn.commit()
        conn.close()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/chats/history")
def get_chat_history(req: ChatHistoryRequest):
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT role, content FROM messages WHERE email = %s AND chat_id = %s ORDER BY id ASC",
            (req.email, req.chat_id)
        )
        rows = cursor.fetchall()
        conn.close()
        return {
            "status":  "success",
            "history": [{"role": r[0], "content": r[1]} for r in rows]
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/chats/export")
def export_chat(email: str, chat_id: int):
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT title FROM chats WHERE id = %s AND email = %s",
            (chat_id, email)
        )
        row = cursor.fetchone()
        title = row[0] if row else "chat"
        cursor.execute(
            "SELECT role, content, created_at FROM messages WHERE email = %s AND chat_id = %s ORDER BY id ASC",
            (email, chat_id)
        )
        rows = cursor.fetchall()
        conn.close()
        lines = [f"# {title}\n"]
        for r in rows:
            role = "👤 Пользователь" if r[0] == "user" else "🤖 Daryn AI"
            lines.append(f"\n**{role}** ({str(r[2])[:16]})\n\n{r[1]}\n\n---")
        content = "\n".join(lines)
        return StreamingResponse(
            iter([content]),
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="chat_{chat_id}.md"'}
        )
    except Exception as e:
        return {"status": "error", "message": str(e)}
