import json

from ..db import get_db_connection
from .ai import ask_ai_quick

MAX_MEMORY_ITEMS = 20
MAX_KEY_LENGTH = 80
MAX_VALUE_LENGTH = 500


def get_user_id(email: str) -> int | None:
    if email == "guest":
        return None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def get_user_memories(email: str) -> list[dict[str, str]]:
    user_id = get_user_id(email)
    if not user_id:
        return []

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        '''SELECT "key", value
           FROM user_memory
           WHERE user_id = %s
           ORDER BY updated_at DESC, id DESC
           LIMIT %s''',
        (user_id, MAX_MEMORY_ITEMS),
    )
    rows = cursor.fetchall()
    conn.close()
    return [{"key": row[0], "value": row[1]} for row in rows]


def format_user_memories(email: str) -> str:
    memories = get_user_memories(email)
    if not memories:
        return ""
    lines = [f"- {item['value']}" for item in memories if item.get("value")]
    if not lines:
        return ""
    return (
        "\n\nПостоянная память пользователя (используй для персонализации, "
        "но не раскрывай без необходимости):\n" + "\n".join(lines)
    )


def clear_user_memories(email: str) -> None:
    user_id = get_user_id(email)
    if not user_id:
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM user_memory WHERE user_id = %s", (user_id,))
    conn.commit()
    conn.close()


def _parse_memory_response(raw: str) -> list[dict[str, str]]:
    if not raw:
        return []
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []

    memories = []
    for item in data[:5]:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "")).strip().lower().replace(" ", "_")[:MAX_KEY_LENGTH]
        value = str(item.get("value", "")).strip()[:MAX_VALUE_LENGTH]
        if key and value:
            memories.append({"key": key, "value": value})
    return memories


def remember_from_message(email: str, message: str) -> None:
    user_id = get_user_id(email)
    if not user_id or not message.strip():
        return

    raw = ask_ai_quick(
        "Извлеки только устойчивые предпочтения или факты о пользователе, "
        "которые пригодятся в будущих диалогах Daryn AI. "
        "Не сохраняй временные просьбы, пароли, токены, платежные данные, адреса, "
        "медицинские/политические/религиозные/биометрические данные. "
        "Если сохранять нечего, верни ровно []. "
        "Ответь только валидным JSON-массивом объектов вида "
        "[{\"key\":\"preferred_language\",\"value\":\"Пользователь говорит на русском и казахском.\"}].\n"
        f"Сообщение пользователя: {message[:2000]}"
    )
    memories = _parse_memory_response(raw)
    if not memories:
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    for item in memories:
        cursor.execute(
            '''INSERT INTO user_memory (user_id, "key", value)
               VALUES (%s, %s, %s)
               ON CONFLICT (user_id, "key")
               DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP''',
            (user_id, item["key"], item["value"]),
        )
    conn.commit()
    conn.close()
